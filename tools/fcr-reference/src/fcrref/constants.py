"""Constants shared across the reference implementation.

Values are normative — the Swift port must use exactly these.
"""

BIT_DEPTH = 14
MAX_VALUE = (1 << BIT_DEPTH) - 1          # 16383

# Zigzag-mapped residuals span 0 .. 2 * MAX_VALUE, which needs 15 bits.
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
