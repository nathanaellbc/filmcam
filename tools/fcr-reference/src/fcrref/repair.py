"""Index reconstruction for .fcr files that lost their trailer.

A crash costs exactly one record: the one in flight. Everything written
before it is recoverable by walking the record stream and validating each
record by its magic and CRC. The scan is record-type-aware: it recognises
both FRM0 frame records and AUD0 audio records (container version 2), and
collects their offsets into separate lists so a crashed clip recovers its
video AND its audio. Unknown or corrupt bytes halt the scan — that is how
truncation and partial writes are detected.
"""

from __future__ import annotations

import struct
import zlib

from .audio import AUDIO_RECORD_FMT, AUDIO_RECORD_SIZE
from .constants import AUDIO_MAGIC, FRAME_MAGIC, HEADER_SIZE, TRAILER_MAGIC
from .container import FRAME_RECORD_FMT, FRAME_RECORD_SIZE, unpack_header


def scan_records(path: str) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Walk the file from the end of the header, returning
    (frame_entries, audio_entries) — (offset, size) pairs for every record
    whose header, payload and CRC are all intact.

    Stops at the first record that is truncated, CRC-corrupt, or has an
    unrecognised magic, so a partial tail is never returned.
    """
    with open(path, "rb") as fh:
        data = fh.read()

    unpack_header(data)  # raises if the header itself is unusable

    frames: list[tuple[int, int]] = []
    audios: list[tuple[int, int]] = []
    offset = HEADER_SIZE
    limit = len(data)

    while offset + 4 <= limit:
        magic = data[offset:offset + 4]
        if magic == FRAME_MAGIC:
            fixed_size = FRAME_RECORD_SIZE
            if offset + fixed_size > limit:
                break
            (_m, _seq, _pts, _exp, _iso, _lens,
             payload_bytes, crc) = struct.unpack_from(FRAME_RECORD_FMT, data, offset)
        elif magic == AUDIO_MAGIC:
            fixed_size = AUDIO_RECORD_SIZE
            if offset + fixed_size > limit:
                break
            (_m, _seq, _pts, _rate, _ch, _fmt, _flags,
             payload_bytes, crc) = struct.unpack_from(AUDIO_RECORD_FMT, data, offset)
        else:
            break  # unrecognised record: end of the clean prefix

        start = offset + fixed_size
        end = start + payload_bytes
        if end > limit:
            break  # payload truncated: this record was in flight
        if (zlib.crc32(data[start:end]) & 0xFFFFFFFF) != crc:
            break  # partial or corrupt write inside the payload

        if magic == FRAME_MAGIC:
            frames.append((offset, end - offset))
        else:
            audios.append((offset, end - offset))
        offset = end

    return frames, audios


def scan_frames(path: str) -> list[tuple[int, int]]:
    """Frame offsets only — the contract existing callers rely on."""
    frames, _ = scan_records(path)
    return frames


def repair(path: str) -> int:
    """Truncate any partial tail, append a fresh index and trailer.

    Returns the number of frames recovered. The index layout matches the
    file's declared container version: version 2 carries a parallel audio
    table (rebuilt from the AUD0 records the scan found), version 1 ends at
    the frame table.
    """
    with open(path, "rb") as fh:
        version = unpack_header(fh.read()).version

    frames, audios = scan_records(path)
    last = [e for e in frames + audios]
    end_of_records = max(o + s for o, s in last) if last else HEADER_SIZE

    with open(path, "r+b") as fh:
        fh.truncate(end_of_records)
        fh.seek(end_of_records)
        fh.write(struct.pack("<I", len(frames)))
        for offset, size in frames:
            fh.write(struct.pack("<QI", offset, size))
        if version >= 2:
            fh.write(struct.pack("<I", len(audios)))
            for offset, size in audios:
                fh.write(struct.pack("<QI", offset, size))
        fh.write(TRAILER_MAGIC)
        fh.write(struct.pack("<Q", end_of_records))

    return len(frames)
