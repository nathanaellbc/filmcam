import dataclasses
import struct

import numpy as np
import pytest

from conftest import build_frame as _frame, build_header as _header
from fcrref.constants import HEADER_MAGIC, HEADER_SIZE, TRAILER_MAGIC
from fcrref.container import (
    ClipHeader,
    FcrReader,
    FcrWriter,
    pack_header,
    unpack_header,
)


def test_header_is_exactly_4096_bytes():
    assert len(pack_header(_header())) == HEADER_SIZE


def test_header_starts_with_magic():
    assert pack_header(_header())[:4] == HEADER_MAGIC


def test_header_roundtrip_preserves_every_field():
    h = _header()
    assert unpack_header(pack_header(h)) == h


def test_unpack_rejects_bad_magic():
    data = bytearray(pack_header(_header()))
    data[0:4] = b"XXXX"
    with pytest.raises(ValueError):
        unpack_header(bytes(data))


def test_write_read_single_frame(tmp_path):
    h = _header()
    m = _frame(h)
    path = tmp_path / "clip.fcr"
    w = FcrWriter(str(path))
    w.write_header(h)
    w.append_frame(m, sequence=0, pts_ns=1000, exposure_ns=20833333, iso=400,
                   lens_position=0.5)
    w.finalize()

    r = FcrReader(str(path))
    assert r.frame_count == 1
    decoded, meta = r.read_frame(0)
    assert np.array_equal(decoded, m)
    assert meta.sequence == 0
    assert meta.pts_ns == 1000
    assert meta.iso == 400


def test_write_read_many_frames(tmp_path):
    h = _header()
    frames = [_frame(h, seed=i) for i in range(5)]
    path = tmp_path / "clip.fcr"
    w = FcrWriter(str(path))
    w.write_header(h)
    for i, m in enumerate(frames):
        w.append_frame(m, sequence=i, pts_ns=i * 41_666_667,
                       exposure_ns=20833333, iso=400, lens_position=0.5)
    w.finalize()

    r = FcrReader(str(path))
    assert r.frame_count == 5
    for i, expected in enumerate(frames):
        decoded, meta = r.read_frame(i)
        assert np.array_equal(decoded, expected)
        assert meta.sequence == i


def test_finalized_file_ends_with_trailer(tmp_path):
    h = _header()
    path = tmp_path / "clip.fcr"
    w = FcrWriter(str(path))
    w.write_header(h)
    w.append_frame(_frame(h), 0, 0, 1, 100, 0.0)
    w.finalize()
    tail = path.read_bytes()[-12:]
    assert tail[:4] == TRAILER_MAGIC
    index_offset = struct.unpack("<Q", tail[4:])[0]
    assert index_offset >= HEADER_SIZE


def test_reader_detects_crc_corruption(tmp_path):
    h = _header()
    path = tmp_path / "clip.fcr"
    w = FcrWriter(str(path))
    w.write_header(h)
    w.append_frame(_frame(h), 0, 0, 1, 100, 0.0)
    w.finalize()

    data = bytearray(path.read_bytes())
    data[HEADER_SIZE + 200] ^= 0xFF  # corrupt inside the payload
    path.write_bytes(bytes(data))

    r = FcrReader(str(path))
    with pytest.raises(ValueError, match="CRC"):
        r.read_frame(0)


def test_header_carries_flags_at_the_documented_wire_offset():
    """Spec 5.3: the header begins magic, version, flags. New writes are v2."""
    h = dataclasses.replace(_header(), flags=0xDEADBEEF)
    packed = pack_header(h)
    assert struct.unpack_from("<4sHI", packed, 0) == (HEADER_MAGIC, 2, 0xDEADBEEF)
    assert unpack_header(packed).flags == 0xDEADBEEF


def test_unpack_accepts_version_1_for_backward_compatibility():
    """A v1 header (no audio index) must still read, so the 66 committed
    v1 vectors remain loadable."""
    h = _header()
    data = bytearray(pack_header(h))
    struct.pack_into("<H", data, 4, 1)  # stamp version 1 on the wire
    back = unpack_header(bytes(data))
    assert back.version == 1
    # Every field except the version stamp matches the original header.
    assert back == dataclasses.replace(h, version=1)


def test_unpack_rejects_a_future_version():
    data = bytearray(pack_header(_header()))
    struct.pack_into("<H", data, 4, 3)
    with pytest.raises(ValueError, match="version"):
        unpack_header(bytes(data))


def test_header_roundtrip_survives_a_wholly_distinct_header():
    """Every scalar is unique, so a mis-indexed unpack slice cannot hide
    behind two fields that happen to share a value."""
    h = ClipHeader(
        width=1001, height=1002, bit_depth=13, cfa_pattern="GBRG",
        frame_rate_num=1003, frame_rate_den=1004,
        black_level=(11, 12, 13, 14), white_level=(1005, 1006, 1007, 1008),
        color_matrix1=tuple(float(i) for i in range(100, 109)),
        color_matrix2=tuple(float(i) for i in range(200, 209)),
        as_shot_neutral=(301.0, 302.0, 303.0),
        lens_id="ultrawide", focal_length_35=401.0, aperture=402.0,
        intrinsic_matrix=tuple(float(i) for i in range(500, 509)),
        readout_time_ns=6001, ois_enabled=True, start_timecode="02:03:04:05",
        created_at_ns=7001, device_model="iPhone17,2", flags=0x0A0B0C0D,
    )
    back = unpack_header(pack_header(h))
    assert back == h
    for f in dataclasses.fields(h):
        assert getattr(back, f.name) == getattr(h, f.name), f.name


def test_ten_bit_clip_roundtrips_exactly(tmp_path):
    """A 10-bit clip of several frames writes and reads back with mosaics
    and metadata identical — the vertical slice of Task 3."""
    h = _header(bit_depth=10)
    frames = [_frame(h, seed=i) for i in range(4)]
    path = tmp_path / "clip10.fcr"
    w = FcrWriter(str(path))
    w.write_header(h)
    for i, m in enumerate(frames):
        w.append_frame(m, sequence=i, pts_ns=i * 41_666_667,
                       exposure_ns=20833333, iso=800, lens_position=0.25)
    w.finalize()

    r = FcrReader(str(path))
    assert r.header.bit_depth == 10
    assert r.frame_count == len(frames)
    for i, expected in enumerate(frames):
        decoded, meta = r.read_frame(i)
        assert np.array_equal(decoded, expected)
        assert meta.sequence == i
        assert meta.iso == 800


def test_append_frame_rejects_samples_above_the_declared_depth(tmp_path):
    """A clip that declares 10-bit must not silently accept 14-bit data."""
    h = _header(bit_depth=10)
    m = _frame(h)
    m[0, 0] = 4000  # above the 10-bit ceiling of 1023
    path = tmp_path / "clip.fcr"
    w = FcrWriter(str(path))
    w.write_header(h)
    with pytest.raises(ValueError, match="exceeds max value"):
        w.append_frame(m, sequence=0, pts_ns=0, exposure_ns=1, iso=100,
                       lens_position=0.0)


# --- Container version 2: parallel audio index ----------------------------


def test_new_clips_are_written_at_version_2(tmp_path):
    h = _header()
    path = tmp_path / "clip.fcr"
    w = FcrWriter(str(path))
    w.write_header(h)
    w.append_frame(_frame(h), 0, 0, 1, 100, 0.0)
    w.finalize()
    assert struct.unpack_from("<H", path.read_bytes(), 4)[0] == 2


def test_a_video_only_v2_clip_reads_with_zero_audio(tmp_path):
    """Version 2 with no audio records: the audio index is empty, not absent."""
    h = _header()
    frames = [_frame(h, seed=i) for i in range(3)]
    path = tmp_path / "clip.fcr"
    w = FcrWriter(str(path))
    w.write_header(h)
    for i, m in enumerate(frames):
        w.append_frame(m, i, i * 41_666_667, 20833333, 400, 0.5)
    w.finalize()

    r = FcrReader(str(path))
    assert r.frame_count == 3
    assert r.audio_count == 0
    for i, want in enumerate(frames):
        decoded, _ = r.read_frame(i)
        assert np.array_equal(decoded, want)


def test_v1_committed_clip_reads_with_zero_audio():
    """Backward compatibility: a version-1 vector (no audio table) must
    still load, with frame count intact and an empty audio index."""
    import pathlib

    vectors = pathlib.Path(__file__).resolve().parents[1] / "vectors"
    r = FcrReader(str(vectors / "clip_2frame.fcr"))
    assert r.header.bit_depth == 14
    assert r.frame_count == 2
    assert r.audio_count == 0
