import struct

import numpy as np
import pytest

from conftest import build_frame as _frame, build_header as _header
from fcrref.constants import HEADER_MAGIC, HEADER_SIZE, TRAILER_MAGIC
from fcrref.container import FcrReader, FcrWriter, pack_header, unpack_header


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
