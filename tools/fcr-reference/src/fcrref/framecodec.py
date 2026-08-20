"""Whole-frame encode/decode with strip-parallel layout.

Payload layout (little-endian):
    u8   plane_count        always 4
    u8   strip_count
    u16  reserved           always 0
    u32  strip_byte_length[plane_count * strip_count]   plane-major
    ...  concatenated strip bitstreams, same order
"""

from __future__ import annotations

import struct

import numpy as np

from .bayer import PLANE_ORDER, merge_planes, split_planes
from .constants import MAX_VALUE
from .predictor import forward, inverse
from .rice import decode_plane, encode_plane, plane_bit_length

_HEADER_FMT = "<BBH"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)


def _strip_bounds(height: int, strips: int) -> list[tuple[int, int]]:
    if strips < 1:
        raise ValueError("strips must be >= 1")
    if strips > height:
        raise ValueError(f"strips ({strips}) exceeds plane height ({height})")
    base, extra = divmod(height, strips)
    bounds = []
    start = 0
    for i in range(strips):
        rows = base + (1 if i < extra else 0)
        bounds.append((start, start + rows))
        start += rows
    return bounds


def _check_range(mosaic: np.ndarray) -> None:
    """Reject samples the Rice coder cannot represent.

    encode_frame would fail deep inside rice.py with a per-value message;
    estimate_frame_bits would silently succeed and report a ratio for a
    bitstream that cannot physically be produced. Both call this so the
    estimator and the encoder accept exactly the same inputs.
    """
    if mosaic.size and int(mosaic.max()) > MAX_VALUE:
        raise ValueError(
            f"sample {int(mosaic.max())} exceeds MAX_VALUE {MAX_VALUE}"
        )


def encode_frame(mosaic: np.ndarray, pattern: str, strips: int = 1) -> bytes:
    _check_range(mosaic)
    planes = split_planes(mosaic, pattern)
    plane_height = planes[PLANE_ORDER[0]].shape[0]
    bounds = _strip_bounds(plane_height, strips)

    chunks: list[bytes] = []
    for name in PLANE_ORDER:
        plane = planes[name]
        for top, bottom in bounds:
            chunks.append(encode_plane(forward(plane[top:bottom])))

    header = struct.pack(_HEADER_FMT, 4, strips, 0)
    lengths = b"".join(struct.pack("<I", len(c)) for c in chunks)
    return header + lengths + b"".join(chunks)


def decode_frame(payload: bytes, height: int, width: int, pattern: str) -> np.ndarray:
    plane_count, strips, _ = struct.unpack_from(_HEADER_FMT, payload, 0)
    if plane_count != 4:
        raise ValueError(f"expected 4 planes, got {plane_count}")

    count = plane_count * strips
    lengths = list(struct.unpack_from(f"<{count}I", payload, _HEADER_SIZE))
    offset = _HEADER_SIZE + 4 * count

    plane_height, plane_width = height // 2, width // 2
    bounds = _strip_bounds(plane_height, strips)

    planes: dict[str, np.ndarray] = {}
    index = 0
    for name in PLANE_ORDER:
        plane = np.empty((plane_height, plane_width), dtype=np.uint16)
        for top, bottom in bounds:
            size = lengths[index]
            data = payload[offset:offset + size]
            residuals = decode_plane(data, (bottom - top, plane_width))
            plane[top:bottom] = inverse(residuals)
            offset += size
            index += 1
        planes[name] = plane

    return merge_planes(planes, pattern)


def estimate_frame_bits(mosaic: np.ndarray, pattern: str, strips: int = 1) -> int:
    """Total bitstream bits, excluding the payload header. Used by analyze."""
    _check_range(mosaic)
    planes = split_planes(mosaic, pattern)
    plane_height = planes[PLANE_ORDER[0]].shape[0]
    bounds = _strip_bounds(plane_height, strips)
    total = 0
    for name in PLANE_ORDER:
        plane = planes[name]
        for top, bottom in bounds:
            total += plane_bit_length(forward(plane[top:bottom]))
    return total
