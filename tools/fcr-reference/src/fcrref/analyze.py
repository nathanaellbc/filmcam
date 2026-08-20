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
    bit_depth: int = BIT_DEPTH
    per_plane_ratio: dict[str, float] = field(default_factory=dict)


def analyze_frame(
    mosaic: np.ndarray,
    pattern: str,
    strips: int = 1,
    bit_depth: int = BIT_DEPTH,
) -> FrameStats:
    """Ratio against the source's *real* bit depth.

    Scoring a 12-bit capture against a 14-bit baseline inflates the ratio
    by 14/12 (~17%), in the optimistic direction, against a 2.0:1
    decision threshold. The caller must pass what the file actually says.
    """
    pixels = int(mosaic.size)
    raw_bits = pixels * bit_depth
    coded_bits = estimate_frame_bits(mosaic, pattern, strips)

    per_plane: dict[str, float] = {}
    for name, plane in split_planes(mosaic, pattern).items():
        plane_raw = int(plane.size) * bit_depth
        plane_coded = plane_bit_length(forward(plane))
        per_plane[name] = plane_raw / plane_coded if plane_coded else float("inf")

    return FrameStats(
        pixels=pixels,
        raw_bits=raw_bits,
        coded_bits=coded_bits,
        ratio=raw_bits / coded_bits if coded_bits else float("inf"),
        bit_depth=bit_depth,
        per_plane_ratio={k: per_plane[k] for k in PLANE_ORDER},
    )


def load_raw16(path: str, height: int, width: int) -> np.ndarray:
    data = np.fromfile(path, dtype="<u2")
    if data.size != height * width:
        raise ValueError(
            f"{path}: expected {height * width} samples, got {data.size}"
        )
    return data.reshape(height, width).astype(np.uint16)


def _bit_depth_from_white_level(white_level) -> int:
    """Derive the sample depth from the file's white level.

    16383 -> 14, 4095 -> 12, 1023 -> 10. Falls back to BIT_DEPTH when the
    file reports something unusable rather than guessing optimistically.
    """
    try:
        value = int(np.max(white_level))
    except (TypeError, ValueError):
        return BIT_DEPTH
    if value <= 0:
        return BIT_DEPTH
    return value.bit_length()


def _color_desc(raw) -> str:
    """The file's CFA colour descriptor, e.g. b"RGBG". Not always RGBG."""
    desc = getattr(raw, "color_desc", None)
    if isinstance(desc, bytes):
        desc = desc.decode("ascii", "ignore")
    if isinstance(desc, str) and len(desc) >= 4:
        return desc
    return "RGBG"


def load_dng(path: str) -> tuple[np.ndarray, str, int]:
    """Return (mosaic, CFA pattern, bit depth), all read from the file.

    Nothing here may be assumed: iPhone ProRAW and several RAW Cam modes
    write 12-bit, and the CFA colour descriptor is not always RGBG.
    """
    try:
        import rawpy
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            'reading DNG requires the "dng" extra: pip install -e ".[dng]"'
        ) from exc

    with rawpy.imread(path) as raw:
        mosaic = np.ascontiguousarray(raw.raw_image_visible).astype(np.uint16)
        colors = _color_desc(raw)
        pattern = "".join(
            colors[raw.raw_pattern[r, c]] for r in range(2) for c in range(2)
        )
        bit_depth = _bit_depth_from_white_level(raw.white_level)
    return mosaic, pattern, bit_depth


def _report(paths: list[str], loader, pattern_override: str | None) -> int:
    total_raw = 0
    total_coded = 0
    for path in paths:
        loaded = loader(path)
        if isinstance(loaded, tuple):
            mosaic, pattern, bit_depth = loaded
        else:
            mosaic, pattern, bit_depth = loaded, None, BIT_DEPTH
        pattern = pattern_override or pattern or "RGGB"
        stats = analyze_frame(mosaic, pattern, bit_depth=bit_depth)
        total_raw += stats.raw_bits
        total_coded += stats.coded_bits
        planes = "  ".join(
            f"{n}:{stats.per_plane_ratio[n]:.2f}" for n in PLANE_ORDER
        )
        print(
            f"{path}\n"
            f"  {mosaic.shape[1]}x{mosaic.shape[0]}  {pattern}  "
            f"{stats.bit_depth}-bit  "
            f"ratio {stats.ratio:.3f}:1   [{planes}]"
        )

    if not total_coded:
        print("no frames analysed", file=sys.stderr)
        return 1

    ratio = total_raw / total_coded
    bytes_per_frame = (total_coded / len(paths)) / 8
    mb_per_s_24fps = bytes_per_frame / 1e6 * 24
    gb_per_min = mb_per_s_24fps * 60 / 1000

    print("\n" + "=" * 60)
    print(f"frames analysed        {len(paths)}")
    print(f"aggregate ratio        {ratio:.3f}:1")
    print(f"bytes per frame        {bytes_per_frame / 1e6:.2f} MB")
    print(f"sustained rate @24fps  {mb_per_s_24fps:.1f} MB/s")
    print(f"storage                {gb_per_min:.2f} GB/min")
    for label, usable_gb in (("128 GB device", 110), ("256 GB device", 230)):
        print(f"  runway, {label:14s} {usable_gb / gb_per_min:.1f} min")

    # Deliberately NOT a pass/fail verdict. Compression ratio is an output, not a
    # target: it varies with bit depth, lens and content, and a fixed ratio gate is
    # meaningless across depths (10-bit data at 1.9:1 costs fewer bytes than 14-bit
    # at 2.2:1). The device's sustained write rate has never been measured — see
    # spec 2.6 — so no mode is disqualified here. Modes are disqualified by the
    # hardware failing them, not by this tool guessing.
    print("\nNo verdict is issued: the device's sustained write ceiling is unmeasured")
    print("(spec 2.6). Compare the rate above against a measured ceiling, not an")
    print("assumed one. For reference, RAW Cam's published ~12 GB/min is ~200 MB/s.")
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
    parser.add_argument(
        "--bit-depth",
        type=int,
        default=BIT_DEPTH,
        help=f"sample bit depth for --raw16 inputs (default {BIT_DEPTH}); "
             "DNG inputs read their own depth",
    )
    args = parser.parse_args(argv)

    paths = sorted(glob.glob(args.input))
    if not paths:
        print(f"no files matched {args.input!r}", file=sys.stderr)
        return 1

    if args.raw16:
        height, width = (int(v) for v in args.raw16.lower().split("x"))
        depth = args.bit_depth
        loader = lambda p: (  # noqa: E731
            load_raw16(p, height, width), None, depth
        )
    else:
        loader = load_dng

    return _report(paths, loader, args.pattern)


if __name__ == "__main__":
    raise SystemExit(main())
