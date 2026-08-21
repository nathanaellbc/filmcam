"""DNG sequence -> .fcr conversion.

A development tool: it reuses the real container writer and codec to turn a
folder of DNGs into a valid `.fcr` clip, then optionally reads the clip back
and asserts every frame is bit-identical to its source.

This is a reference path, not a production one. Encoding is per-sample
Python, so a 12 MP frame takes minutes. Use it to prove the format on real
footage and to produce small known-good clips, not to convert whole takes —
that is what the Swift port is for.
"""

from __future__ import annotations

import argparse
import glob
import sys
import time

import numpy as np

from .analyze import load_dng
from .container import ClipHeader, FcrReader, FcrWriter


def build_clip_header(
    width: int,
    height: int,
    bit_depth: int,
    cfa_pattern: str,
    frame_rate_num: int,
    frame_rate_den: int,
) -> ClipHeader:
    """A valid header for a converted clip.

    Fields the DNGs do not tell us (lens identity, intrinsics, readout
    time, ...) are left at neutral defaults. They matter to a real capture,
    not to proving a converted sequence round-trips.
    """
    white = (1 << bit_depth) - 1
    return ClipHeader(
        width=width,
        height=height,
        bit_depth=bit_depth,
        cfa_pattern=cfa_pattern,
        frame_rate_num=frame_rate_num,
        frame_rate_den=frame_rate_den,
        black_level=(0, 0, 0, 0),
        white_level=(white, white, white, white),
        color_matrix1=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
        color_matrix2=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
        as_shot_neutral=(1.0, 1.0, 1.0),
        lens_id="unknown",
        focal_length_35=0.0,
        aperture=0.0,
        intrinsic_matrix=(0.0,) * 9,
        readout_time_ns=0,
        ois_enabled=False,
        start_timecode="00:00:00:00",
        created_at_ns=0,
        device_model="unknown",
    )


def convert(
    paths: list[str],
    out_path: str,
    frame_rate_num: int = 24,
    frame_rate_den: int = 1,
    strips: int = 1,
    pattern_override: str | None = None,
    verify: bool = True,
) -> int:
    """Write `paths` to `out_path` as a .fcr clip. Returns the frame count."""
    if not paths:
        print("no input files", file=sys.stderr)
        return 0

    writer: FcrWriter | None = None
    header: ClipHeader | None = None
    written = 0
    t0 = time.perf_counter()

    for sequence, path in enumerate(paths):
        mosaic, pattern, bit_depth = load_dng(path)
        pattern = pattern_override or pattern

        if header is None:
            header = build_clip_header(
                mosaic.shape[1], mosaic.shape[0], bit_depth, pattern,
                frame_rate_num, frame_rate_den,
            )
            writer = FcrWriter(out_path)
            writer.write_header(header)
            print(
                f"clip: {header.width}x{header.height} {pattern} "
                f"{bit_depth}-bit -> {out_path}"
            )
        else:
            if (mosaic.shape[1], mosaic.shape[0]) != (header.width, header.height):
                raise ValueError(
                    f"{path}: geometry {mosaic.shape[1]}x{mosaic.shape[0]} "
                    f"does not match the clip's {header.width}x{header.height}"
                )
            if pattern != header.cfa_pattern:
                raise ValueError(
                    f"{path}: CFA pattern {pattern} does not match the "
                    f"clip's {header.cfa_pattern}"
                )
            if bit_depth != header.bit_depth:
                raise ValueError(
                    f"{path}: bit depth {bit_depth} does not match the "
                    f"clip's {header.bit_depth}"
                )

        assert writer is not None
        frame_start = time.perf_counter()
        writer.append_frame(
            mosaic,
            sequence=sequence,
            pts_ns=sequence * (1_000_000_000 * frame_rate_den // frame_rate_num),
            exposure_ns=0,
            iso=0,
            lens_position=0.0,
            strips=strips,
        )
        written += 1
        elapsed = time.perf_counter() - frame_start
        print(f"  frame {sequence:3d}  {elapsed:6.1f}s  {path}", flush=True)

    assert writer is not None
    writer.finalize()
    total = time.perf_counter() - t0
    print(f"wrote {written} frames in {total:.1f}s")

    if verify and header is not None:
        print("verifying round-trip...", flush=True)
        reader = FcrReader(out_path)
        if reader.frame_count != written:
            raise AssertionError(
                f"clip holds {reader.frame_count} frames, wrote {written}"
            )
        for i, path in enumerate(paths):
            mosaic, _, _ = load_dng(path)
            decoded, meta = reader.read_frame(i)
            if meta.sequence != i:
                raise AssertionError(f"frame {i}: sequence is {meta.sequence}")
            if not np.array_equal(decoded, mosaic):
                raise AssertionError(f"frame {i} does not round-trip: {path}")
        print(f"verified: all {written} frames bit-identical")

    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert a DNG sequence to a .fcr clip (reference path)"
    )
    parser.add_argument("--input", required=True, help="DNG file glob")
    parser.add_argument("--out", required=True, help="output .fcr path")
    parser.add_argument(
        "--fps",
        default="24/1",
        help="frame rate as N/D (default 24/1)",
    )
    parser.add_argument(
        "--strips", type=int, default=1, help="encode strips per frame"
    )
    parser.add_argument(
        "--pattern", default=None, help="override the CFA pattern"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="convert at most N frames"
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="skip the bit-identical round-trip check",
    )
    args = parser.parse_args(argv)

    paths = sorted(glob.glob(args.input))
    if args.limit is not None:
        paths = paths[: args.limit]
    if not paths:
        print(f"no files matched {args.input!r}", file=sys.stderr)
        return 1

    num, _, den = args.fps.partition("/")
    written = convert(
        paths,
        args.out,
        frame_rate_num=int(num),
        frame_rate_den=int(den or 1),
        strips=args.strips,
        pattern_override=args.pattern,
        verify=not args.no_verify,
    )
    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main())
