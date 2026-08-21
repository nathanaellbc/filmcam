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
    AUDIO_MAGIC,
    FRAME_MAGIC,
    HEADER_MAGIC,
    HEADER_SIZE,
    TRAILER_MAGIC,
)
from .audio import AudioMeta, pack_audio, unpack_audio
from .framecodec import decode_frame, encode_frame

# Wire order: magic, version, flags, width, height, bit_depth, ...
# `flags` is last in ClipHeader (it is defaulted) but third on the wire.
_HDR_FIXED = "<4sHIIIB16s2I4H4I9f9f3f16sff9fQ?16sQ32s"

# Container version. Version 2 adds the embedded-audio index (parallel
# AUD0 record table). Version 1 files — the committed video-only vectors —
# remain readable and simply have no audio records. Versions above 2 are
# rejected, so a v1 reader fails a v2 file cleanly at the version gate.
_HDR_VERSION = 2
_SUPPORTED_VERSIONS = (1, 2)

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
    flags: int = 0
    # Container version on the wire. Not a constructor argument: new writes
    # are always version 2, and readers populate this from the file so the
    # index loader knows whether a parallel audio table is present.
    version: int = _HDR_VERSION


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
        h.version,
        h.flags,
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
    if fields[1] not in _SUPPORTED_VERSIONS:
        raise ValueError(
            f"unsupported header version {fields[1]} "
            f"(supported: {max(_SUPPORTED_VERSIONS)} and earlier)"
        )
    version = fields[1]
    flags = fields[2]
    i = 3  # skip magic, version, flags
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
        created_at_ns=created, device_model=model, flags=flags,
        version=version,
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
        self._audio_index: list[tuple[int, int]] = []

    def write_header(self, header: ClipHeader) -> None:
        self._header = header
        self._file.write(pack_header(header))

    def append_frame(self, mosaic: np.ndarray, sequence: int, pts_ns: int,
                     exposure_ns: int, iso: int, lens_position: float,
                     strips: int = 1) -> None:
        if self._header is None:
            raise RuntimeError("write_header must be called first")
        payload = encode_frame(
            mosaic, self._header.cfa_pattern, strips,
            bit_depth=self._header.bit_depth,
        )
        meta = FrameMeta(sequence, pts_ns, exposure_ns, iso, lens_position)
        record = pack_frame(payload, meta)
        offset = self._file.tell()
        self._file.write(record)
        self._index.append((offset, len(record)))

    def append_audio(self, payload: bytes, pts_ns: int, sample_rate_hz: int,
                     channel_count: int, sample_format: int) -> None:
        """Append a chunk of PCM as an AUD0 record, interleaved wherever the
        caller emits it among the frame records. `pts_ns` is the host-clock
        time of the chunk's first sample, on the same clock as frame pts."""
        if self._header is None:
            raise RuntimeError("write_header must be called first")
        if self._header.version < 2:
            raise ValueError(
                f"embedded audio requires container version 2, "
                f"this clip declares version {self._header.version}"
            )
        record = pack_audio(
            payload,
            sequence=len(self._audio_index),
            pts_ns=pts_ns,
            sample_rate_hz=sample_rate_hz,
            channel_count=channel_count,
            sample_format=sample_format,
        )
        offset = self._file.tell()
        self._file.write(record)
        self._audio_index.append((offset, len(record)))

    def finalize(self) -> None:
        index_offset = self._file.tell()
        self._file.write(struct.pack("<I", len(self._index)))
        for offset, size in self._index:
            self._file.write(struct.pack("<QI", offset, size))
        # Version 2 files append the parallel audio index after the frame
        # index (the trailer's single offset still points at the start of
        # the whole region, which self-describes both counts). Version 1
        # files end at the frame table — keeping the committed v1 vectors
        # byte-identical.
        if self._header is not None and self._header.version >= 2:
            self._file.write(struct.pack("<I", len(self._audio_index)))
            for offset, size in self._audio_index:
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
        self._index, self._audio_index = self._load_index()

    def _load_index(self) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
        tail = self._data[-12:]
        if len(tail) < 12 or tail[:4] != TRAILER_MAGIC:
            raise ValueError("missing trailer; use repair.scan_frames")
        index_offset = struct.unpack("<Q", tail[4:])[0]
        count = struct.unpack_from("<I", self._data, index_offset)[0]
        frames = []
        pos = index_offset + 4
        for _ in range(count):
            offset, size = struct.unpack_from("<QI", self._data, pos)
            frames.append((offset, size))
            pos += 12
        # Version 2 files carry a parallel audio index after the frames.
        # Version 1 files end at the frame table, so they have no audio.
        audio: list[tuple[int, int]] = []
        if self.header.version >= 2:
            acount = struct.unpack_from("<I", self._data, pos)[0]
            pos += 4
            for _ in range(acount):
                offset, size = struct.unpack_from("<QI", self._data, pos)
                audio.append((offset, size))
                pos += 12
        return frames, audio

    @property
    def frame_count(self) -> int:
        return len(self._index)

    @property
    def audio_count(self) -> int:
        return len(self._audio_index)

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
            payload, self.header.height, self.header.width,
            self.header.cfa_pattern, bit_depth=self.header.bit_depth,
        )
        meta = FrameMeta(sequence, pts_ns, exposure_ns, iso, lens_position)
        return mosaic, meta

    def read_audio(self, index: int) -> tuple[AudioMeta, bytes]:
        """Return (metadata, PCM payload) for the audio chunk at `index`."""
        offset, size = self._audio_index[index]
        record = self._data[offset:offset + size]
        return unpack_audio(record)
