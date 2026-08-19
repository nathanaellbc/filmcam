"""Rice/Golomb coding with adaptive k per block.

Code for a zigzag value u with parameter k:
    q = u >> k
    if q < RICE_LIMIT:  q zero bits, then a 1 bit, then k bits of remainder
    else:               RICE_LIMIT zero bits, then a 1 bit, then u in RAW_BITS

Length is therefore q + 1 + k in the normal path and
RICE_LIMIT + 1 + RAW_BITS in the escape path.

k is chosen per BLOCK_SIZE-sample block by exhaustive search over 0..K_MAX
and written as a K_BITS-wide header before the block's codes.
"""

from __future__ import annotations

import numpy as np

from .bitio import BitReader, BitWriter
from .constants import BLOCK_SIZE, K_BITS, K_MAX, RAW_BITS, RICE_LIMIT

ESCAPE_LENGTH = RICE_LIMIT + 1 + RAW_BITS


def zigzag(residuals: np.ndarray) -> np.ndarray:
    """Map signed residuals to unsigned: 0,-1,1,-2,2 -> 0,1,2,3,4."""
    v = residuals.astype(np.int64, copy=False)
    return np.where(v >= 0, v * 2, -v * 2 - 1).astype(np.uint32)


def unzigzag(values: np.ndarray) -> np.ndarray:
    v = values.astype(np.int64, copy=False)
    return np.where(v % 2 == 0, v // 2, -((v + 1) // 2)).astype(np.int32)


def code_length(values: np.ndarray, k: int) -> np.ndarray:
    """Bits required to code each value with parameter k."""
    if not 0 <= k <= K_MAX:
        raise ValueError(f"k must be 0..{K_MAX}, got {k}")
    q = values.astype(np.int64, copy=False) >> k
    normal = q + 1 + k
    return np.where(q < RICE_LIMIT, normal, ESCAPE_LENGTH).astype(np.int64)


def choose_k(values: np.ndarray) -> int:
    """Exhaustive optimum k for a block. Ties resolve to the smallest k."""
    best_k = 0
    best_cost = None
    for k in range(K_MAX + 1):
        cost = int(code_length(values, k).sum())
        if best_cost is None or cost < best_cost:
            best_cost = cost
            best_k = k
    return best_k


def block_ranges(count: int) -> list[tuple[int, int]]:
    """Half-open [start, stop) ranges covering `count` samples."""
    return [(s, min(s + BLOCK_SIZE, count)) for s in range(0, count, BLOCK_SIZE)]


def plane_bit_length(residuals: np.ndarray) -> int:
    """Total bits to code a plane's residuals, including block headers.

    This is exact: it equals the bit length the encoder in framecodec
    will produce. It exists so compression ratio can be measured without
    running the encoder.
    """
    values = zigzag(residuals).ravel()
    total = 0
    for start, stop in block_ranges(values.size):
        block = values[start:stop]
        k = choose_k(block)
        total += K_BITS + int(code_length(block, k).sum())
    return total


def _write_plane(writer: BitWriter, residuals: np.ndarray) -> None:
    """Write a plane's residuals into an existing BitWriter."""
    values = zigzag(residuals).ravel()
    for start, stop in block_ranges(values.size):
        block = values[start:stop]
        k = choose_k(block)
        writer.write_bits(k, K_BITS)
        mask = (1 << k) - 1
        for u in block.tolist():
            q = u >> k
            if q < RICE_LIMIT:
                writer.write_bits(1, q + 1)      # q zeros then a 1
                if k:
                    writer.write_bits(u & mask, k)
            else:
                writer.write_bits(1, RICE_LIMIT + 1)
                writer.write_bits(u, RAW_BITS)


def _read_plane(reader: BitReader, count: int) -> np.ndarray:
    """Read `count` zigzag values from an existing BitReader."""
    out = np.empty(count, dtype=np.uint32)
    index = 0
    for start, stop in block_ranges(count):
        k = reader.read_bits(K_BITS)
        for _ in range(stop - start):
            q = reader.read_unary(RICE_LIMIT)
            if q < RICE_LIMIT:
                r = reader.read_bits(k) if k else 0
                out[index] = (q << k) | r
            else:
                out[index] = reader.read_bits(RAW_BITS)
            index += 1
    return out


def encode_plane(residuals: np.ndarray) -> bytes:
    writer = BitWriter()
    _write_plane(writer, residuals)
    return writer.flush()


def decode_plane(data: bytes, shape: tuple[int, int]) -> np.ndarray:
    height, width = shape
    reader = BitReader(data)
    values = _read_plane(reader, height * width)
    return unzigzag(values).reshape(height, width)
