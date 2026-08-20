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
    """Spec 5.3: the header begins magic, version, flags."""
    h = dataclasses.replace(_header(), flags=0xDEADBEEF)
    packed = pack_header(h)
    assert struct.unpack_from("<4sHI", packed, 0) == (HEADER_MAGIC, 1, 0xDEADBEEF)
    assert unpack_header(packed).flags == 0xDEADBEEF


def test_unpack_rejects_a_future_version():
    data = bytearray(pack_header(_header()))
    struct.pack_into("<H", data, 4, 2)
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
