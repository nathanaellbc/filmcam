import numpy as np
import pytest

from fcrref import convert, inspect
from fcrref.container import FcrReader


class FakeRaw:
    """Stands in for rawpy so convert/inspect can be tested without DNGs."""

    def __init__(self, mosaic, pattern, white_level):
        self._mosaic = mosaic
        self._pattern = pattern
        self._white = white_level

    # convert.load_dng reads the file through rawpy; we patch load_dng itself
    # below, so this class only carries the values a test wants to feed in.


def _fake_loader(mosaics, pattern, bit_depth):
    """A loader that behaves like analyze.load_dng but reads from a list.

    Keyed by the frame index embedded in the fake path, because convert()
    calls the loader again during verification — an iterator would be
    exhausted after the write pass.
    """

    def load(path):
        index = int(path.split("_")[1].split(".")[0])
        return mosaics[index], pattern, bit_depth

    return load


def _paths(n):
    return [f"frame_{i:05d}.dng" for i in range(n)]


def test_convert_writes_a_readable_clip_and_verifies(tmp_path, monkeypatch):
    rng = np.random.default_rng(1)
    mosaics = [
        rng.integers(0, 16384, size=(48, 64), dtype=np.uint16) for _ in range(3)
    ]
    monkeypatch.setattr(convert, "load_dng", _fake_loader(mosaics, "RGGB", 14))

    out = str(tmp_path / "clip.fcr")
    written = convert.convert(_paths(3), out, verify=True)

    assert written == 3
    reader = FcrReader(out)
    assert reader.frame_count == 3
    assert (reader.header.width, reader.header.height) == (64, 48)
    assert reader.header.cfa_pattern == "RGGB"
    assert reader.header.bit_depth == 14
    for i, want in enumerate(mosaics):
        decoded, meta = reader.read_frame(i)
        assert meta.sequence == i
        assert np.array_equal(decoded, want)


def test_convert_rejects_mixed_geometry(tmp_path, monkeypatch):
    a = np.zeros((48, 64), dtype=np.uint16)
    b = np.zeros((24, 32), dtype=np.uint16)  # different geometry
    monkeypatch.setattr(convert, "load_dng", _fake_loader([a, b], "RGGB", 14))

    with pytest.raises(ValueError, match="geometry"):
        convert.convert(_paths(2), str(tmp_path / "clip.fcr"), verify=False)


def test_convert_rejects_mixed_bit_depth(tmp_path, monkeypatch):
    a = np.zeros((48, 64), dtype=np.uint16)
    b = np.zeros((48, 64), dtype=np.uint16)
    loader = _fake_loader([a, b], "RGGB", 14)
    # First file reports 14-bit, second reports 10-bit.
    seq = iter([(a, "RGGB", 14), (b, "RGGB", 10)])
    monkeypatch.setattr(convert, "load_dng", lambda _p: next(seq))

    with pytest.raises(ValueError, match="bit depth"):
        convert.convert(_paths(2), str(tmp_path / "clip.fcr"), verify=False)


def test_convert_rejects_mixed_cfa_pattern(tmp_path, monkeypatch):
    a = np.zeros((48, 64), dtype=np.uint16)
    b = np.zeros((48, 64), dtype=np.uint16)
    seq = iter([(a, "RGGB", 14), (b, "BGGR", 14)])
    monkeypatch.setattr(convert, "load_dng", lambda _p: next(seq))

    with pytest.raises(ValueError, match="CFA pattern"):
        convert.convert(_paths(2), str(tmp_path / "clip.fcr"), verify=False)


def test_convert_pattern_override_wins(tmp_path, monkeypatch):
    a = np.zeros((48, 64), dtype=np.uint16)
    monkeypatch.setattr(convert, "load_dng", _fake_loader([a], "RGGB", 14))

    out = str(tmp_path / "clip.fcr")
    convert.convert(_paths(1), out, pattern_override="BGGR", verify=False)
    assert FcrReader(out).header.cfa_pattern == "BGGR"


def test_convert_with_no_inputs_returns_zero(tmp_path, capsys):
    assert convert.convert([], str(tmp_path / "clip.fcr")) == 0
    assert "no input files" in capsys.readouterr().err


# --- convert --audio: embed a WAV as AUD0 chunks ---------------------------


def _write_wav(path, frames, channels=2, rate=48000, sampwidth=2):
    import wave

    with wave.open(str(path), "wb") as f:
        f.setnchannels(channels)
        f.setsampwidth(sampwidth)
        f.setframerate(rate)
        f.writeframes(b"\x01\x02" * frames * channels)


def test_convert_with_audio_embeds_aud0_chunks(tmp_path, monkeypatch):
    """A WAV alongside the DNGs becomes interleaved AUD0 records in a v2 clip."""
    rng = np.random.default_rng(1)
    mosaics = [rng.integers(0, 16384, size=(48, 64), dtype=np.uint16) for _ in range(3)]
    monkeypatch.setattr(convert, "load_dng", _fake_loader(mosaics, "RGGB", 14))

    wav = tmp_path / "audio.wav"
    _write_wav(wav, frames=48000)  # 1 s of stereo s16 at 48 kHz

    out = str(tmp_path / "clip.fcr")
    convert.convert(_paths(3), out, audio_path=str(wav), verify=False)

    reader = FcrReader(out)
    assert reader.header.version == 2
    assert reader.frame_count == 3
    assert reader.audio_count >= 1
    meta, payload = reader.read_audio(0)
    assert meta.sample_rate_hz == 48000
    assert meta.channel_count == 2
    assert meta.sample_format == 0  # s16le


def test_convert_audio_is_aligned_to_frame_zero_pts(tmp_path, monkeypatch):
    """The first audio chunk's pts is the first frame's pts (0) — the shared-
    clock alignment decision."""
    rng = np.random.default_rng(1)
    mosaics = [rng.integers(0, 16384, size=(48, 64), dtype=np.uint16) for _ in range(2)]
    monkeypatch.setattr(convert, "load_dng", _fake_loader(mosaics, "RGGB", 14))

    wav = tmp_path / "audio.wav"
    _write_wav(wav, frames=48000)

    out = str(tmp_path / "clip.fcr")
    convert.convert(_paths(2), out, audio_path=str(wav), verify=False)

    reader = FcrReader(out)
    first_audio_pts = reader.read_audio(0)[0].pts_ns
    first_frame_pts = reader.read_frame(0)[1].pts_ns
    assert first_audio_pts == first_frame_pts


def test_convert_audio_roundtrips_the_source_pcm(tmp_path, monkeypatch):
    """The embedded audio, concatenated across chunks, equals the WAV's PCM."""
    rng = np.random.default_rng(1)
    mosaics = [rng.integers(0, 16384, size=(48, 64), dtype=np.uint16) for _ in range(2)]
    monkeypatch.setattr(convert, "load_dng", _fake_loader(mosaics, "RGGB", 14))

    import wave
    wav = tmp_path / "audio.wav"
    _write_wav(wav, frames=48000)
    with wave.open(str(wav), "rb") as f:
        source_pcm = f.readframes(48000)

    out = str(tmp_path / "clip.fcr")
    convert.convert(_paths(2), out, audio_path=str(wav), verify=False)

    reader = FcrReader(out)
    combined = b"".join(reader.read_audio(i)[1] for i in range(reader.audio_count))
    assert combined == source_pcm


def test_convert_without_audio_stays_version_1(tmp_path, monkeypatch):
    """No --audio means the clip is unchanged: version 1, zero audio chunks."""
    rng = np.random.default_rng(1)
    mosaics = [rng.integers(0, 16384, size=(48, 64), dtype=np.uint16) for _ in range(2)]
    monkeypatch.setattr(convert, "load_dng", _fake_loader(mosaics, "RGGB", 14))

    out = str(tmp_path / "clip.fcr")
    convert.convert(_paths(2), out, verify=False)
    reader = FcrReader(out)
    assert reader.header.version == 1
    assert reader.audio_count == 0


def test_inspect_check_passes_a_valid_clip(tmp_path, capsys):
    from conftest import build_frame, build_header
    from fcrref.container import FcrWriter

    h = build_header(width=64, height=48, bit_depth=10)
    frames = [build_frame(h, seed=i) for i in range(3)]
    path = str(tmp_path / "clip.fcr")
    w = FcrWriter(path)
    w.write_header(h)
    for i, m in enumerate(frames):
        w.append_frame(m, i, i * 41_666_667, 20833333, 400, 0.5)
    w.finalize()

    reader = FcrReader(path)
    assert inspect.check(reader) is True
    out = capsys.readouterr().out
    assert "4032" not in out  # header echoed the real 64x48 geometry
    assert "10-bit" in out
    assert "structure: OK" in out


def test_inspect_check_flags_a_corrupt_frame(tmp_path, capsys):
    from conftest import build_frame, build_header
    from fcrref.constants import HEADER_SIZE
    from fcrref.container import FRAME_RECORD_SIZE, FcrWriter

    h = build_header(width=64, height=48)
    path = tmp_path / "clip.fcr"
    w = FcrWriter(str(path))
    w.write_header(h)
    w.append_frame(build_frame(h), 0, 0, 1, 100, 0.0)
    w.finalize()

    # Corrupt squarely inside the single frame's payload — past the header
    # and the fixed-size frame record, well before the index and trailer.
    data = bytearray(path.read_bytes())
    data[HEADER_SIZE + FRAME_RECORD_SIZE + 5] ^= 0xFF
    path.write_bytes(bytes(data))

    reader = FcrReader(str(path))
    assert inspect.check(reader) is False
    assert "CRC MISMATCH" in capsys.readouterr().out


def test_inspect_dump_frame_writes_raw16(tmp_path):
    from conftest import build_frame, build_header
    from fcrref.container import FcrWriter

    h = build_header(width=64, height=48, bit_depth=12)
    m = build_frame(h)
    path = str(tmp_path / "clip.fcr")
    w = FcrWriter(path)
    w.write_header(h)
    w.append_frame(m, 0, 0, 1, 100, 0.0)
    w.finalize()

    out = tmp_path / "frame0.raw16"
    inspect.dump_frame(FcrReader(path), 0, str(out))
    loaded = np.fromfile(str(out), dtype="<u2").reshape(48, 64)
    assert np.array_equal(loaded, m)


def test_inspect_reports_and_validates_audio(tmp_path, capsys):
    import struct as _s

    from conftest import build_frame, build_header
    from fcrref.container import FcrWriter

    h = build_header(width=64, height=48)  # v2 by default
    path = str(tmp_path / "clip.fcr")
    w = FcrWriter(path)
    w.write_header(h)
    w.append_frame(build_frame(h, seed=1), 0, 0, 20833333, 400, 0.5)
    pcm = _s.pack("<4800h", *range(4800))  # 0.05 s of stereo s16
    w.append_audio(pcm, pts_ns=0, sample_rate_hz=48000, channel_count=2,
                   sample_format=0)
    w.finalize()

    reader = FcrReader(path)
    assert inspect.check(reader) is True
    out = capsys.readouterr().out
    assert "audio chunks indexed: 1" in out
    assert "48000 Hz" in out
    assert "structure: OK" in out


def test_inspect_flags_a_corrupt_audio_chunk(tmp_path, capsys):
    import struct as _s

    from conftest import build_frame, build_header
    from fcrref.constants import HEADER_SIZE
    from fcrref.container import FRAME_RECORD_SIZE, FcrWriter

    h = build_header(width=64, height=48)
    path = tmp_path / "clip.fcr"
    w = FcrWriter(str(path))
    w.write_header(h)
    w.append_frame(build_frame(h, seed=1), 0, 0, 20833333, 400, 0.5)
    pcm = _s.pack("<4800h", *range(4800))
    w.append_audio(pcm, pts_ns=0, sample_rate_hz=48000, channel_count=2,
                   sample_format=0)
    w.finalize()

    # Corrupt inside the audio chunk's payload, which sits after the frame.
    reader = FcrReader(str(path))
    audio_offset, _ = reader._audio_index[0]
    data = bytearray(path.read_bytes())
    data[audio_offset + 40] ^= 0xFF
    path.write_bytes(bytes(data))

    reader = FcrReader(str(path))
    assert inspect.check(reader) is False
    assert "audio 0: CRC MISMATCH" in capsys.readouterr().out
