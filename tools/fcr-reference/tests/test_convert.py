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
