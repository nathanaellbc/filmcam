"""Compression ratio measurement.

Answers the question spec 5.4 leaves open: does the MED + Rice pipeline
reach 2.2-2.6:1 on real iPhone 15 Bayer data? Run against DNGs exported
from RAW Cam.
"""

from __future__ import annotations

import argparse
import glob
import sys
from dataclasses import dataclass, field

import numpy as np

from .bayer import PLANE_ORDER, split_planes
from .constants import BIT_DEPTH
from .framecodec import estimate_frame_bits
from .predictor import forward
from .rice import plane_bit_length


@dataclass
class FrameStats:
    pixels: int
    raw_bits: int
    coded_bits: int
    ratio: float
    per_plane_ratio: dict[str, float] = field(default_factory=dict)


def analyze_frame(mosaic: np.ndarray, pattern: str, strips: int = 1) -> FrameStats:
    pixels = int(mosaic.size)
    raw_bits = pixels * BIT_DEPTH
    coded_bits = estimate_frame_bits(mosaic, pattern, strips)

    per_plane: dict[str, float] = {}
    for name, plane in split_planes(mosaic, pattern).items():
        plane_raw = int(plane.size) * BIT_DEPTH
        plane_coded = plane_bit_length(forward(plane))
        per_plane[name] = plane_raw / plane_coded if plane_coded else float("inf")

    return FrameStats(
        pixels=pixels,
        raw_bits=raw_bits,
        coded_bits=coded_bits,
        ratio=raw_bits / coded_bits if coded_bits else float("inf"),
        per_plane_ratio={k: per_plane[k] for k in PLANE_ORDER},
    )


def load_raw16(path: str, height: int, width: int) -> np.ndarray:
    data = np.fromfile(path, dtype="<u2")
    if data.size != height * width:
        raise ValueError(
            f"{path}: expected {height * width} samples, got {data.size}"
        )
    return data.reshape(height, width).astype(np.uint16)


def load_dng(path: str) -> tuple[np.ndarray, str]:
    try:
        import rawpy
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            'reading DNG requires the "dng" extra: pip install -e ".[dng]"'
        ) from exc

    with rawpy.imread(path) as raw:
        mosaic = np.ascontiguousarray(raw.raw_image_visible).astype(np.uint16)
        colors = "RGBG"
        pattern = "".join(
            colors[raw.raw_pattern[r, c]] for r in range(2) for c in range(2)
        )
    return mosaic, pattern


def _report(paths: list[str], loader, pattern_override: str | None) -> int:
    total_raw = 0
    total_coded = 0
    for path in paths:
        loaded = loader(path)
        mosaic, pattern = loaded if isinstance(loaded, tuple) else (loaded, None)
        pattern = pattern_override or pattern or "RGGB"
        stats = analyze_frame(mosaic, pattern)
        total_raw += stats.raw_bits
        total_coded += stats.coded_bits
        planes = "  ".join(
            f"{n}:{stats.per_plane_ratio[n]:.2f}" for n in PLANE_ORDER
        )
        print(
            f"{path}\n"
            f"  {mosaic.shape[1]}x{mosaic.shape[0]}  {pattern}  "
            f"ratio {stats.ratio:.3f}:1   [{planes}]"
        )

    if not total_coded:
        print("no frames analysed", file=sys.stderr)
        return 1

    ratio = total_raw / total_coded
    mb_per_s_24fps = (total_coded / len(paths)) / 8 / 1e6 * 24
    print("\n" + "=" * 60)
    print(f"frames analysed        {len(paths)}")
    print(f"aggregate ratio        {ratio:.3f}:1")
    print(f"implied rate @24fps    {mb_per_s_24fps:.1f} MB/s")
    print(f"spec target            2.2-2.6:1")
    if ratio < 2.0:
        print("\nVERDICT: BELOW 2.0:1 — spec 2.1 primary mode does not fit.")
        print("The 12 MP open gate mode must be revisited.")
    else:
        print("\nVERDICT: meets the floor the design depends on.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure .fcr compression ratio")
    parser.add_argument("--input", required=True, help="file glob (DNG or raw16)")
    parser.add_argument("--pattern", default=None, help="override CFA pattern")
    parser.add_argument(
        "--raw16",
        default=None,
        metavar="HxW",
        help="treat inputs as headerless little-endian uint16 of this size",
    )
    args = parser.parse_args(argv)

    paths = sorted(glob.glob(args.input))
    if not paths:
        print(f"no files matched {args.input!r}", file=sys.stderr)
        return 1

    if args.raw16:
        height, width = (int(v) for v in args.raw16.lower().split("x"))
        loader = lambda p: load_raw16(p, height, width)  # noqa: E731
    else:
        loader = load_dng

    return _report(paths, loader, args.pattern)


if __name__ == "__main__":
    raise SystemExit(main())
