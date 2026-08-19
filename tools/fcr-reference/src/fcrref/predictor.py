"""MED (median edge detector) predictor, as used by JPEG-LS / LOCO-I.

Edge rules (normative):
    (0, 0)        -> predict 0
    row 0, c > 0  -> predict left
    col 0, r > 0  -> predict above
    otherwise     -> MED(left, above, above-left)

MED:
    if c >= max(a, b):  pred = min(a, b)
    elif c <= min(a, b): pred = max(a, b)
    else:                pred = a + b - c
"""

from __future__ import annotations

import numpy as np


def _med(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> np.ndarray:
    lo = np.minimum(a, b)
    hi = np.maximum(a, b)
    pred = a + b - c
    pred = np.where(c >= hi, lo, pred)
    pred = np.where(c <= lo, hi, pred)
    return pred


def forward(plane: np.ndarray) -> np.ndarray:
    """Return signed int32 residuals (actual - predicted)."""
    if plane.ndim != 2:
        raise ValueError("plane must be 2-D")
    src = plane.astype(np.int32, copy=False)
    pred = np.zeros_like(src)

    # Row 0, columns 1..: predict from the left.
    if src.shape[1] > 1:
        pred[0, 1:] = src[0, :-1]

    if src.shape[0] > 1:
        # Column 0, rows 1..: predict from above.
        pred[1:, 0] = src[:-1, 0]
        # Interior: MED.
        if src.shape[1] > 1:
            a = src[1:, :-1]    # left
            b = src[:-1, 1:]    # above
            c = src[:-1, :-1]   # above-left
            pred[1:, 1:] = _med(a, b, c)

    return src - pred


def inverse(residuals: np.ndarray) -> np.ndarray:
    """Reconstruct the plane from signed residuals."""
    if residuals.ndim != 2:
        raise ValueError("residuals must be 2-D")
    res = residuals.astype(np.int32, copy=False)
    height, width = res.shape
    out = np.zeros((height, width), dtype=np.int32)

    # Row 0 is a running sum of residuals (each predicts from the left).
    out[0] = np.cumsum(res[0], dtype=np.int32)

    for r in range(1, height):
        out[r, 0] = out[r - 1, 0] + res[r, 0]
        for c in range(1, width):
            a = out[r, c - 1]
            b = out[r - 1, c]
            cc = out[r - 1, c - 1]
            lo = a if a < b else b
            hi = a if a > b else b
            if cc >= hi:
                pred = lo
            elif cc <= lo:
                pred = hi
            else:
                pred = a + b - cc
            out[r, c] = pred + res[r, c]

    return out.astype(np.uint16)
