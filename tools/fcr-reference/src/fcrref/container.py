"""The .fcr container: append-only, crash-resilient by construction.

Layout (spec 5.3):
    Header      4096 bytes, fixed
    Frame       "FRM0" + fields + CRC32 + payload, repeated
    Index       appended at finalize
    Trailer     "FCRX" + u64 index offset, last 12 bytes
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

import numpy as np

from .constants import (
    FRAME_MAGIC,
    HEADER_MAGIC,
    HEADER_SIZE,
    TRAILER_MAGIC,
)
from .framecodec import decode_frame, encode_frame

_HDR_FIXED = "<4sHIIB16s2I4H4I9f9f3f16sff9fQ?16sQ32s"

# Frame-record layout. Public (no leading underscore): Task 9's repair.py
# imports these names from this module as a documented cross-module contract.
FRAME_RECORD_FMT = "<4sIQIHfII"
FRAME_RECORD_SIZE = struct.calcsize(FRAME_RECORD_FMT)


def _fixed_str(value: str, size: int) -> bytes:
    raw = value.encode("utf-8")
    if len(raw) > size:
        raise ValueError(f"{value!r} exceeds {size} bytes")
    return raw.ljust(size, b"\0")


def _read_str(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("utf-8")


@dataclass(frozen=True)
class ClipHeader:
    width: int
    height: int
    bit_depth: int
    cfa_pattern: str
    frame_rate_num: int
    frame_rate_den: int
    black_level: tuple[int, int, int, int]
    white_level: tuple[int, int, int, int]
    color_matrix1: tuple[float, ...]
    color_matrix2: tuple[float, ...]
    as_shot_neutral: tuple[float, float, float]
    lens_id: str
    focal_length_35: float
    aperture: float
    intrinsic_matrix: tuple[float, ...]
    readout_time_ns: int
    ois_enabled: bool
    start_timecode: str
    created_at_ns: int
    device_model: str


@dataclass(frozen=True)
class FrameMeta:
    sequence: int
    pts_ns: int
    exposure_ns: int
    iso: int
    lens_position: float


def pack_header(h: ClipHeader) -> bytes:
    body = struct.pack(
        _HDR_FIXED,
        HEADER_MAGIC,
        1,                              # version
        h.width,
        h.height,
        h.bit_depth,
        _fixed_str(h.cfa_pattern, 16),
        h.frame_rate_num,
        h.frame_rate_den,
        *h.black_level,
        *h.white_level,
        *h.color_matrix1,
        *h.color_matrix2,
        *h.as_shot_neutral,
        _fixed_str(h.lens_id, 16),
        h.focal_length_35,
        h.aperture,
        *h.intrinsic_matrix,
        h.readout_time_ns,
        h.ois_enabled,
        _fixed_str(h.start_timecode, 16),
        h.created_at_ns,
        _fixed_str(h.device_model, 32),
    )
    if len(body) > HEADER_SIZE:
        raise ValueError("header body exceeds 4096 bytes")
    return body.ljust(HEADER_SIZE, b"\0")


def unpack_header(data: bytes) -> ClipHeader:
    if len(data) < HEADER_SIZE:
        raise ValueError("header truncated")
    fields = struct.unpack_from(_HDR_FIXED, data, 0)
    if fields[0] != HEADER_MAGIC:
        raise ValueError(f"bad header magic {fields[0]!r}")
    i = 2  # skip magic, version
    width, height, bit_depth = fields[i], fields[i + 1], fields[i + 2]
    cfa = _read_str(fields[i + 3])
    fr_num, fr_den = fields[i + 4], fields[i + 5]
    black = tuple(fields[i + 6:i + 10])
    white = tuple(fields[i + 10:i + 14])
    cm1 = tuple(fields[i + 14:i + 23])
    cm2 = tuple(fields[i + 23:i + 32])
    neutral = tuple(fields[i + 32:i + 35])
    lens_id = _read_str(fields[i + 35])
    focal, aperture = fields[i + 36], fields[i + 37]
    intrinsics = tuple(fields[i + 38:i + 47])
    readout, ois = fields[i + 47], fields[i + 48]
    timecode = _read_str(fields[i + 49])
    created = fields[i + 50]
    model = _read_str(fields[i + 51])
    return ClipHeader(
        width=width, height=height, bit_depth=bit_depth, cfa_pattern=cfa,
        frame_rate_num=fr_num, frame_rate_den=fr_den,
        black_level=black, white_level=white,
        color_matrix1=cm1, color_matrix2=cm2, as_shot_neutral=neutral,
        lens_id=lens_id, focal_length_35=focal, aperture=aperture,
        intrinsic_matrix=intrinsics, readout_time_ns=readout,
        ois_enabled=bool(ois), start_timecode=timecode,
        created_at_ns=created, device_model=model,
    )


def pack_frame(payload: bytes, meta: FrameMeta) -> bytes:
    return struct.pack(
        FRAME_RECORD_FMT,
        FRAME_MAGIC,
        meta.sequence,
        meta.pts_ns,
        meta.exposure_ns,
        meta.iso,
        meta.lens_position,
        len(payload),
        zlib.crc32(payload) & 0xFFFFFFFF,
    ) + payload


class FcrWriter:
    def __init__(self, path: str) -> None:
        self._file = open(path, "wb")
        self._header: ClipHeader | None = None
        self._index: list[tuple[int, int]] = []

    def write_header(self, header: ClipHeader) -> None:
        self._header = header
        self._file.write(pack_header(header))

    def append_frame(self, mosaic: np.ndarray, sequence: int, pts_ns: int,
                     exposure_ns: int, iso: int, lens_position: float,
                     strips: int = 1) -> None:
        if self._header is None:
            raise RuntimeError("write_header must be called first")
        payload = encode_frame(mosaic, self._header.cfa_pattern, strips)
        meta = FrameMeta(sequence, pts_ns, exposure_ns, iso, lens_position)
        record = pack_frame(payload, meta)
        offset = self._file.tell()
        self._file.write(record)
        self._index.append((offset, len(record)))

    def finalize(self) -> None:
        index_offset = self._file.tell()
        self._file.write(struct.pack("<I", len(self._index)))
        for offset, size in self._index:
            self._file.write(struct.pack("<QI", offset, size))
        self._file.write(TRAILER_MAGIC)
        self._file.write(struct.pack("<Q", index_offset))
        self._file.close()


class FcrReader:
    def __init__(self, path: str) -> None:
        self._path = path
        with open(path, "rb") as fh:
            self._data = fh.read()
        self.header = unpack_header(self._data)
        self._index = self._load_index()

    def _load_index(self) -> list[tuple[int, int]]:
        tail = self._data[-12:]
        if len(tail) < 12 or tail[:4] != TRAILER_MAGIC:
            raise ValueError("missing trailer; use repair.scan_frames")
        index_offset = struct.unpack("<Q", tail[4:])[0]
        count = struct.unpack_from("<I", self._data, index_offset)[0]
        entries = []
        pos = index_offset + 4
        for _ in range(count):
            offset, size = struct.unpack_from("<QI", self._data, pos)
            entries.append((offset, size))
            pos += 12
        return entries

    @property
    def frame_count(self) -> int:
        return len(self._index)

    def read_frame(self, index: int) -> tuple[np.ndarray, FrameMeta]:
        offset, _size = self._index[index]
        (magic, sequence, pts_ns, exposure_ns, iso, lens_position,
         payload_bytes, crc) = struct.unpack_from(FRAME_RECORD_FMT, self._data, offset)
        if magic != FRAME_MAGIC:
            raise ValueError(f"bad frame magic at offset {offset}")
        start = offset + FRAME_RECORD_SIZE
        payload = self._data[start:start + payload_bytes]
        if (zlib.crc32(payload) & 0xFFFFFFFF) != crc:
            raise ValueError(f"CRC mismatch on frame {index}")
        mosaic = decode_frame(
            payload, self.header.height, self.header.width, self.header.cfa_pattern
        )
        meta = FrameMeta(sequence, pts_ns, exposure_ns, iso, lens_position)
        return mosaic, meta
