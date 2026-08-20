"""Constants shared across the reference implementation.

Values are normative — the Swift port must use exactly these.

D1 — sample depth is variable (10/12/14-bit), but RAW_BITS is not.
    The Rice escape path writes a zigzag value in RAW_BITS bits. A 14-bit
    residual zigzags to at most 32766, which fits in 15 bits; every
    shallower depth fits with room to spare. Holding RAW_BITS fixed at 15
    costs `15 - (depth + 1)` bits only on escaped samples — roughly 24
    bytes against a 5 MB frame — and in exchange rice.py needs no depth
    awareness, every committed conformance vector stays byte-valid, and
    the Swift port has exactly one escape width to implement. The
    tradeoff is that sample depth is capped at 14-bit, which is the
    sensor's ceiling anyway. Do not make RAW_BITS depend on bit depth.
"""

BIT_DEPTH = 14                            # Default depth for callers that don't specify one.
MAX_VALUE = (1 << BIT_DEPTH) - 1          # 16383. Default max value paired with BIT_DEPTH above.


def max_value_for(bit_depth: int) -> int:
    """Return the maximum sample value representable at `bit_depth`.

    Valid for 8..14 bits inclusive — 14 is the sensor's ceiling and the
    fixed width of RAW_BITS (see D1 above) caps depth there.
    """
    if not 8 <= bit_depth <= 14:
        raise ValueError(f"bit_depth must be in 8..14, got {bit_depth}")
    return (1 << bit_depth) - 1


# Zigzag-mapped residuals span 0 .. 2 * MAX_VALUE, which needs 15 bits.
# Fixed at BIT_DEPTH + 1 (not max_value_for(depth) + 1) — see decision D1
# in the module docstring above.
RAW_BITS = BIT_DEPTH + 1                  # 15

# Rice escape threshold. A quotient >= RICE_LIMIT is escaped and the
# zigzag value is written raw in RAW_BITS bits.
RICE_LIMIT = 24

# Samples per adaptive-k block.
BLOCK_SIZE = 512

# k is stored in 4 bits per block, so it must fit in 0..15.
K_MAX = 15
K_BITS = 4

CFA_PATTERNS = ("RGGB", "BGGR", "GRBG", "GBRG")

HEADER_SIZE = 4096
HEADER_MAGIC = b"FCR1"
FRAME_MAGIC = b"FRM0"
TRAILER_MAGIC = b"FCRX"
SIDECAR_MAGIC = b"FCM1"
