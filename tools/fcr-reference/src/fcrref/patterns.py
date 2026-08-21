"""Deterministic synthetic Bayer test patterns.

These are the inputs Stage M1's FileBackedSource replays, and the
material scopes.py computes ground truth from. Every function must
return byte-identical output for the same arguments, on any machine.

Each generator takes a `bit_depth` defaulting to `BIT_DEPTH` (14). The
default reproduces the pre-parameter output byte-for-byte; a shallower
depth simply lowers the ceiling every level scales to.
"""

from __future__ import annotations

import numpy as np

from .constants import BIT_DEPTH, max_value_for

# 75% colour bar values, scaled to full scale, in the classic order.
_BAR_LEVELS = (
    (0.75, 0.75, 0.75),  # grey
    (0.75, 0.75, 0.00),  # yellow
    (0.00, 0.75, 0.75),  # cyan
    (0.00, 0.75, 0.00),  # green
    (0.75, 0.00, 0.75),  # magenta
    (0.75, 0.00, 0.00),  # red
    (0.00, 0.00, 0.75),  # blue
    (0.00, 0.00, 0.00),  # black
)


def horizontal_ramp(
    height: int, width: int, bit_depth: int = BIT_DEPTH
) -> np.ndarray:
    row = np.linspace(0, max_value_for(bit_depth), width, dtype=np.float64)
    return np.tile(np.round(row), (height, 1)).astype(np.uint16)


def vertical_ramp(
    height: int, width: int, bit_depth: int = BIT_DEPTH
) -> np.ndarray:
    column = np.linspace(0, max_value_for(bit_depth), height, dtype=np.float64)
    return np.tile(np.round(column)[:, None], (1, width)).astype(np.uint16)


def flat(
    height: int, width: int, value: int, bit_depth: int = BIT_DEPTH
) -> np.ndarray:
    max_value = max_value_for(bit_depth)
    if not 0 <= value <= max_value:
        raise ValueError(f"value must be 0..{max_value}")
    return np.full((height, width), value, dtype=np.uint16)


def colour_bars(
    height: int, width: int, pattern: str, bit_depth: int = BIT_DEPTH
) -> np.ndarray:
    """Colour bars laid directly onto the mosaic, honouring the CFA."""
    max_value = max_value_for(bit_depth)
    channel_index = {"R": 0, "G": 1, "B": 2}
    out = np.zeros((height, width), dtype=np.uint16)
    bar_width = max(1, width // len(_BAR_LEVELS))
    for x in range(width):
        bar = min(x // bar_width, len(_BAR_LEVELS) - 1)
        levels = _BAR_LEVELS[bar]
        for y in range(height):
            colour = pattern[(y % 2) * 2 + (x % 2)]
            out[y, x] = int(round(levels[channel_index[colour]] * max_value))
    return out


def shot_noise(
    height: int, width: int, seed: int, bit_depth: int = BIT_DEPTH
) -> np.ndarray:
    """A smooth scene plus Poisson shot noise — the realistic sensor case."""
    max_value = max_value_for(bit_depth)
    y, x = np.mgrid[0:height, 0:width]
    signal = 2000.0 + 1500.0 * np.sin(x / 60.0) * np.cos(y / 80.0)
    signal = np.clip(signal, 1.0, None)
    rng = np.random.default_rng(seed)
    return rng.poisson(signal).clip(0, max_value).astype(np.uint16)


def zone_plate(
    height: int, width: int, bit_depth: int = BIT_DEPTH
) -> np.ndarray:
    """Radial frequency sweep — stresses demosaic and scaling."""
    y, x = np.mgrid[0:height, 0:width]
    cy, cx = height / 2.0, width / 2.0
    r2 = (x - cx) ** 2 + (y - cy) ** 2
    wave = np.sin(r2 / max(width, height))
    return np.round((wave * 0.5 + 0.5) * max_value_for(bit_depth)).astype(np.uint16)


def motion_sequence(
    height: int, width: int, frames: int, seed: int,
    bit_depth: int = BIT_DEPTH,
) -> list[np.ndarray]:
    """A pattern translated by a deterministic pseudo-random walk.

    Used to exercise frame pacing and, later, stabilization.
    """
    base = zone_plate(height, width, bit_depth=bit_depth)
    rng = np.random.default_rng(seed)
    out: list[np.ndarray] = []
    dy = dx = 0

    def step() -> int:
        # Magnitude is never zero, so consecutive frames always differ.
        magnitude = int(rng.integers(1, 4))
        return magnitude if rng.integers(0, 2) else -magnitude

    for _ in range(frames):
        dy += step()
        dx += step()
        # Roll by even offsets so the CFA phase is preserved.
        out.append(np.roll(base, (dy * 2, dx * 2), axis=(0, 1)).copy())
    return out
