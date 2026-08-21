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

from .container import (
    FRAME_MAGIC,
    FRAME_RECORD_FMT,
    FRAME_RECORD_SIZE,
    FcrReader,
)


def check(reader: FcrReader) -> bool:
    """Validate structure and per-frame CRCs without decoding any frame."""
    h = reader.header
    print(
        f"header: {h.width}x{h.height}  {h.cfa_pattern}  "
        f"{h.bit_depth}-bit  {h.frame_rate_num}/{h.frame_rate_den} fps"
    )
    print(f"frames indexed: {reader.frame_count}")

    data = reader._data  # already in memory; structural scan only
    ok = True
    for i in range(reader.frame_count):
        offset, _ = reader._index[i]
        (magic, sequence, pts_ns, _exp, _iso, _lens,
         payload_bytes, crc) = struct.unpack_from(FRAME_RECORD_FMT, data, offset)
        if magic != FRAME_MAGIC:
            print(f"  frame {i}: BAD MAGIC at offset {offset}")
            ok = False
            continue
        start = offset + FRAME_RECORD_SIZE
        payload = data[start:start + payload_bytes]
        if len(payload) != payload_bytes:
            print(f"  frame {i}: TRUNCATED payload")
            ok = False
            continue
        if (zlib.crc32(payload) & 0xFFFFFFFF) != crc:
            print(f"  frame {i}: CRC MISMATCH")
            ok = False
            continue
        if sequence != i:
            print(f"  frame {i}: sequence field is {sequence}")
            ok = False
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
