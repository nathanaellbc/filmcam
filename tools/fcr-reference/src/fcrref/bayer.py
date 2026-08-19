"""Bayer mosaic <-> colour plane separation.

A CFA pattern names the colours of the 2x2 cell in reading order:
    pattern[0] = (0,0)   pattern[1] = (0,1)
    pattern[2] = (1,0)   pattern[3] = (1,1)

The two greens are distinguished by position, not colour: G1 is the green
that appears first in reading order, G2 the second.
"""

from __future__ import annotations

import numpy as np

from .constants import CFA_PATTERNS

PLANE_ORDER: tuple[str, ...] = ("R", "G1", "G2", "B")

# Quadrant offsets within the 2x2 cell, in reading order.
_QUADRANTS = ((0, 0), (0, 1), (1, 0), (1, 1))


def _plane_names(pattern: str) -> tuple[str, ...]:
    """Map a CFA pattern to the plane name at each quadrant."""
    if pattern not in CFA_PATTERNS:
        raise ValueError(f"unknown CFA pattern {pattern!r}")
    names: list[str] = []
    green_seen = 0
    for ch in pattern:
        if ch == "G":
            green_seen += 1
            names.append(f"G{green_seen}")
        else:
            names.append(ch)
    return tuple(names)


def split_planes(mosaic: np.ndarray, pattern: str) -> dict[str, np.ndarray]:
    if mosaic.ndim != 2:
        raise ValueError("mosaic must be 2-D")
    height, width = mosaic.shape
    if height % 2 or width % 2:
        raise ValueError(f"mosaic dimensions must be even, got {mosaic.shape}")
    names = _plane_names(pattern)
    planes: dict[str, np.ndarray] = {}
    for name, (dy, dx) in zip(names, _QUADRANTS):
        planes[name] = np.ascontiguousarray(mosaic[dy::2, dx::2])
    return planes


def merge_planes(planes: dict[str, np.ndarray], pattern: str) -> np.ndarray:
    names = _plane_names(pattern)
    first = planes[names[0]]
    height, width = first.shape
    mosaic = np.empty((height * 2, width * 2), dtype=first.dtype)
    for name, (dy, dx) in zip(names, _QUADRANTS):
        mosaic[dy::2, dx::2] = planes[name]
    return mosaic
