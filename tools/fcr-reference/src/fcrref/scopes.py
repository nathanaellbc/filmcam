"""Ground-truth scope computation.

Stage M1's Metal implementations are asserted against these outputs. All
inputs are float arrays in 0..1; conversion from sensor values happens
upstream so that scope maths is independent of bit depth.
"""

from __future__ import annotations

import numpy as np

# Rec.709 luma coefficients.
_KR, _KG, _KB = 0.2126, 0.7152, 0.0722


def luma(rgb: np.ndarray) -> np.ndarray:
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError("rgb must be (H, W, 3)")
    return rgb[..., 0] * _KR + rgb[..., 1] * _KG + rgb[..., 2] * _KB


def _quantise(values: np.ndarray, bins: int) -> np.ndarray:
    clipped = np.clip(values, 0.0, 1.0)
    return np.minimum((clipped * bins).astype(np.int64), bins - 1)


def histogram(image: np.ndarray, bins: int = 256) -> np.ndarray:
    indices = _quantise(np.asarray(image, dtype=np.float64), bins)
    return np.bincount(indices.ravel(), minlength=bins).astype(np.int64)


def waveform(luma_image: np.ndarray, bins: int = 256) -> np.ndarray:
    """Per-column luma histogram. Row 0 is black, row bins-1 is white."""
    image = np.asarray(luma_image, dtype=np.float64)
    if image.ndim != 2:
        raise ValueError("luma_image must be 2-D")
    height, width = image.shape
    indices = _quantise(image, bins)
    columns = np.tile(np.arange(width), (height, 1))
    flat = indices.ravel() * width + columns.ravel()
    counts = np.bincount(flat, minlength=bins * width)
    return counts.reshape(bins, width).astype(np.int64)


def vectorscope(rgb: np.ndarray, bins: int = 256) -> np.ndarray:
    """2-D histogram in (Cb, Cr). Neutral colours land at the centre."""
    image = np.asarray(rgb, dtype=np.float64)
    y = luma(image)
    cb = (image[..., 2] - y) / (2.0 * (1.0 - _KB))
    cr = (image[..., 0] - y) / (2.0 * (1.0 - _KR))
    # Map -0.5..0.5 onto 0..bins-1, with neutral exactly at bins // 2.
    cb_i = np.clip(np.round(cb * bins) + bins // 2, 0, bins - 1).astype(np.int64)
    cr_i = np.clip(np.round(cr * bins) + bins // 2, 0, bins - 1).astype(np.int64)
    flat = cr_i.ravel() * bins + cb_i.ravel()
    counts = np.bincount(flat, minlength=bins * bins)
    return counts.reshape(bins, bins).astype(np.int64)
