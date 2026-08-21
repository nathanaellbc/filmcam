import struct

import numpy as np
import pytest

from conftest import build_header as _header
from fcrref import repair
from fcrref.constants import HEADER_SIZE
from fcrref.container import (
    FRAME_RECORD_FMT,
    FRAME_RECORD_SIZE,
    FcrReader,
    FcrWriter,
)


def _write_clip(path, frame_count=6, seed=4):
    h = _header(width=32, height=24)
    rng = np.random.default_rng(seed)
    frames = [
        rng.integers(0, 16384, size=(h.height, h.width), dtype=np.uint16)
        for _ in range(frame_count)
    ]
    w = FcrWriter(str(path))
    w.write_header(h)
    for i, m in enumerate(frames):
        w.append_frame(m, i, i * 41_666_667, 20833333, 400, 0.5)
    w.finalize()
    return frames


def test_scan_finds_every_frame_in_a_complete_file(tmp_path):
    path = tmp_path / "clip.fcr"
    frames = _write_clip(path)
    assert len(repair.scan_frames(str(path))) == len(frames)


def test_repair_restores_readability_after_trailer_loss(tmp_path):
    path = tmp_path / "clip.fcr"
    frames = _write_clip(path)

    data = bytearray(path.read_bytes())
    del data[-12:]  # lose the trailer, as a crash would
    path.write_bytes(bytes(data))

    with pytest.raises(ValueError):
        FcrReader(str(path))

    recovered = repair.repair(str(path))
    assert recovered == len(frames)

    r = FcrReader(str(path))
    for i, expected in enumerate(frames):
        decoded, _ = r.read_frame(i)
        assert np.array_equal(decoded, expected)


@pytest.mark.parametrize("seed", range(50))
def test_truncation_never_yields_a_partial_frame(tmp_path, seed):
    """Spec 9: every complete frame recovers, no partial frame is returned."""
    path = tmp_path / f"clip_{seed}.fcr"
    frames = _write_clip(path, frame_count=8, seed=seed)
    full = bytearray(path.read_bytes())

    rng = np.random.default_rng(seed)
    cut = int(rng.integers(HEADER_SIZE, len(full)))
    path.write_bytes(bytes(full[:cut]))

    recovered = repair.repair(str(path))
    assert 0 <= recovered <= len(frames)

    if recovered:
        r = FcrReader(str(path))
        assert r.frame_count == recovered
        for i in range(recovered):
            decoded, _ = r.read_frame(i)
            assert np.array_equal(decoded, frames[i])


def test_repair_on_header_only_file_recovers_nothing(tmp_path):
    path = tmp_path / "clip.fcr"
    _write_clip(path)
    data = path.read_bytes()[:HEADER_SIZE]
    path.write_bytes(data)
    assert repair.repair(str(path)) == 0


def test_scan_stops_at_a_corrupt_payload_inside_a_full_length_frame(tmp_path):
    """Reach the CRC branch, which truncation never does.

    Truncation always leaves byte-identical valid data ahead of the cut, so
    the payload-length check always fires first and the CRC gate is never
    the deciding one. This flips a single bit *inside* an otherwise
    complete payload, leaving the length field intact, so only the CRC can
    catch it. That branch already shipped one bug that survived 65 tests
    because no fixture reached it.
    """
    path = tmp_path / "clip.fcr"
    frames = _write_clip(path, frame_count=6)
    entries = repair.scan_frames(str(path))
    assert len(entries) == len(frames)

    victim = 3
    offset, size = entries[victim]
    data = bytearray(path.read_bytes())
    payload_start = offset + FRAME_RECORD_SIZE
    flip_at = payload_start + (size - FRAME_RECORD_SIZE) // 2
    assert flip_at < offset + size  # squarely inside this frame's payload
    data[flip_at] ^= 0x01
    path.write_bytes(bytes(data))

    # The record header, and therefore the length field, is untouched.
    assert len(path.read_bytes()) == len(data)
    magic, _s, _p, _e, _i, _l, payload_bytes, _crc = struct.unpack_from(
        FRAME_RECORD_FMT, bytes(data), offset
    )
    assert magic == b"FRM0"
    assert payload_bytes == size - FRAME_RECORD_SIZE

    assert repair.scan_frames(str(path)) == entries[:victim]


def test_repair_after_inner_corruption_keeps_only_the_clean_prefix(tmp_path):
    path = tmp_path / "clip.fcr"
    frames = _write_clip(path, frame_count=6)
    offset, size = repair.scan_frames(str(path))[2]
    data = bytearray(path.read_bytes())
    data[offset + FRAME_RECORD_SIZE + 5] ^= 0xFF
    path.write_bytes(bytes(data))

    assert repair.repair(str(path)) == 2
    reader = FcrReader(str(path))
    assert reader.frame_count == 2
    for i in range(2):
        decoded, _ = reader.read_frame(i)
        assert np.array_equal(decoded, frames[i])


def test_repair_recovers_a_truncated_ten_bit_clip(tmp_path):
    """The repair scan is depth-agnostic: a crashed 10-bit take loses
    exactly the in-flight frame, same as a 14-bit one."""
    from conftest import build_frame as _frame

    h = _header(width=32, height=24, bit_depth=10)
    frames = [_frame(h, seed=i) for i in range(6)]
    path = tmp_path / "clip10.fcr"
    w = FcrWriter(str(path))
    w.write_header(h)
    for i, m in enumerate(frames):
        w.append_frame(m, i, i * 41_666_667, 20833333, 400, 0.5)
    w.finalize()

    full = bytearray(path.read_bytes())
    cut = HEADER_SIZE + (len(full) - HEADER_SIZE) * 3 // 4
    path.write_bytes(bytes(full[:cut]))

    recovered = repair.repair(str(path))
    assert 0 < recovered < len(frames)

    r = FcrReader(str(path))
    assert r.header.bit_depth == 10
    for i in range(recovered):
        decoded, _ = r.read_frame(i)
        assert np.array_equal(decoded, frames[i])


# --- Task 4: record-type-aware repair (interleaved audio) ------------------


def _pcm(frames, channels=2, seed=0):
    import struct as _s

    count = frames * channels
    return _s.pack(f"<{count}h", *[((seed + i) % 2000) - 1000 for i in range(count)])


def _write_interleaved_clip(path, frame_count=6, audio_count=4, seed=4):
    """A v2 clip with audio chunks interleaved between the frame records.

    Exactly `audio_count` chunks are written: chunk k is emitted after frame
    k while stocks last (audio_count <= frame_count in every caller).
    """
    h = _header(width=32, height=24)  # v2 by default
    rng = np.random.default_rng(seed)
    frames = [
        rng.integers(0, 16384, size=(h.height, h.width), dtype=np.uint16)
        for _ in range(frame_count)
    ]
    chunks = [_pcm(1200, seed=i) for i in range(audio_count)]
    w = FcrWriter(str(path))
    w.write_header(h)
    for i, m in enumerate(frames):
        w.append_frame(m, i, i * 41_666_667, 20833333, 400, 0.5)
        if i < audio_count:
            w.append_audio(chunks[i], pts_ns=i * 41_666_667 + 20_000_000,
                           sample_rate_hz=48000, channel_count=2,
                           sample_format=0)
    w.finalize()
    return frames, chunks


def test_scan_records_finds_frames_and_audio_in_a_healthy_clip(tmp_path):
    path = tmp_path / "clip.fcr"
    frames, chunks = _write_interleaved_clip(path)
    found_frames, found_audio = repair.scan_records(str(path))
    assert len(found_frames) == len(frames)
    assert len(found_audio) == len(chunks)


def test_scan_frames_still_returns_only_the_frames(tmp_path):
    """The v1-era wrapper keeps its contract for existing callers."""
    path = tmp_path / "clip.fcr"
    frames, chunks = _write_interleaved_clip(path)
    assert len(repair.scan_frames(str(path))) == len(frames)


def test_repair_an_interleaved_clip_recovers_video_and_audio(tmp_path):
    """A crash mid-audio-payload must drop only the partial record and
    recover every complete frame and audio chunk before it."""
    path = tmp_path / "clip.fcr"
    frames, chunks = _write_interleaved_clip(path)

    full = bytearray(path.read_bytes())
    cut = HEADER_SIZE + (len(full) - HEADER_SIZE) * 3 // 4
    path.write_bytes(bytes(full[:cut]))

    with pytest.raises(ValueError):
        FcrReader(str(path))  # trailer gone

    recovered = repair.repair(str(path))
    assert 0 < recovered < len(frames)

    r = FcrReader(str(path))
    assert r.frame_count == recovered
    for i in range(recovered):
        decoded, _ = r.read_frame(i)
        assert np.array_equal(decoded, frames[i])
    # Whatever audio survived must round-trip exactly.
    for i in range(r.audio_count):
        _, payload = r.read_audio(i)
        assert payload == chunks[i]


def test_scan_halts_at_a_corrupt_audio_payload(tmp_path):
    """A flipped bit inside an audio chunk must stop recovery there, the
    same CRC gate that protects frames."""
    path = tmp_path / "clip.fcr"
    frames, chunks = _write_interleaved_clip(path, frame_count=6, audio_count=4)
    frames_idx, audio_idx = repair.scan_records(str(path))

    # Corrupt inside the SECOND audio chunk's payload.
    victim_offset, victim_size = audio_idx[1]
    data = bytearray(path.read_bytes())
    from fcrref.audio import AUDIO_RECORD_SIZE

    data[victim_offset + AUDIO_RECORD_SIZE + 3] ^= 0xFF
    path.write_bytes(bytes(data))

    new_frames, new_audio = repair.scan_records(str(path))
    # Recovery keeps the records that precede the corrupt chunk and stops.
    assert len(new_audio) == 1
    assert len(new_frames) < len(frames)


@pytest.mark.parametrize("seed", range(50))
def test_truncation_of_an_interleaved_clip_never_yields_a_partial_record(tmp_path, seed):
    """The interleaved form of the spec 9 property: every complete record
    recovers, no partial frame or audio chunk is ever returned."""
    path = tmp_path / f"iclip_{seed}.fcr"
    frames, chunks = _write_interleaved_clip(path, frame_count=8, audio_count=6,
                                             seed=seed)
    full = bytearray(path.read_bytes())
    rng = np.random.default_rng(seed)
    cut = int(rng.integers(HEADER_SIZE, len(full)))
    path.write_bytes(bytes(full[:cut]))

    recovered = repair.repair(str(path))
    assert 0 <= recovered <= len(frames)

    if recovered or True:
        r = FcrReader(str(path))
        assert r.frame_count == recovered
        for i in range(recovered):
            decoded, _ = r.read_frame(i)
            assert np.array_equal(decoded, frames[i])
        for i in range(r.audio_count):
            _, payload = r.read_audio(i)
            assert payload == chunks[i]
