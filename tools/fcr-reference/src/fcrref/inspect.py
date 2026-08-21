"""Inspect and extract a .fcr clip without a full decode.

Two cheap operations that do not pay the reference decoder's per-sample
cost on every frame:

* ``--check`` validates structure: header parses, index is consistent, and
  every frame's CRC32 matches its payload. This proves the file is intact.
* ``--frame N`` decodes a single frame and writes it out as raw16, for
  spot-checking a clip against its source.

A full bit-identical decode of every frame is what the test suite does; it
is deliberately not what this tool does, because it is slow at 12 MP.
"""

from __future__ import annotations

import argparse
import struct
import sys
import zlib

import numpy as np

from .audio import AUDIO_RECORD_FMT, AUDIO_RECORD_SIZE
from .constants import AUDIO_MAGIC
from .container import (
    FRAME_MAGIC,
    FRAME_RECORD_FMT,
    FRAME_RECORD_SIZE,
    FcrReader,
)


def _check_record(data, offset, expect_magic, fmt, fixed_size, label, index):
    """Validate one record's magic, length and CRC. Returns ok."""
    fields = struct.unpack_from(fmt, data, offset)
    magic, sequence = fields[0], fields[1]
    payload_bytes, crc = fields[-2], fields[-1]
    if magic != expect_magic:
        print(f"  {label} {index}: BAD MAGIC at offset {offset}")
        return False
    start = offset + fixed_size
    payload = data[start:start + payload_bytes]
    if len(payload) != payload_bytes:
        print(f"  {label} {index}: TRUNCATED payload")
        return False
    if (zlib.crc32(payload) & 0xFFFFFFFF) != crc:
        print(f"  {label} {index}: CRC MISMATCH")
        return False
    if sequence != index:
        print(f"  {label} {index}: sequence field is {sequence}")
        return False
    return True


def check(reader: FcrReader) -> bool:
    """Validate structure and per-record CRCs without decoding any payload."""
    h = reader.header
    print(
        f"header: {h.width}x{h.height}  {h.cfa_pattern}  "
        f"{h.bit_depth}-bit  {h.frame_rate_num}/{h.frame_rate_den} fps  "
        f"v{h.version}"
    )
    print(f"frames indexed: {reader.frame_count}")

    data = reader._data  # already in memory; structural scan only
    ok = True
    for i in range(reader.frame_count):
        offset, _ = reader._index[i]
        ok &= _check_record(data, offset, FRAME_MAGIC, FRAME_RECORD_FMT,
                            FRAME_RECORD_SIZE, "frame", i)

    # Version 2 clips carry an interleaved audio stream, validated the same
    # way. Version 1 clips simply report zero audio. Audio parameters are
    # read straight from the record headers (not read_audio, which CRC-
    # checks) so a corrupt chunk is reported by the loop below rather than
    # raising here.
    print(f"audio chunks indexed: {reader.audio_count}")
    if reader.audio_count:
        first_off, _ = reader._audio_index[0]
        (_m, _s, _pts, rate, ch, fmt, _fl, _pb, _c) = struct.unpack_from(
            AUDIO_RECORD_FMT, data, first_off
        )
        print(f"  {rate} Hz, {ch} ch, format {fmt}")
        for i in range(reader.audio_count):
            offset, _ = reader._audio_index[i]
            ok &= _check_record(data, offset, AUDIO_MAGIC, AUDIO_RECORD_FMT,
                                AUDIO_RECORD_SIZE, "audio", i)

    print("structure: OK" if ok else "structure: CORRUPT")
    return ok


def dump_frame(reader: FcrReader, index: int, out_path: str) -> None:
    """Decode one frame and write it as little-endian uint16 raw16."""
    mosaic, meta = reader.read_frame(index)
    mosaic.astype("<u2").tofile(out_path)
    h = reader.header
    print(
        f"frame {index}: {h.width}x{h.height} {h.cfa_pattern} "
        f"{h.bit_depth}-bit, seq={meta.sequence} -> {out_path}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect / extract a .fcr clip")
    parser.add_argument("file", help="the .fcr clip")
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate structure and CRCs without decoding frames",
    )
    parser.add_argument(
        "--frame",
        type=int,
        default=None,
        metavar="N",
        help="decode frame N and write it to --out as raw16",
    )
    parser.add_argument("--out", default=None, help="output path for --frame")
    args = parser.parse_args(argv)

    reader = FcrReader(args.file)

    if args.frame is not None:
        if not args.out:
            print("--frame requires --out", file=sys.stderr)
            return 1
        dump_frame(reader, args.frame, args.out)
        return 0

    # Default to a structural check when no action is given.
    return 0 if check(reader) else 1


if __name__ == "__main__":
    raise SystemExit(main())
