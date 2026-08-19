"""Index reconstruction for .fcr files that lost their trailer.

A crash costs exactly one frame: the one in flight. Everything written
before it is recoverable by walking FRM0 markers and validating CRCs.
"""

from __future__ import annotations

import struct
import zlib

from .constants import FRAME_MAGIC, HEADER_SIZE, TRAILER_MAGIC
from .container import FRAME_RECORD_FMT, FRAME_RECORD_SIZE, unpack_header


def scan_frames(path: str) -> list[tuple[int, int]]:
    """Walk the file from the end of the header, returning (offset, size)
    for every frame whose header, payload and CRC are all intact."""
    with open(path, "rb") as fh:
        data = fh.read()

    unpack_header(data)  # raises if the header itself is unusable

    entries: list[tuple[int, int]] = []
    offset = HEADER_SIZE
    limit = len(data)

    while offset + FRAME_RECORD_SIZE <= limit:
        magic = data[offset:offset + 4]
        if magic != FRAME_MAGIC:
            break
        (_m, _seq, _pts, _exp, _iso, _lens,
         payload_bytes, crc) = struct.unpack_from(FRAME_RECORD_FMT, data, offset)
        start = offset + FRAME_RECORD_SIZE
        end = start + payload_bytes
        if end > limit:
            break  # payload truncated: this frame was in flight
        if (zlib.crc32(data[start:end]) & 0xFFFFFFFF) != crc:
            break  # partial write inside the payload
        entries.append((offset, end - offset))
        offset = end

    return entries


def repair(path: str) -> int:
    """Truncate any partial tail, append a fresh index and trailer.

    Returns the number of frames recovered.
    """
    entries = scan_frames(path)
    end_of_frames = entries[-1][0] + entries[-1][1] if entries else HEADER_SIZE

    with open(path, "r+b") as fh:
        fh.truncate(end_of_frames)
        fh.seek(end_of_frames)
        fh.write(struct.pack("<I", len(entries)))
        for offset, size in entries:
            fh.write(struct.pack("<QI", offset, size))
        fh.write(TRAILER_MAGIC)
        fh.write(struct.pack("<Q", end_of_frames))

    return len(entries)
