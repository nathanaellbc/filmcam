# Stage W — `.fcr` Container & Rice Codec Reference Implementation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a platform-agnostic Python reference implementation of the `.fcr` container and its lossless Rice codec, measure the real compression ratio on iPhone 15 Bayer data, and freeze conformance vectors that the later Swift port must match byte-for-byte.

**Architecture:** A pure-Python + numpy package (`fcrref`) with no Apple dependencies. The codec is decomposed into independently testable layers — bit I/O, CFA plane separation, MED prediction, Rice code-length calculation, Rice bitstream — so each has its own test cycle. Code-length calculation is deliberately separated from bitstream encoding, because the compression-ratio question (spec §5.4) can be answered from lengths alone, without a working encoder. Test patterns and scope ground truth are generated here so that Stage M1's Swift tests have assertions that exist before the Swift does.

**Tech Stack:** Python 3.11+, numpy, pytest, pytest-benchmark (optional), rawpy (optional, for reading DNG).

**Spec:** `docs/superpowers/specs/2026-08-19-filmcam-capture-design.md`

## Global Constraints

Copied verbatim from the spec. Every task's requirements implicitly include this section.

- **Bit depth: 14-bit throughout**, stored packed at 7 bytes per 4 pixels (1.75 B/px). (spec §2.3)
- **Sample value range: 0–16383.** Prediction residuals: −16383…16383. Zigzag-mapped: 0…32766, requiring `RAW_BITS = 15`.
- **CFA patterns supported:** `RGGB`, `BGGR`, `GRBG`, `GBRG` — the four iOS `kCVPixelFormatType_14Bayer_*` formats. (spec §2.3)
- **Primary frame geometry: 4032 × 3024** (12 MP binned open gate). Fallback geometry: 4K crop. (spec §2.1)
- **Frame rate: 24 fps** primary; 18 fps is the documented degradation fallback. (spec §5.4)
- **Target compression ratio: 2.2–2.6:1.** Below ~2.0:1 invalidates the 12 MP primary mode. (spec §5.4)
- **Predictor: MED / LOCO-I** (JPEG-LS), applied per CFA plane, not across the Bayer mosaic. (spec §5.4)
- **Entropy coder: Rice/Golomb, adaptive `k` per 512-sample block.** (spec §5.4)
- **Strip-parallel payload layout** with per-strip offsets in the payload header. (spec §5.4)
- **Container is append-only** with per-frame `FRM0` markers and CRC32, index appended at finalize, trailer `FCRX`. (spec §5.3)
- **All multi-byte integers are little-endian.** All bitstream bit-packing is **MSB-first**.
- **Header is exactly 4096 bytes, fixed.** (spec §5.3)
- **Determinism is mandatory:** every generated artifact must be byte-identical across runs and machines. Seed all RNG explicitly. No timestamps, no dict-ordering dependence, no `hash()`.
- **Motion sidecar `.fcm` is a separate append-only file**, with explicit gap markers, never interpolated. (spec §5.5)

---

## File Structure

All Stage W work lives in `tools/fcr-reference/`. It is a development tool, not shipped app code.

| File | Responsibility |
|---|---|
| `tools/fcr-reference/pyproject.toml` | Package metadata, pytest config |
| `tools/fcr-reference/README.md` | How to run the analyzer and regenerate vectors |
| `src/fcrref/constants.py` | Shared constants: bit depth, `LIMIT`, `RAW_BITS`, block size, magics |
| `src/fcrref/bitio.py` | `BitWriter` / `BitReader`, MSB-first |
| `src/fcrref/bayer.py` | CFA mosaic ↔ four colour planes |
| `src/fcrref/predictor.py` | MED / LOCO-I forward and inverse |
| `src/fcrref/rice.py` | Zigzag, `k` selection, code lengths, encode, decode |
| `src/fcrref/framecodec.py` | Whole-frame encode/decode, strip layout |
| `src/fcrref/container.py` | `.fcr` header, frame records, index, trailer, repair scan |
| `src/fcrref/sidecar.py` | `.fcm` motion sidecar |
| `src/fcrref/patterns.py` | Deterministic synthetic test patterns (W3) |
| `src/fcrref/scopes.py` | Ground-truth histogram / waveform / vectorscope (W5) |
| `src/fcrref/looks.py` | `.cube` LUT read/write, Rec.709 + Cineon, false-colour IRE table (W4) |
| `src/fcrref/analyze.py` | Compression-ratio measurement CLI (W2) |
| `src/fcrref/vectors.py` | Conformance vector generation + manifest (W6) |
| `tests/…` | One test module per source module |
| `vectors/` | Frozen conformance vectors + `manifest.json` |

---

## Task 1: Project scaffold and bit I/O

**Files:**
- Create: `tools/fcr-reference/pyproject.toml`
- Create: `tools/fcr-reference/README.md`
- Create: `tools/fcr-reference/src/fcrref/__init__.py`
- Create: `tools/fcr-reference/src/fcrref/constants.py`
- Create: `tools/fcr-reference/src/fcrref/bitio.py`
- Test: `tools/fcr-reference/tests/test_bitio.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `constants.BIT_DEPTH: int = 14`, `MAX_VALUE: int = 16383`, `RAW_BITS: int = 15`, `RICE_LIMIT: int = 24`, `BLOCK_SIZE: int = 512`, `K_MAX: int = 15`
  - `BitWriter()` with `write_bits(value: int, count: int) -> None`, `bit_length() -> int`, `flush() -> bytes`
  - `BitReader(data: bytes)` with `read_bits(count: int) -> int`, `read_unary(limit: int) -> int`

- [ ] **Step 1: Create the package scaffold**

`tools/fcr-reference/pyproject.toml`:

```toml
[project]
name = "fcrref"
version = "0.1.0"
description = "Reference implementation of the .fcr container and Rice codec"
requires-python = ">=3.11"
dependencies = ["numpy>=1.26"]

[project.optional-dependencies]
dng = ["rawpy>=0.19"]
dev = ["pytest>=8.0"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"
```

`tools/fcr-reference/src/fcrref/__init__.py`:

```python
"""Reference implementation of the FilmCam .fcr container and Rice codec.

This package is the normative definition of the on-disk format. The Swift
implementation in Stage M1 must produce byte-identical output for the
conformance vectors in ../vectors/.
"""

__version__ = "0.1.0"
```

`tools/fcr-reference/README.md`:

```markdown
# fcr-reference

Reference implementation of the FilmCam `.fcr` container and its lossless
Rice codec. Platform-agnostic; no Apple dependencies.

## Install

    cd tools/fcr-reference
    python -m pip install -e ".[dev,dng]"

## Measure compression ratio on real footage

    python -m fcrref.analyze --input path/to/clip/*.dng

## Regenerate conformance vectors

    python -m fcrref.vectors --out vectors/

Regeneration must be byte-identical. If it is not, that is a bug.
```

- [ ] **Step 2: Write the failing test**

`tools/fcr-reference/tests/test_bitio.py`:

```python
import random

import pytest

from fcrref.bitio import BitReader, BitWriter


def test_write_then_read_single_value():
    w = BitWriter()
    w.write_bits(0b101, 3)
    data = w.flush()
    r = BitReader(data)
    assert r.read_bits(3) == 0b101


def test_msb_first_byte_layout():
    """Bits pack MSB-first: 0b101 in 3 bits then 0b11111 in 5 bits == 0xBF."""
    w = BitWriter()
    w.write_bits(0b101, 3)
    w.write_bits(0b11111, 5)
    assert w.flush() == bytes([0b10111111])


def test_flush_pads_with_zeros():
    w = BitWriter()
    w.write_bits(1, 1)
    assert w.flush() == bytes([0b10000000])


def test_bit_length_tracks_written_bits():
    w = BitWriter()
    w.write_bits(0, 5)
    w.write_bits(0, 7)
    assert w.bit_length() == 12


def test_roundtrip_random_sequence():
    rng = random.Random(20260819)
    values = []
    w = BitWriter()
    for _ in range(2000):
        count = rng.randint(1, 24)
        value = rng.randrange(0, 1 << count)
        values.append((value, count))
        w.write_bits(value, count)
    r = BitReader(w.flush())
    for value, count in values:
        assert r.read_bits(count) == value


def test_read_unary_counts_zeros_before_one():
    w = BitWriter()
    w.write_bits(1, 6)  # five zeros then a one
    r = BitReader(w.flush())
    assert r.read_unary(24) == 5


def test_read_unary_stops_at_limit():
    w = BitWriter()
    w.write_bits(0, 24)
    w.write_bits(0xFF, 8)
    r = BitReader(w.flush())
    assert r.read_unary(24) == 24


def test_write_bits_rejects_out_of_range_value():
    w = BitWriter()
    with pytest.raises(ValueError):
        w.write_bits(4, 2)


def test_read_past_end_raises():
    r = BitReader(bytes([0xFF]))
    r.read_bits(8)
    with pytest.raises(EOFError):
        r.read_bits(1)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd tools/fcr-reference && python -m pytest tests/test_bitio.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fcrref.bitio'`

- [ ] **Step 4: Write `constants.py`**

`tools/fcr-reference/src/fcrref/constants.py`:

```python
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
```

- [ ] **Step 5: Write `bitio.py`**

`tools/fcr-reference/src/fcrref/bitio.py`:

```python
"""MSB-first bit packing.

Bits are written most-significant-first within each byte. The final byte
is zero-padded. This ordering is normative.
"""

from __future__ import annotations


class BitWriter:
    """Accumulates bits MSB-first into a byte buffer."""

    def __init__(self) -> None:
        self._bytes = bytearray()
        self._acc = 0
        self._nbits = 0
        self._total = 0

    def write_bits(self, value: int, count: int) -> None:
        if count < 0 or count > 32:
            raise ValueError(f"count must be 0..32, got {count}")
        if count == 0:
            return
        if value < 0 or value >= (1 << count):
            raise ValueError(f"value {value} does not fit in {count} bits")
        self._acc = (self._acc << count) | value
        self._nbits += count
        self._total += count
        while self._nbits >= 8:
            self._nbits -= 8
            self._bytes.append((self._acc >> self._nbits) & 0xFF)
        self._acc &= (1 << self._nbits) - 1

    def bit_length(self) -> int:
        """Total bits written so far, excluding flush padding."""
        return self._total

    def flush(self) -> bytes:
        """Zero-pad to a byte boundary and return the buffer."""
        if self._nbits:
            self._bytes.append((self._acc << (8 - self._nbits)) & 0xFF)
            self._acc = 0
            self._nbits = 0
        return bytes(self._bytes)


class BitReader:
    """Reads bits MSB-first from a byte buffer."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0  # bit position

    def read_bits(self, count: int) -> int:
        if count < 0 or count > 32:
            raise ValueError(f"count must be 0..32, got {count}")
        if count == 0:
            return 0
        if self._pos + count > len(self._data) * 8:
            raise EOFError("read past end of bitstream")
        value = 0
        remaining = count
        while remaining:
            byte_index = self._pos >> 3
            bit_offset = self._pos & 7
            available = 8 - bit_offset
            take = min(available, remaining)
            byte = self._data[byte_index]
            shift = available - take
            mask = (1 << take) - 1
            value = (value << take) | ((byte >> shift) & mask)
            self._pos += take
            remaining -= take
        return value

    def read_unary(self, limit: int) -> int:
        """Count zeros until a 1 bit. Returns `limit` if that many zeros
        are seen, consuming exactly `limit` bits and no terminator."""
        count = 0
        while count < limit:
            if self.read_bits(1):
                return count
            count += 1
        return limit

    def bit_position(self) -> int:
        return self._pos
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd tools/fcr-reference && python -m pip install -e ".[dev]" && python -m pytest tests/test_bitio.py -v`
Expected: PASS — 9 passed

- [ ] **Step 7: Commit**

```bash
git add tools/fcr-reference/
git commit -m "feat(fcrref): add package scaffold and MSB-first bit I/O"
```

---

## Task 2: CFA plane separation

**Files:**
- Create: `tools/fcr-reference/src/fcrref/bayer.py`
- Test: `tools/fcr-reference/tests/test_bayer.py`

**Interfaces:**
- Consumes: `constants.CFA_PATTERNS`
- Produces:
  - `split_planes(mosaic: np.ndarray, pattern: str) -> dict[str, np.ndarray]` — keys are always `"R"`, `"G1"`, `"G2"`, `"B"`; each plane is `(H//2, W//2)` `uint16`
  - `merge_planes(planes: dict[str, np.ndarray], pattern: str) -> np.ndarray` — inverse
  - `PLANE_ORDER: tuple[str, ...] = ("R", "G1", "G2", "B")` — normative serialisation order

The spec (§5.4) requires prediction to run per colour plane, because same-colour neighbours correlate and adjacent Bayer pixels do not. This task establishes that separation.

- [ ] **Step 1: Write the failing test**

`tools/fcr-reference/tests/test_bayer.py`:

```python
import numpy as np
import pytest

from fcrref.bayer import PLANE_ORDER, merge_planes, split_planes
from fcrref.constants import CFA_PATTERNS


def _mosaic() -> np.ndarray:
    """4x4 mosaic where every pixel holds a distinct value."""
    return np.arange(16, dtype=np.uint16).reshape(4, 4)


def test_plane_order_is_normative():
    assert PLANE_ORDER == ("R", "G1", "G2", "B")


def test_rggb_assigns_quadrants_correctly():
    m = _mosaic()
    planes = split_planes(m, "RGGB")
    # RGGB: (0,0)=R (0,1)=G1 (1,0)=G2 (1,1)=B
    assert planes["R"][0, 0] == m[0, 0]
    assert planes["G1"][0, 0] == m[0, 1]
    assert planes["G2"][0, 0] == m[1, 0]
    assert planes["B"][0, 0] == m[1, 1]


def test_bggr_assigns_quadrants_correctly():
    m = _mosaic()
    planes = split_planes(m, "BGGR")
    assert planes["B"][0, 0] == m[0, 0]
    assert planes["G1"][0, 0] == m[0, 1]
    assert planes["G2"][0, 0] == m[1, 0]
    assert planes["R"][0, 0] == m[1, 1]


def test_plane_shape_is_half_resolution():
    m = np.zeros((3024, 4032), dtype=np.uint16)
    planes = split_planes(m, "RGGB")
    for name in PLANE_ORDER:
        assert planes[name].shape == (1512, 2016)


@pytest.mark.parametrize("pattern", CFA_PATTERNS)
def test_split_merge_roundtrip(pattern):
    rng = np.random.default_rng(20260819)
    m = rng.integers(0, 16384, size=(64, 96), dtype=np.uint16)
    assert np.array_equal(merge_planes(split_planes(m, pattern), pattern), m)


def test_rejects_odd_dimensions():
    m = np.zeros((5, 4), dtype=np.uint16)
    with pytest.raises(ValueError):
        split_planes(m, "RGGB")


def test_rejects_unknown_pattern():
    m = np.zeros((4, 4), dtype=np.uint16)
    with pytest.raises(ValueError):
        split_planes(m, "XYZW")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/fcr-reference && python -m pytest tests/test_bayer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fcrref.bayer'`

- [ ] **Step 3: Write `bayer.py`**

`tools/fcr-reference/src/fcrref/bayer.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tools/fcr-reference && python -m pytest tests/test_bayer.py -v`
Expected: PASS — 9 passed

- [ ] **Step 5: Commit**

```bash
git add tools/fcr-reference/src/fcrref/bayer.py tools/fcr-reference/tests/test_bayer.py
git commit -m "feat(fcrref): add CFA mosaic to colour plane separation"
```

---

## Task 3: MED / LOCO-I predictor

**Files:**
- Create: `tools/fcr-reference/src/fcrref/predictor.py`
- Test: `tools/fcr-reference/tests/test_predictor.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `forward(plane: np.ndarray) -> np.ndarray` — signed `int32` residuals, same shape
  - `inverse(residuals: np.ndarray) -> np.ndarray` — `uint16` plane, same shape

Edge rules are normative: `(0,0)` predicts 0; row 0 predicts from the left; column 0 predicts from above; all other pixels use MED.

- [ ] **Step 1: Write the failing test**

`tools/fcr-reference/tests/test_predictor.py`:

```python
import numpy as np

from fcrref import predictor


def test_first_pixel_predicts_zero():
    plane = np.array([[100]], dtype=np.uint16)
    assert predictor.forward(plane)[0, 0] == 100


def test_first_row_predicts_from_left():
    plane = np.array([[10, 14, 14]], dtype=np.uint16)
    res = predictor.forward(plane)
    assert res[0, 1] == 4
    assert res[0, 2] == 0


def test_first_column_predicts_from_above():
    plane = np.array([[10], [13], [13]], dtype=np.uint16)
    res = predictor.forward(plane)
    assert res[1, 0] == 3
    assert res[2, 0] == 0


def test_med_takes_min_when_c_is_largest():
    # a=left=5, b=above=9, c=above-left=20 -> c >= max(a,b) -> pred = min = 5
    plane = np.array([[20, 9], [5, 7]], dtype=np.uint16)
    assert predictor.forward(plane)[1, 1] == 7 - 5


def test_med_takes_max_when_c_is_smallest():
    # a=5, b=9, c=1 -> c <= min(a,b) -> pred = max = 9
    plane = np.array([[1, 9], [5, 7]], dtype=np.uint16)
    assert predictor.forward(plane)[1, 1] == 7 - 9


def test_med_takes_gradient_otherwise():
    # a=5, b=9, c=6 -> pred = a + b - c = 8
    plane = np.array([[6, 9], [5, 7]], dtype=np.uint16)
    assert predictor.forward(plane)[1, 1] == 7 - 8


def test_flat_plane_yields_all_zero_residuals_after_first():
    plane = np.full((16, 16), 1234, dtype=np.uint16)
    res = predictor.forward(plane)
    assert res[0, 0] == 1234
    assert np.all(res.ravel()[1:] == 0)


def test_roundtrip_random_plane():
    rng = np.random.default_rng(20260819)
    plane = rng.integers(0, 16384, size=(97, 131), dtype=np.uint16)
    assert np.array_equal(predictor.inverse(predictor.forward(plane)), plane)


def test_roundtrip_extreme_values():
    plane = np.array([[0, 16383], [16383, 0]], dtype=np.uint16)
    assert np.array_equal(predictor.inverse(predictor.forward(plane)), plane)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/fcr-reference && python -m pytest tests/test_predictor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fcrref.predictor'`

- [ ] **Step 3: Write `predictor.py`**

The forward pass is fully vectorised. The inverse is row-sequential because each row depends on the reconstructed row above, but within a row the MED prediction depends on the reconstructed pixel to the left, so it is genuinely serial. Clarity is the priority here; this is a reference implementation.

`tools/fcr-reference/src/fcrref/predictor.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tools/fcr-reference && python -m pytest tests/test_predictor.py -v`
Expected: PASS — 9 passed

- [ ] **Step 5: Commit**

```bash
git add tools/fcr-reference/src/fcrref/predictor.py tools/fcr-reference/tests/test_predictor.py
git commit -m "feat(fcrref): add MED/LOCO-I predictor with vectorised forward pass"
```

---

## Task 4: Rice code lengths and adaptive `k` selection

**Files:**
- Create: `tools/fcr-reference/src/fcrref/rice.py`
- Test: `tools/fcr-reference/tests/test_rice.py`

**Interfaces:**
- Consumes: `constants.{RICE_LIMIT, RAW_BITS, BLOCK_SIZE, K_MAX, K_BITS}`
- Produces:
  - `zigzag(residuals: np.ndarray) -> np.ndarray` — `int32` → `uint32`
  - `unzigzag(values: np.ndarray) -> np.ndarray` — inverse
  - `code_length(values: np.ndarray, k: int) -> np.ndarray` — bits per sample for a given `k`
  - `choose_k(values: np.ndarray) -> int` — exhaustive optimum over `0..K_MAX`
  - `plane_bit_length(residuals: np.ndarray) -> int` — total bits including per-block `k` headers

`plane_bit_length` is the whole point of this task: it answers the compression-ratio question (spec §5.4) **without a working encoder**, so W2's measurement is not blocked on Task 5.

- [ ] **Step 1: Write the failing test**

`tools/fcr-reference/tests/test_rice.py`:

```python
import numpy as np

from fcrref import rice
from fcrref.constants import BLOCK_SIZE, K_BITS, RAW_BITS, RICE_LIMIT


def test_zigzag_maps_zero_to_zero():
    assert rice.zigzag(np.array([0], dtype=np.int32))[0] == 0


def test_zigzag_interleaves_signs():
    src = np.array([0, -1, 1, -2, 2], dtype=np.int32)
    assert list(rice.zigzag(src)) == [0, 1, 2, 3, 4]


def test_zigzag_roundtrip():
    rng = np.random.default_rng(20260819)
    src = rng.integers(-16383, 16384, size=10000, dtype=np.int32)
    assert np.array_equal(rice.unzigzag(rice.zigzag(src)), src)


def test_zigzag_max_fits_in_raw_bits():
    src = np.array([-16383, 16383], dtype=np.int32)
    assert int(rice.zigzag(src).max()) < (1 << RAW_BITS)


def test_code_length_normal_path():
    # u=5, k=2 -> q=1, length = q + 1 + k = 4
    assert rice.code_length(np.array([5], dtype=np.uint32), 2)[0] == 4


def test_code_length_zero_value():
    # u=0, k=0 -> q=0, length = 0 + 1 + 0 = 1
    assert rice.code_length(np.array([0], dtype=np.uint32), 0)[0] == 1


def test_code_length_escape_path():
    # q >= RICE_LIMIT escapes: length = RICE_LIMIT + 1 + RAW_BITS
    big = np.array([RICE_LIMIT << 3], dtype=np.uint32)
    assert rice.code_length(big, 3)[0] == RICE_LIMIT + 1 + RAW_BITS


def test_choose_k_prefers_zero_for_tiny_values():
    assert rice.choose_k(np.zeros(BLOCK_SIZE, dtype=np.uint32)) == 0


def test_choose_k_grows_with_magnitude():
    small = np.full(BLOCK_SIZE, 3, dtype=np.uint32)
    large = np.full(BLOCK_SIZE, 3000, dtype=np.uint32)
    assert rice.choose_k(large) > rice.choose_k(small)


def test_choose_k_is_the_exhaustive_optimum():
    rng = np.random.default_rng(7)
    values = rng.integers(0, 500, size=BLOCK_SIZE, dtype=np.uint32)
    best = rice.choose_k(values)
    costs = [int(rice.code_length(values, k).sum()) for k in range(16)]
    assert costs[best] == min(costs)


def test_plane_bit_length_includes_block_headers():
    residuals = np.zeros((1, BLOCK_SIZE * 2), dtype=np.int32)
    # 2 blocks, each: K_BITS header + BLOCK_SIZE codes of length 1
    expected = 2 * (K_BITS + BLOCK_SIZE)
    assert rice.plane_bit_length(residuals) == expected


def test_plane_bit_length_handles_partial_final_block():
    residuals = np.zeros((1, BLOCK_SIZE + 10), dtype=np.int32)
    expected = (K_BITS + BLOCK_SIZE) + (K_BITS + 10)
    assert rice.plane_bit_length(residuals) == expected
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/fcr-reference && python -m pytest tests/test_rice.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fcrref.rice'`

- [ ] **Step 3: Write `rice.py`**

`tools/fcr-reference/src/fcrref/rice.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tools/fcr-reference && python -m pytest tests/test_rice.py -v`
Expected: PASS — 12 passed

- [ ] **Step 5: Commit**

```bash
git add tools/fcr-reference/src/fcrref/rice.py tools/fcr-reference/tests/test_rice.py
git commit -m "feat(fcrref): add Rice code-length calculation and adaptive k selection"
```

---

## Task 5: Rice bitstream encode and decode

**Files:**
- Modify: `tools/fcr-reference/src/fcrref/rice.py` (append encode/decode)
- Test: `tools/fcr-reference/tests/test_rice_bitstream.py`

**Interfaces:**
- Consumes: `bitio.BitWriter`, `bitio.BitReader`, everything from Task 4
- Produces:
  - `encode_plane(residuals: np.ndarray) -> bytes`
  - `decode_plane(data: bytes, shape: tuple[int, int]) -> np.ndarray` — returns `int32` residuals

The critical test is that the encoder's actual bit count equals `plane_bit_length` exactly. If those diverge, the ratio measured in Task 7 is a lie.

> **Escape-path warning — this bit the first implementation.**
>
> Matching *lengths* is not the same as matching *bit consumption*. The encoder
> writes an escape marker as `write_bits(1, RICE_LIMIT + 1)` — 24 zeros **plus a
> terminating 1** — but `read_unary(RICE_LIMIT)` stops after 24 bits and does not
> consume that terminator. The decoder must consume it explicitly, or it reads the
> raw value one bit early and desynchronises everything after it.
>
> This is invisible to ordinary tests. `choose_k` picks a `k` around 14–15 for
> uniformly distributed data, so `q < RICE_LIMIT` everywhere and the escape never
> fires. The escape is only optimal for **skewed** data: many near-zero values plus
> a rare large outlier. Any test that claims to cover the escape path must assert
> `choose_k` actually returns a low `k` for its fixture — otherwise it covers
> nothing while appearing to.

- [ ] **Step 1: Write the failing test**

`tools/fcr-reference/tests/test_rice_bitstream.py`:

```python
import numpy as np
import pytest

from fcrref import rice
from fcrref.bitio import BitWriter
from fcrref.constants import BLOCK_SIZE


def test_roundtrip_zeros():
    res = np.zeros((4, BLOCK_SIZE), dtype=np.int32)
    data = rice.encode_plane(res)
    assert np.array_equal(rice.decode_plane(data, res.shape), res)


def test_roundtrip_random_small():
    rng = np.random.default_rng(20260819)
    res = rng.integers(-40, 41, size=(31, 47), dtype=np.int32)
    data = rice.encode_plane(res)
    assert np.array_equal(rice.decode_plane(data, res.shape), res)


def test_roundtrip_full_scale_values_on_the_normal_path():
    """Full-scale residuals. NOTE: this does NOT escape — choose_k picks
    k=14 here, giving q in {0,1}. Kept because large-magnitude values on the
    normal path are still worth covering. The escape test is below."""
    res = np.array([[16383, -16383, 0, 16383]], dtype=np.int32)
    data = rice.encode_plane(res)
    assert np.array_equal(rice.decode_plane(data, res.shape), res)


def test_roundtrip_forces_a_genuine_escape():
    """The escape fires only for SKEWED data: a block of near-zeros with a
    rare large outlier, where choose_k picks a low k. Uniform random data
    never escapes, because choose_k finds a k around 14-15 that caps every
    value's cost. Without this test the decoder's escape branch is entirely
    uncovered and a one-bit desync passes the whole suite."""
    res = np.zeros((1, BLOCK_SIZE), dtype=np.int32)
    res[0, 0] = 16000
    res[0, 100] = 5
    res[0, 200] = -3
    assert rice.choose_k(rice.zigzag(res).ravel()) == 0  # escape really fires
    data = rice.encode_plane(res)
    assert np.array_equal(rice.decode_plane(data, res.shape), res)


@pytest.mark.parametrize("seed", range(20))
def test_roundtrip_property(seed):
    rng = np.random.default_rng(seed)
    height = int(rng.integers(1, 40))
    width = int(rng.integers(1, 600))
    scale = int(rng.integers(1, 16384))
    res = rng.integers(-scale, scale + 1, size=(height, width), dtype=np.int32)
    data = rice.encode_plane(res)
    assert np.array_equal(rice.decode_plane(data, res.shape), res)


def test_encoded_length_matches_plane_bit_length_exactly():
    """The measurement in Task 7 depends on this identity holding."""
    rng = np.random.default_rng(99)
    res = rng.integers(-800, 801, size=(23, 1100), dtype=np.int32)
    predicted_bits = rice.plane_bit_length(res)
    w = BitWriter()
    rice._write_plane(w, res)  # internal, exercised deliberately
    assert w.bit_length() == predicted_bits


def test_output_is_deterministic():
    rng = np.random.default_rng(5)
    res = rng.integers(-100, 101, size=(9, 700), dtype=np.int32)
    assert rice.encode_plane(res) == rice.encode_plane(res)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/fcr-reference && python -m pytest tests/test_rice_bitstream.py -v`
Expected: FAIL — `AttributeError: module 'fcrref.rice' has no attribute 'encode_plane'`

- [ ] **Step 3: Append encode/decode to `rice.py`**

Add these imports at the top of `rice.py` (alongside the existing ones):

```python
from .bitio import BitReader, BitWriter
```

Append to `tools/fcr-reference/src/fcrref/rice.py`:

```python
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
                # read_unary consumed RICE_LIMIT bits and stopped WITHOUT
                # consuming the terminating 1 bit the encoder wrote as part
                # of write_bits(1, RICE_LIMIT + 1). Consume it here, or the
                # raw value is read one bit early and the stream desyncs.
                reader.read_bits(1)
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tools/fcr-reference && python -m pytest tests/test_rice_bitstream.py -v`
Expected: PASS — 25 passed

- [ ] **Step 5: Run the whole suite to check nothing regressed**

Run: `cd tools/fcr-reference && python -m pytest -v`
Expected: PASS — all tests

- [ ] **Step 6: Commit**

```bash
git add tools/fcr-reference/src/fcrref/rice.py tools/fcr-reference/tests/test_rice_bitstream.py
git commit -m "feat(fcrref): add Rice bitstream encoder and decoder"
```

---

## Task 6: Whole-frame codec with strip layout

**Files:**
- Create: `tools/fcr-reference/src/fcrref/framecodec.py`
- Test: `tools/fcr-reference/tests/test_framecodec.py`

**Interfaces:**
- Consumes: `bayer.{split_planes, merge_planes, PLANE_ORDER}`, `predictor.{forward, inverse}`, `rice.{encode_plane, decode_plane, plane_bit_length}`
- Produces:
  - `encode_frame(mosaic: np.ndarray, pattern: str, strips: int = 1) -> bytes`
  - `decode_frame(payload: bytes, height: int, width: int, pattern: str) -> np.ndarray`
  - `estimate_frame_bits(mosaic: np.ndarray, pattern: str, strips: int = 1) -> int`

Payload layout (normative, little-endian):

```
u8   plane_count      always 4
u8   strip_count
u16  reserved         always 0
u32  strip_byte_length  x (plane_count * strip_count), plane-major
     ...concatenated strip bitstreams, plane-major then strip-minor
```

Each strip is predicted independently — its first row uses the row-0 rule — so strips can be encoded and decoded in parallel. (spec §5.4)

- [ ] **Step 1: Write the failing test**

`tools/fcr-reference/tests/test_framecodec.py`:

```python
import struct

import numpy as np
import pytest

from fcrref import framecodec
from fcrref.constants import CFA_PATTERNS


def _frame(height=64, width=96, seed=20260819):
    rng = np.random.default_rng(seed)
    return rng.integers(0, 16384, size=(height, width), dtype=np.uint16)


def test_payload_header_declares_four_planes():
    payload = framecodec.encode_frame(_frame(), "RGGB", strips=2)
    plane_count, strip_count, reserved = struct.unpack_from("<BBH", payload, 0)
    assert plane_count == 4
    assert strip_count == 2
    assert reserved == 0


@pytest.mark.parametrize("pattern", CFA_PATTERNS)
def test_roundtrip_all_patterns(pattern):
    m = _frame()
    payload = framecodec.encode_frame(m, pattern)
    assert np.array_equal(framecodec.decode_frame(payload, *m.shape, pattern), m)


@pytest.mark.parametrize("strips", [1, 2, 3, 8])
def test_roundtrip_various_strip_counts(strips):
    m = _frame(height=96, width=64)
    payload = framecodec.encode_frame(m, "RGGB", strips=strips)
    assert np.array_equal(framecodec.decode_frame(payload, *m.shape, "RGGB"), m)


def test_flat_frame_compresses_hard():
    """A flat frame codes every residual as a single bit, plus a 4-bit k
    header per 512-sample block: ~1.008 bits/sample against 14, so ~13.9:1.
    The bound is set below that, not at some round number."""
    m = np.full((256, 256), 2048, dtype=np.uint16)
    payload = framecodec.encode_frame(m, "RGGB")
    raw_bytes = m.size * 14 / 8
    assert len(payload) < raw_bytes / 10


def test_estimate_matches_actual_payload_size():
    m = _frame(height=128, width=128)
    bits = framecodec.estimate_frame_bits(m, "RGGB", strips=4)
    payload = framecodec.encode_frame(m, "RGGB", strips=4)
    # Estimate covers bitstream only; add header and per-strip padding.
    header = 4 + 4 * 4 * 4
    assert header + (bits + 7) // 8 <= len(payload) <= header + (bits + 7) // 8 + 16


def test_rejects_strip_count_exceeding_plane_height():
    m = _frame(height=8, width=8)  # planes are 4 rows tall
    with pytest.raises(ValueError):
        framecodec.encode_frame(m, "RGGB", strips=5)


def test_output_is_deterministic():
    m = _frame()
    assert framecodec.encode_frame(m, "RGGB") == framecodec.encode_frame(m, "RGGB")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/fcr-reference && python -m pytest tests/test_framecodec.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fcrref.framecodec'`

- [ ] **Step 3: Write `framecodec.py`**

`tools/fcr-reference/src/fcrref/framecodec.py`:

```python
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


def encode_frame(mosaic: np.ndarray, pattern: str, strips: int = 1) -> bytes:
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
    planes = split_planes(mosaic, pattern)
    plane_height = planes[PLANE_ORDER[0]].shape[0]
    bounds = _strip_bounds(plane_height, strips)
    total = 0
    for name in PLANE_ORDER:
        plane = planes[name]
        for top, bottom in bounds:
            total += plane_bit_length(forward(plane[top:bottom]))
    return total
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tools/fcr-reference && python -m pytest tests/test_framecodec.py -v`
Expected: PASS — 16 passed

- [ ] **Step 5: Commit**

```bash
git add tools/fcr-reference/src/fcrref/framecodec.py tools/fcr-reference/tests/test_framecodec.py
git commit -m "feat(fcrref): add whole-frame codec with strip-parallel payload layout"
```

---

## Task 7: Compression ratio analyzer (W2 — the project's biggest open question)

**Files:**
- Create: `tools/fcr-reference/src/fcrref/analyze.py`
- Test: `tools/fcr-reference/tests/test_analyze.py`

**Interfaces:**
- Consumes: `framecodec.estimate_frame_bits`, `bayer.split_planes`, `rice.plane_bit_length`
- Produces:
  - `analyze_frame(mosaic: np.ndarray, pattern: str) -> FrameStats` (dataclass with `pixels`, `raw_bits`, `coded_bits`, `ratio`, `per_plane_ratio: dict[str, float]`)
  - `load_dng(path: str) -> tuple[np.ndarray, str]` — requires the `dng` extra
  - `load_raw16(path: str, height: int, width: int) -> np.ndarray`
  - CLI: `python -m fcrref.analyze --input <glob> [--pattern RGGB] [--raw16 HxW]`

**This task produces the number that validates or invalidates spec §2.1.** Run it against real RAW Cam DNGs from an iPhone 15. If the aggregate ratio is below 2.0:1, report it — the 12 MP primary mode does not fit and the spec needs revising.

> **Expect this to be tight, and possibly to fail.**
>
> Hand analysis of a photon-noise-dominated synthetic frame (the closest proxy
> available without real data) lands near **1.6:1**, not the 2.2–2.6:1 the spec
> infers from RAW Cam's published bitrate. Two things could explain the gap, and
> only real data distinguishes them:
>
> 1. **Real footage is less noisy than the proxy.** Much of a real frame is
>    smooth — sky, walls, skin — where residuals are far smaller than in a
>    synthetic field of uniform shot noise. Real ratios are usually better.
> 2. **RAW Cam's figure includes something we are not modelling** — a different
>    predictor, a noise-shaping step, or simply a lower effective bit depth.
>
> If the measured ratio comes back below 2.0:1, that is a **finding, not a
> failure of this task**. Stop, record it, and revise spec §2.1 before Stage M0.
> The fallbacks are already named in spec §5.4: 4K crop, or 18 fps.
>
> **Runtime note:** `analyze` deliberately uses `estimate_frame_bits`, which
> never enters a per-sample Python loop. A full 12 MP frame takes roughly a
> minute. Running the actual `encode_frame` on 12 MP would take many minutes —
> that path exists for conformance vectors at small geometry, not for bulk
> measurement.

- [ ] **Step 1: Write the failing test**

`tools/fcr-reference/tests/test_analyze.py`:

```python
import numpy as np

from fcrref import analyze
from fcrref.constants import BIT_DEPTH


def test_raw_bits_counts_bit_depth_per_pixel():
    m = np.zeros((64, 64), dtype=np.uint16)
    stats = analyze.analyze_frame(m, "RGGB")
    assert stats.pixels == 64 * 64
    assert stats.raw_bits == 64 * 64 * BIT_DEPTH


def test_flat_frame_reports_very_high_ratio():
    """Ceiling is ~13.9:1 — one bit per sample plus block headers."""
    m = np.full((256, 256), 4000, dtype=np.uint16)
    assert analyze.analyze_frame(m, "RGGB").ratio > 12.0


def test_uniform_noise_reports_ratio_near_one():
    """Full-scale white noise is incompressible; ratio must not exceed ~1.1."""
    rng = np.random.default_rng(20260819)
    m = rng.integers(0, 16384, size=(256, 256), dtype=np.uint16)
    assert analyze.analyze_frame(m, "RGGB").ratio < 1.1


def test_per_plane_ratios_are_reported_for_all_four_planes():
    rng = np.random.default_rng(3)
    m = rng.integers(0, 16384, size=(64, 64), dtype=np.uint16)
    stats = analyze.analyze_frame(m, "RGGB")
    assert set(stats.per_plane_ratio) == {"R", "G1", "G2", "B"}


def test_realistic_sensor_noise_compresses_meaningfully():
    """Photon-noise-dominated image data — a smooth scene plus shot noise
    proportional to sqrt(signal), which is what a real sensor produces.

    This is a CHARACTERISATION test, not a spec check. Hand analysis puts
    this proxy near 1.6:1: at signal ~2000 the shot noise is ~45 DN, MED
    residuals run ~1.5x that, so the mean zigzag value is ~108, optimal
    k ~6, and the cost lands around 8.7 bits against 14.

    Do NOT relax or tighten this bound to make the spec's 2.2-2.6:1 target
    appear met. That number can only be settled by Task 7 Step 7, against
    real DNGs. See the warning in the Task 7 preamble.
    """
    rng = np.random.default_rng(11)
    y, x = np.mgrid[0:512, 0:512]
    signal = (2000 + 1500 * np.sin(x / 60.0) * np.cos(y / 80.0)).astype(np.float64)
    noisy = rng.poisson(np.clip(signal, 1.0, None)).clip(0, 16383).astype(np.uint16)
    ratio = analyze.analyze_frame(noisy, "RGGB").ratio
    assert 1.2 < ratio < 3.0


def test_load_raw16_reads_little_endian_pairs(tmp_path):
    src = np.arange(24, dtype=np.uint16).reshape(4, 6)
    path = tmp_path / "frame.raw16"
    path.write_bytes(src.astype("<u2").tobytes())
    assert np.array_equal(analyze.load_raw16(str(path), 4, 6), src)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/fcr-reference && python -m pytest tests/test_analyze.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fcrref.analyze'`

- [ ] **Step 3: Write `analyze.py`**

`tools/fcr-reference/src/fcrref/analyze.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tools/fcr-reference && python -m pytest tests/test_analyze.py -v`
Expected: PASS — 6 passed

- [ ] **Step 5: Sanity-run the CLI against a synthetic frame**

```bash
cd tools/fcr-reference
python -c "
import numpy as np
y, x = np.mgrid[0:3024, 0:4032]
sig = (1500 + 1200*np.sin(x/90.0)*np.cos(y/110.0))
np.random.default_rng(2).poisson(sig).clip(0,16383).astype('<u2').tofile('synthetic.raw16')
"
python -m fcrref.analyze --input synthetic.raw16 --raw16 3024x4032 --pattern RGGB
rm synthetic.raw16
```

Expected: a ratio report at full 12 MP geometry, confirming the tool runs at production frame size.

- [ ] **Step 6: Commit**

```bash
git add tools/fcr-reference/src/fcrref/analyze.py tools/fcr-reference/tests/test_analyze.py
git commit -m "feat(fcrref): add compression ratio analyzer for real Bayer data"
```

- [ ] **Step 7: Run against real footage and record the result**

Once RAW Cam DNGs from an iPhone 15 are available:

```bash
python -m fcrref.analyze --input "path/to/clip/*.dng" > docs/superpowers/measurements/2026-XX-XX-compression-ratio.txt
```

Append the aggregate ratio to spec §5.4 as a measured fact, replacing the inferred 2.2–2.6:1. **If it is below 2.0:1, stop and revise the spec before continuing to Task 8.**

---

## Task 8: `.fcr` container writer and reader

**Files:**
- Create: `tools/fcr-reference/src/fcrref/container.py`
- Create: `tools/fcr-reference/tests/conftest.py`
- Test: `tools/fcr-reference/tests/test_container.py`

**Interfaces:**
- Consumes: `constants.{HEADER_SIZE, HEADER_MAGIC, FRAME_MAGIC, TRAILER_MAGIC}`, `framecodec.{encode_frame, decode_frame}`
- Produces:
  - `ClipHeader` dataclass with every field from spec §5.3
  - `pack_header(h: ClipHeader) -> bytes` / `unpack_header(data: bytes) -> ClipHeader`
  - `FcrWriter(path)` with `write_header(h)`, `append_frame(mosaic, sequence, pts_ns, exposure_ns, iso, lens_position)`, `finalize()`
  - `FcrReader(path)` with `header`, `frame_count`, `read_frame(index) -> tuple[np.ndarray, FrameMeta]`

- [ ] **Step 1: Write the shared test fixtures**

Every value here is exactly representable in float32. That matters: the header packs
floats as `f`, so a value like `1.6` or `0.7` would not survive a round-trip and the
equality assertion below would fail for reasons that have nothing to do with the code.

`tools/fcr-reference/tests/conftest.py`:

```python
import numpy as np
import pytest

from fcrref.container import ClipHeader


def build_header(width: int = 64, height: int = 48) -> ClipHeader:
    """A valid header. All float fields are float32-exact on purpose."""
    return ClipHeader(
        width=width,
        height=height,
        bit_depth=14,
        cfa_pattern="RGGB",
        frame_rate_num=24000,
        frame_rate_den=1000,
        black_level=(64, 64, 64, 64),
        white_level=(16383, 16383, 16383, 16383),
        color_matrix1=tuple(range(9)),
        color_matrix2=tuple(range(9)),
        as_shot_neutral=(0.5, 1.0, 0.75),
        lens_id="main",
        focal_length_35=24.0,
        aperture=1.5,
        intrinsic_matrix=(1000.0, 0.0, 32.0, 0.0, 1000.0, 24.0, 0.0, 0.0, 1.0),
        readout_time_ns=16_000_000,
        ois_enabled=False,
        start_timecode="01:00:00:00",
        created_at_ns=0,
        device_model="iPhone15,4",
    )


def build_frame(header: ClipHeader, seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(
        0, 16384, size=(header.height, header.width), dtype=np.uint16
    )


@pytest.fixture
def make_header():
    return build_header


@pytest.fixture
def make_frame():
    return build_frame
```

- [ ] **Step 2: Write the failing test**

`tools/fcr-reference/tests/test_container.py`:

```python
import struct

import numpy as np
import pytest

from conftest import build_frame as _frame, build_header as _header
from fcrref.constants import HEADER_MAGIC, HEADER_SIZE, TRAILER_MAGIC
from fcrref.container import FcrReader, FcrWriter, pack_header, unpack_header


def test_header_is_exactly_4096_bytes():
    assert len(pack_header(_header())) == HEADER_SIZE


def test_header_starts_with_magic():
    assert pack_header(_header())[:4] == HEADER_MAGIC


def test_header_roundtrip_preserves_every_field():
    h = _header()
    assert unpack_header(pack_header(h)) == h


def test_unpack_rejects_bad_magic():
    data = bytearray(pack_header(_header()))
    data[0:4] = b"XXXX"
    with pytest.raises(ValueError):
        unpack_header(bytes(data))


def test_write_read_single_frame(tmp_path):
    h = _header()
    m = _frame(h)
    path = tmp_path / "clip.fcr"
    w = FcrWriter(str(path))
    w.write_header(h)
    w.append_frame(m, sequence=0, pts_ns=1000, exposure_ns=20833333, iso=400,
                   lens_position=0.5)
    w.finalize()

    r = FcrReader(str(path))
    assert r.frame_count == 1
    decoded, meta = r.read_frame(0)
    assert np.array_equal(decoded, m)
    assert meta.sequence == 0
    assert meta.pts_ns == 1000
    assert meta.iso == 400


def test_write_read_many_frames(tmp_path):
    h = _header()
    frames = [_frame(h, seed=i) for i in range(5)]
    path = tmp_path / "clip.fcr"
    w = FcrWriter(str(path))
    w.write_header(h)
    for i, m in enumerate(frames):
        w.append_frame(m, sequence=i, pts_ns=i * 41_666_667,
                       exposure_ns=20833333, iso=400, lens_position=0.5)
    w.finalize()

    r = FcrReader(str(path))
    assert r.frame_count == 5
    for i, expected in enumerate(frames):
        decoded, meta = r.read_frame(i)
        assert np.array_equal(decoded, expected)
        assert meta.sequence == i


def test_finalized_file_ends_with_trailer(tmp_path):
    h = _header()
    path = tmp_path / "clip.fcr"
    w = FcrWriter(str(path))
    w.write_header(h)
    w.append_frame(_frame(h), 0, 0, 1, 100, 0.0)
    w.finalize()
    tail = path.read_bytes()[-12:]
    assert tail[:4] == TRAILER_MAGIC
    index_offset = struct.unpack("<Q", tail[4:])[0]
    assert index_offset >= HEADER_SIZE


def test_reader_detects_crc_corruption(tmp_path):
    h = _header()
    path = tmp_path / "clip.fcr"
    w = FcrWriter(str(path))
    w.write_header(h)
    w.append_frame(_frame(h), 0, 0, 1, 100, 0.0)
    w.finalize()

    data = bytearray(path.read_bytes())
    data[HEADER_SIZE + 200] ^= 0xFF  # corrupt inside the payload
    path.write_bytes(bytes(data))

    r = FcrReader(str(path))
    with pytest.raises(ValueError, match="CRC"):
        r.read_frame(0)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd tools/fcr-reference && python -m pytest tests/test_container.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fcrref.container'`

- [ ] **Step 4: Write `container.py`**

`tools/fcr-reference/src/fcrref/container.py`:

```python
"""The .fcr container: append-only, crash-resilient by construction.

Layout (spec 5.3):
    Header      4096 bytes, fixed
    Frame       "FRM0" + fields + CRC32 + payload, repeated
    Index       appended at finalize
    Trailer     "FCRX" + u64 index offset, last 12 bytes
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

import numpy as np

from .constants import (
    FRAME_MAGIC,
    HEADER_MAGIC,
    HEADER_SIZE,
    TRAILER_MAGIC,
)
from .framecodec import decode_frame, encode_frame

_HDR_FIXED = "<4sHIIB16s2I4H4I9f9f3f16sff9fQ?16sQ32s"
_FRAME_FIXED = "<4sIQIHfII"
_FRAME_FIXED_SIZE = struct.calcsize(_FRAME_FIXED)


def _fixed_str(value: str, size: int) -> bytes:
    raw = value.encode("utf-8")
    if len(raw) > size:
        raise ValueError(f"{value!r} exceeds {size} bytes")
    return raw.ljust(size, b"\0")


def _read_str(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("utf-8")


@dataclass(frozen=True)
class ClipHeader:
    width: int
    height: int
    bit_depth: int
    cfa_pattern: str
    frame_rate_num: int
    frame_rate_den: int
    black_level: tuple[int, int, int, int]
    white_level: tuple[int, int, int, int]
    color_matrix1: tuple[float, ...]
    color_matrix2: tuple[float, ...]
    as_shot_neutral: tuple[float, float, float]
    lens_id: str
    focal_length_35: float
    aperture: float
    intrinsic_matrix: tuple[float, ...]
    readout_time_ns: int
    ois_enabled: bool
    start_timecode: str
    created_at_ns: int
    device_model: str


@dataclass(frozen=True)
class FrameMeta:
    sequence: int
    pts_ns: int
    exposure_ns: int
    iso: int
    lens_position: float


def pack_header(h: ClipHeader) -> bytes:
    body = struct.pack(
        _HDR_FIXED,
        HEADER_MAGIC,
        1,                              # version
        h.width,
        h.height,
        h.bit_depth,
        _fixed_str(h.cfa_pattern, 16),
        h.frame_rate_num,
        h.frame_rate_den,
        *h.black_level,
        *h.white_level,
        *h.color_matrix1,
        *h.color_matrix2,
        *h.as_shot_neutral,
        _fixed_str(h.lens_id, 16),
        h.focal_length_35,
        h.aperture,
        *h.intrinsic_matrix,
        h.readout_time_ns,
        h.ois_enabled,
        _fixed_str(h.start_timecode, 16),
        h.created_at_ns,
        _fixed_str(h.device_model, 32),
    )
    if len(body) > HEADER_SIZE:
        raise ValueError("header body exceeds 4096 bytes")
    return body.ljust(HEADER_SIZE, b"\0")


def unpack_header(data: bytes) -> ClipHeader:
    if len(data) < HEADER_SIZE:
        raise ValueError("header truncated")
    fields = struct.unpack_from(_HDR_FIXED, data, 0)
    if fields[0] != HEADER_MAGIC:
        raise ValueError(f"bad header magic {fields[0]!r}")
    i = 2  # skip magic, version
    width, height, bit_depth = fields[i], fields[i + 1], fields[i + 2]
    cfa = _read_str(fields[i + 3])
    fr_num, fr_den = fields[i + 4], fields[i + 5]
    black = tuple(fields[i + 6:i + 10])
    white = tuple(fields[i + 10:i + 14])
    cm1 = tuple(fields[i + 14:i + 23])
    cm2 = tuple(fields[i + 23:i + 32])
    neutral = tuple(fields[i + 32:i + 35])
    lens_id = _read_str(fields[i + 35])
    focal, aperture = fields[i + 36], fields[i + 37]
    intrinsics = tuple(fields[i + 38:i + 47])
    readout, ois = fields[i + 47], fields[i + 48]
    timecode = _read_str(fields[i + 49])
    created = fields[i + 50]
    model = _read_str(fields[i + 51])
    return ClipHeader(
        width=width, height=height, bit_depth=bit_depth, cfa_pattern=cfa,
        frame_rate_num=fr_num, frame_rate_den=fr_den,
        black_level=black, white_level=white,
        color_matrix1=cm1, color_matrix2=cm2, as_shot_neutral=neutral,
        lens_id=lens_id, focal_length_35=focal, aperture=aperture,
        intrinsic_matrix=intrinsics, readout_time_ns=readout,
        ois_enabled=bool(ois), start_timecode=timecode,
        created_at_ns=created, device_model=model,
    )


def pack_frame(payload: bytes, meta: FrameMeta) -> bytes:
    return struct.pack(
        _FRAME_FIXED,
        FRAME_MAGIC,
        meta.sequence,
        meta.pts_ns,
        meta.exposure_ns,
        meta.iso,
        meta.lens_position,
        len(payload),
        zlib.crc32(payload) & 0xFFFFFFFF,
    ) + payload


class FcrWriter:
    def __init__(self, path: str) -> None:
        self._file = open(path, "wb")
        self._header: ClipHeader | None = None
        self._index: list[tuple[int, int]] = []

    def write_header(self, header: ClipHeader) -> None:
        self._header = header
        self._file.write(pack_header(header))

    def append_frame(self, mosaic: np.ndarray, sequence: int, pts_ns: int,
                     exposure_ns: int, iso: int, lens_position: float,
                     strips: int = 1) -> None:
        if self._header is None:
            raise RuntimeError("write_header must be called first")
        payload = encode_frame(mosaic, self._header.cfa_pattern, strips)
        meta = FrameMeta(sequence, pts_ns, exposure_ns, iso, lens_position)
        record = pack_frame(payload, meta)
        offset = self._file.tell()
        self._file.write(record)
        self._index.append((offset, len(record)))

    def finalize(self) -> None:
        index_offset = self._file.tell()
        self._file.write(struct.pack("<I", len(self._index)))
        for offset, size in self._index:
            self._file.write(struct.pack("<QI", offset, size))
        self._file.write(TRAILER_MAGIC)
        self._file.write(struct.pack("<Q", index_offset))
        self._file.close()


class FcrReader:
    def __init__(self, path: str) -> None:
        self._path = path
        with open(path, "rb") as fh:
            self._data = fh.read()
        self.header = unpack_header(self._data)
        self._index = self._load_index()

    def _load_index(self) -> list[tuple[int, int]]:
        tail = self._data[-12:]
        if len(tail) < 12 or tail[:4] != TRAILER_MAGIC:
            raise ValueError("missing trailer; use repair.scan_frames")
        index_offset = struct.unpack("<Q", tail[4:])[0]
        count = struct.unpack_from("<I", self._data, index_offset)[0]
        entries = []
        pos = index_offset + 4
        for _ in range(count):
            offset, size = struct.unpack_from("<QI", self._data, pos)
            entries.append((offset, size))
            pos += 12
        return entries

    @property
    def frame_count(self) -> int:
        return len(self._index)

    def read_frame(self, index: int) -> tuple[np.ndarray, FrameMeta]:
        offset, _size = self._index[index]
        (magic, sequence, pts_ns, exposure_ns, iso, lens_position,
         payload_bytes, crc) = struct.unpack_from(_FRAME_FIXED, self._data, offset)
        if magic != FRAME_MAGIC:
            raise ValueError(f"bad frame magic at offset {offset}")
        start = offset + _FRAME_FIXED_SIZE
        payload = self._data[start:start + payload_bytes]
        if (zlib.crc32(payload) & 0xFFFFFFFF) != crc:
            raise ValueError(f"CRC mismatch on frame {index}")
        mosaic = decode_frame(
            payload, self.header.height, self.header.width, self.header.cfa_pattern
        )
        meta = FrameMeta(sequence, pts_ns, exposure_ns, iso, lens_position)
        return mosaic, meta
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd tools/fcr-reference && python -m pytest tests/test_container.py -v`
Expected: PASS — 8 passed

- [ ] **Step 6: Commit**

```bash
git add tools/fcr-reference/src/fcrref/container.py tools/fcr-reference/tests/conftest.py tools/fcr-reference/tests/test_container.py
git commit -m "feat(fcrref): add .fcr container writer and reader"
```

---

## Task 9: Repair scan

**Files:**
- Create: `tools/fcr-reference/src/fcrref/repair.py`
- Test: `tools/fcr-reference/tests/test_repair.py`

**Interfaces:**
- Consumes: `container.{FRAME_MAGIC, _FRAME_FIXED, unpack_header}`
- Produces:
  - `scan_frames(path: str) -> list[tuple[int, int]]` — rebuilt index
  - `repair(path: str) -> int` — appends a valid index and trailer, returns frames recovered

Spec §9 demands: truncate at 1000 random offsets, assert every complete frame recovers and no partial frame is ever returned. That is the headline test here.

- [ ] **Step 1: Write the failing test**

`tools/fcr-reference/tests/test_repair.py`:

```python
import numpy as np
import pytest

from conftest import build_header as _header
from fcrref import repair
from fcrref.constants import HEADER_SIZE
from fcrref.container import FcrReader, FcrWriter


def _write_clip(path, frame_count=6, seed=4):
    h = _header(width=32, height=24)
    rng = np.random.default_rng(seed)
    frames = [
        rng.integers(0, 16384, size=(h.height, h.width), dtype=np.uint16)
        for _ in range(frame_count)
    ]
    w = FcrWriter(str(path))
    w.write_header(h)
    for i, m in enumerate(frames):
        w.append_frame(m, i, i * 41_666_667, 20833333, 400, 0.5)
    w.finalize()
    return frames


def test_scan_finds_every_frame_in_a_complete_file(tmp_path):
    path = tmp_path / "clip.fcr"
    frames = _write_clip(path)
    assert len(repair.scan_frames(str(path))) == len(frames)


def test_repair_restores_readability_after_trailer_loss(tmp_path):
    path = tmp_path / "clip.fcr"
    frames = _write_clip(path)

    data = bytearray(path.read_bytes())
    del data[-12:]  # lose the trailer, as a crash would
    path.write_bytes(bytes(data))

    with pytest.raises(ValueError):
        FcrReader(str(path))

    recovered = repair.repair(str(path))
    assert recovered == len(frames)

    r = FcrReader(str(path))
    for i, expected in enumerate(frames):
        decoded, _ = r.read_frame(i)
        assert np.array_equal(decoded, expected)


@pytest.mark.parametrize("seed", range(50))
def test_truncation_never_yields_a_partial_frame(tmp_path, seed):
    """Spec 9: every complete frame recovers, no partial frame is returned."""
    path = tmp_path / f"clip_{seed}.fcr"
    frames = _write_clip(path, frame_count=8, seed=seed)
    full = bytearray(path.read_bytes())

    rng = np.random.default_rng(seed)
    cut = int(rng.integers(HEADER_SIZE, len(full)))
    path.write_bytes(bytes(full[:cut]))

    recovered = repair.repair(str(path))
    assert 0 <= recovered <= len(frames)

    if recovered:
        r = FcrReader(str(path))
        assert r.frame_count == recovered
        for i in range(recovered):
            decoded, _ = r.read_frame(i)
            assert np.array_equal(decoded, frames[i])


def test_repair_on_header_only_file_recovers_nothing(tmp_path):
    path = tmp_path / "clip.fcr"
    _write_clip(path)
    data = path.read_bytes()[:HEADER_SIZE]
    path.write_bytes(data)
    assert repair.repair(str(path)) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/fcr-reference && python -m pytest tests/test_repair.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fcrref.repair'`

- [ ] **Step 3: Write `repair.py`**

`tools/fcr-reference/src/fcrref/repair.py`:

```python
"""Index reconstruction for .fcr files that lost their trailer.

A crash costs exactly one frame: the one in flight. Everything written
before it is recoverable by walking FRM0 markers and validating CRCs.
"""

from __future__ import annotations

import struct
import zlib

from .constants import FRAME_MAGIC, HEADER_SIZE, TRAILER_MAGIC
from .container import _FRAME_FIXED, _FRAME_FIXED_SIZE, unpack_header


def scan_frames(path: str) -> list[tuple[int, int]]:
    """Walk the file from the end of the header, returning (offset, size)
    for every frame whose header, payload and CRC are all intact."""
    with open(path, "rb") as fh:
        data = fh.read()

    unpack_header(data)  # raises if the header itself is unusable

    entries: list[tuple[int, int]] = []
    offset = HEADER_SIZE
    limit = len(data)

    while offset + _FRAME_FIXED_SIZE <= limit:
        magic = data[offset:offset + 4]
        if magic != FRAME_MAGIC:
            break
        (_m, _seq, _pts, _exp, _iso, _lens,
         payload_bytes, crc) = struct.unpack_from(_FRAME_FIXED, data, offset)
        start = offset + _FRAME_FIXED_SIZE
        end = start + payload_bytes
        if end > limit:
            break  # payload truncated: this frame was in flight
        if (zlib.crc32(data[start:end]) & 0xFFFFFFFF) != crc:
            break  # partial write inside the payload
        entries.append((offset, end - offset))
        offset = end

    return entries


def repair(path: str) -> int:
    """Truncate any partial tail, append a fresh index and trailer.

    Returns the number of frames recovered.
    """
    entries = scan_frames(path)
    end_of_frames = entries[-1][0] + entries[-1][1] if entries else HEADER_SIZE

    with open(path, "r+b") as fh:
        fh.truncate(end_of_frames)
        fh.seek(end_of_frames)
        fh.write(struct.pack("<I", len(entries)))
        for offset, size in entries:
            fh.write(struct.pack("<QI", offset, size))
        fh.write(TRAILER_MAGIC)
        fh.write(struct.pack("<Q", end_of_frames))

    return len(entries)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tools/fcr-reference && python -m pytest tests/test_repair.py -v`
Expected: PASS — 53 passed

- [ ] **Step 5: Commit**

```bash
git add tools/fcr-reference/src/fcrref/repair.py tools/fcr-reference/tests/test_repair.py
git commit -m "feat(fcrref): add crash-recovery repair scan for .fcr files"
```

---

## Task 10: `.fcm` motion sidecar

**Files:**
- Create: `tools/fcr-reference/src/fcrref/sidecar.py`
- Test: `tools/fcr-reference/tests/test_sidecar.py`

**Interfaces:**
- Consumes: `constants.SIDECAR_MAGIC`
- Produces:
  - `MotionSample` dataclass: `host_time_ns: int`, `gyro: tuple[float, float, float]`, `accel: tuple[float, float, float]`
  - `FcmWriter(path)` with `write_header(sample_rate_hz)`, `append(sample)`, `close()`
  - `read_sidecar(path) -> tuple[int, list[MotionSample]]`
  - `find_gaps(samples, expected_hz, tolerance=2.0) -> list[tuple[int, int]]` — spans where delivery stalled

Spec §5.5: gaps are recorded explicitly and **never interpolated**. `find_gaps` reports them so the stabilizer can flag rather than guess.

- [ ] **Step 1: Write the failing test**

`tools/fcr-reference/tests/test_sidecar.py`:

```python
import pytest

from fcrref.constants import SIDECAR_MAGIC
from fcrref.sidecar import FcmWriter, MotionSample, find_gaps, read_sidecar


def _samples(count, hz=200, start=0):
    step = int(1e9 / hz)
    return [
        MotionSample(
            host_time_ns=start + i * step,
            gyro=(0.1 * i, -0.2 * i, 0.3 * i),
            accel=(0.0, 9.81, 0.0),
        )
        for i in range(count)
    ]


def test_file_starts_with_magic(tmp_path):
    path = tmp_path / "clip.fcm"
    w = FcmWriter(str(path))
    w.write_header(200)
    w.close()
    assert path.read_bytes()[:4] == SIDECAR_MAGIC


def test_roundtrip_preserves_samples(tmp_path):
    path = tmp_path / "clip.fcm"
    samples = _samples(500)
    w = FcmWriter(str(path))
    w.write_header(200)
    for s in samples:
        w.append(s)
    w.close()

    rate, loaded = read_sidecar(str(path))
    assert rate == 200
    assert len(loaded) == len(samples)
    for a, b in zip(samples, loaded):
        assert a.host_time_ns == b.host_time_ns
        assert a.gyro == pytest.approx(b.gyro)
        assert a.accel == pytest.approx(b.accel)


def test_truncated_sidecar_reads_all_complete_samples(tmp_path):
    path = tmp_path / "clip.fcm"
    w = FcmWriter(str(path))
    w.write_header(200)
    for s in _samples(100):
        w.append(s)
    w.close()

    data = bytearray(path.read_bytes())
    del data[-10:]  # a partial final record
    path.write_bytes(bytes(data))

    _rate, loaded = read_sidecar(str(path))
    assert len(loaded) == 99


def test_find_gaps_returns_empty_for_regular_sampling():
    assert find_gaps(_samples(400), expected_hz=200) == []


def test_find_gaps_detects_a_stall():
    head = _samples(100)
    tail = _samples(100, start=head[-1].host_time_ns + 50_000_000)  # 50 ms hole
    gaps = find_gaps(head + tail, expected_hz=200)
    assert len(gaps) == 1
    assert gaps[0] == (head[-1].host_time_ns, tail[0].host_time_ns)


def test_find_gaps_requires_at_least_two_samples():
    assert find_gaps(_samples(1), expected_hz=200) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/fcr-reference && python -m pytest tests/test_sidecar.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fcrref.sidecar'`

- [ ] **Step 3: Write `sidecar.py`**

`tools/fcr-reference/src/fcrref/sidecar.py`:

```python
"""The .fcm motion sidecar: append-only gyro and accelerometer records.

Written separately from the video container so a crash preserves it
independently. Gaps are reported, never interpolated (spec 5.5).

Layout (little-endian):
    "FCM1"  u16 version  u16 sample_rate_hz   (8 bytes)
    then repeated 32-byte records:
        u64 host_time_ns
        f32 gyro_x, gyro_y, gyro_z
        f32 accel_x, accel_y, accel_z
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .constants import SIDECAR_MAGIC

_HEADER_FMT = "<4sHH"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)
_RECORD_FMT = "<Q6f"
_RECORD_SIZE = struct.calcsize(_RECORD_FMT)


@dataclass(frozen=True)
class MotionSample:
    host_time_ns: int
    gyro: tuple[float, float, float]
    accel: tuple[float, float, float]


class FcmWriter:
    def __init__(self, path: str) -> None:
        self._file = open(path, "wb")

    def write_header(self, sample_rate_hz: int) -> None:
        self._file.write(struct.pack(_HEADER_FMT, SIDECAR_MAGIC, 1, sample_rate_hz))

    def append(self, sample: MotionSample) -> None:
        self._file.write(
            struct.pack(_RECORD_FMT, sample.host_time_ns, *sample.gyro, *sample.accel)
        )

    def close(self) -> None:
        self._file.close()


def read_sidecar(path: str) -> tuple[int, list[MotionSample]]:
    with open(path, "rb") as fh:
        data = fh.read()

    magic, _version, rate = struct.unpack_from(_HEADER_FMT, data, 0)
    if magic != SIDECAR_MAGIC:
        raise ValueError(f"bad sidecar magic {magic!r}")

    samples: list[MotionSample] = []
    offset = _HEADER_SIZE
    while offset + _RECORD_SIZE <= len(data):
        values = struct.unpack_from(_RECORD_FMT, data, offset)
        samples.append(
            MotionSample(
                host_time_ns=values[0],
                gyro=(values[1], values[2], values[3]),
                accel=(values[4], values[5], values[6]),
            )
        )
        offset += _RECORD_SIZE

    return rate, samples


def find_gaps(
    samples: list[MotionSample], expected_hz: int, tolerance: float = 2.0
) -> list[tuple[int, int]]:
    """Return (start_ns, end_ns) spans where the interval exceeded
    `tolerance` times the nominal sample period."""
    if len(samples) < 2:
        return []
    nominal = 1e9 / expected_hz
    threshold = nominal * tolerance
    gaps: list[tuple[int, int]] = []
    for previous, current in zip(samples, samples[1:]):
        if current.host_time_ns - previous.host_time_ns > threshold:
            gaps.append((previous.host_time_ns, current.host_time_ns))
    return gaps
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tools/fcr-reference && python -m pytest tests/test_sidecar.py -v`
Expected: PASS — 6 passed

- [ ] **Step 5: Commit**

```bash
git add tools/fcr-reference/src/fcrref/sidecar.py tools/fcr-reference/tests/test_sidecar.py
git commit -m "feat(fcrref): add .fcm motion sidecar with gap detection"
```

---

## Task 11: Synthetic test patterns (W3)

**Files:**
- Create: `tools/fcr-reference/src/fcrref/patterns.py`
- Test: `tools/fcr-reference/tests/test_patterns.py`

**Interfaces:**
- Consumes: `constants.MAX_VALUE`
- Produces (all return `uint16` Bayer mosaics, all deterministic):
  - `horizontal_ramp(height, width) -> np.ndarray`
  - `vertical_ramp(height, width) -> np.ndarray`
  - `flat(height, width, value) -> np.ndarray`
  - `colour_bars(height, width, pattern) -> np.ndarray`
  - `shot_noise(height, width, seed) -> np.ndarray`
  - `zone_plate(height, width) -> np.ndarray`
  - `motion_sequence(height, width, frames, seed) -> list[np.ndarray]`

These feed Stage M1's `FileBackedSource`. Determinism is non-negotiable — the Swift tests assert against ground truth computed from these exact arrays.

- [ ] **Step 1: Write the failing test**

`tools/fcr-reference/tests/test_patterns.py`:

```python
import numpy as np

from fcrref import patterns
from fcrref.constants import MAX_VALUE


def test_horizontal_ramp_increases_left_to_right():
    m = patterns.horizontal_ramp(32, 64)
    assert m[0, 0] == 0
    assert m[0, -1] == MAX_VALUE
    assert np.all(np.diff(m[0].astype(np.int32)) >= 0)


def test_horizontal_ramp_is_constant_down_each_column():
    m = patterns.horizontal_ramp(32, 64)
    assert np.all(m == m[0][None, :])


def test_vertical_ramp_is_constant_across_each_row():
    m = patterns.vertical_ramp(32, 64)
    assert np.all(m == m[:, 0][:, None])


def test_flat_returns_requested_value():
    m = patterns.flat(16, 16, 1234)
    assert np.all(m == 1234)


def test_colour_bars_has_expected_distinct_columns():
    m = patterns.colour_bars(64, 64, "RGGB")
    assert len(np.unique(m[0])) > 1


def test_shot_noise_is_deterministic_for_a_seed():
    a = patterns.shot_noise(64, 64, seed=7)
    b = patterns.shot_noise(64, 64, seed=7)
    assert np.array_equal(a, b)


def test_shot_noise_differs_between_seeds():
    a = patterns.shot_noise(64, 64, seed=7)
    b = patterns.shot_noise(64, 64, seed=8)
    assert not np.array_equal(a, b)


def test_all_patterns_stay_in_range():
    for m in (
        patterns.horizontal_ramp(40, 40),
        patterns.vertical_ramp(40, 40),
        patterns.colour_bars(40, 40, "RGGB"),
        patterns.shot_noise(40, 40, seed=1),
        patterns.zone_plate(40, 40),
    ):
        assert m.dtype == np.uint16
        assert m.min() >= 0
        assert m.max() <= MAX_VALUE


def test_motion_sequence_returns_requested_frame_count():
    frames = patterns.motion_sequence(32, 32, frames=5, seed=2)
    assert len(frames) == 5


def test_motion_sequence_frames_differ():
    frames = patterns.motion_sequence(32, 32, frames=3, seed=2)
    assert not np.array_equal(frames[0], frames[1])


def test_motion_sequence_is_deterministic():
    a = patterns.motion_sequence(32, 32, frames=3, seed=2)
    b = patterns.motion_sequence(32, 32, frames=3, seed=2)
    assert all(np.array_equal(x, y) for x, y in zip(a, b))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/fcr-reference && python -m pytest tests/test_patterns.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fcrref.patterns'`

- [ ] **Step 3: Write `patterns.py`**

`tools/fcr-reference/src/fcrref/patterns.py`:

```python
"""Deterministic synthetic Bayer test patterns.

These are the inputs Stage M1's FileBackedSource replays, and the
material scopes.py computes ground truth from. Every function must
return byte-identical output for the same arguments, on any machine.
"""

from __future__ import annotations

import numpy as np

from .constants import MAX_VALUE

# 75% colour bar values, scaled to 14-bit, in the classic order.
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


def horizontal_ramp(height: int, width: int) -> np.ndarray:
    row = np.linspace(0, MAX_VALUE, width, dtype=np.float64)
    return np.tile(np.round(row), (height, 1)).astype(np.uint16)


def vertical_ramp(height: int, width: int) -> np.ndarray:
    column = np.linspace(0, MAX_VALUE, height, dtype=np.float64)
    return np.tile(np.round(column)[:, None], (1, width)).astype(np.uint16)


def flat(height: int, width: int, value: int) -> np.ndarray:
    if not 0 <= value <= MAX_VALUE:
        raise ValueError(f"value must be 0..{MAX_VALUE}")
    return np.full((height, width), value, dtype=np.uint16)


def colour_bars(height: int, width: int, pattern: str) -> np.ndarray:
    """Colour bars laid directly onto the mosaic, honouring the CFA."""
    channel_index = {"R": 0, "G": 1, "B": 2}
    out = np.zeros((height, width), dtype=np.uint16)
    bar_width = max(1, width // len(_BAR_LEVELS))
    for x in range(width):
        bar = min(x // bar_width, len(_BAR_LEVELS) - 1)
        levels = _BAR_LEVELS[bar]
        for y in range(height):
            colour = pattern[(y % 2) * 2 + (x % 2)]
            out[y, x] = int(round(levels[channel_index[colour]] * MAX_VALUE))
    return out


def shot_noise(height: int, width: int, seed: int) -> np.ndarray:
    """A smooth scene plus Poisson shot noise — the realistic sensor case."""
    y, x = np.mgrid[0:height, 0:width]
    signal = 2000.0 + 1500.0 * np.sin(x / 60.0) * np.cos(y / 80.0)
    signal = np.clip(signal, 1.0, None)
    rng = np.random.default_rng(seed)
    return rng.poisson(signal).clip(0, MAX_VALUE).astype(np.uint16)


def zone_plate(height: int, width: int) -> np.ndarray:
    """Radial frequency sweep — stresses demosaic and scaling."""
    y, x = np.mgrid[0:height, 0:width]
    cy, cx = height / 2.0, width / 2.0
    r2 = (x - cx) ** 2 + (y - cy) ** 2
    wave = np.sin(r2 / max(width, height))
    return np.round((wave * 0.5 + 0.5) * MAX_VALUE).astype(np.uint16)


def motion_sequence(
    height: int, width: int, frames: int, seed: int
) -> list[np.ndarray]:
    """A pattern translated by a deterministic pseudo-random walk.

    Used to exercise frame pacing and, later, stabilization.
    """
    base = zone_plate(height, width)
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tools/fcr-reference && python -m pytest tests/test_patterns.py -v`
Expected: PASS — 11 passed

- [ ] **Step 5: Commit**

```bash
git add tools/fcr-reference/src/fcrref/patterns.py tools/fcr-reference/tests/test_patterns.py
git commit -m "feat(fcrref): add deterministic synthetic Bayer test patterns"
```

---

## Task 12: Scope ground truth (W5)

**Files:**
- Create: `tools/fcr-reference/src/fcrref/scopes.py`
- Test: `tools/fcr-reference/tests/test_scopes.py`

**Interfaces:**
- Consumes: `constants.MAX_VALUE`
- Produces:
  - `luma(rgb: np.ndarray) -> np.ndarray` — Rec.709 luma from float RGB in 0..1
  - `histogram(image: np.ndarray, bins: int = 256) -> np.ndarray` — shape `(bins,)`
  - `waveform(luma_image: np.ndarray, bins: int = 256) -> np.ndarray` — shape `(bins, width)`
  - `vectorscope(rgb: np.ndarray, bins: int = 256) -> np.ndarray` — shape `(bins, bins)`

Spec §9: "A luminance ramp has a provably correct waveform." These functions are that proof, and Stage M1's Metal shaders are asserted against their output.

- [ ] **Step 1: Write the failing test**

`tools/fcr-reference/tests/test_scopes.py`:

```python
import numpy as np

from fcrref import scopes


def test_luma_of_white_is_one():
    rgb = np.ones((2, 2, 3))
    assert np.allclose(scopes.luma(rgb), 1.0)


def test_luma_uses_rec709_coefficients():
    rgb = np.zeros((1, 1, 3))
    rgb[0, 0] = (0.0, 1.0, 0.0)
    assert np.isclose(scopes.luma(rgb)[0, 0], 0.7152)


def test_histogram_of_flat_image_is_a_single_spike():
    image = np.full((16, 16), 0.5)
    h = scopes.histogram(image)
    assert h.sum() == 256
    assert np.count_nonzero(h) == 1


def test_histogram_bin_count_is_respected():
    assert scopes.histogram(np.zeros((4, 4)), bins=64).shape == (64,)


def test_waveform_of_horizontal_ramp_is_a_diagonal():
    """Each column holds one constant value, rising left to right."""
    width = 64
    ramp = np.tile(np.linspace(0, 1, width), (32, 1))
    wf = scopes.waveform(ramp)
    assert wf.shape == (256, width)
    for x in range(width):
        column = wf[:, x]
        assert np.count_nonzero(column) == 1
        assert column.sum() == 32
    peaks = [int(np.argmax(wf[:, x])) for x in range(width)]
    assert peaks == sorted(peaks)
    assert peaks[0] < peaks[-1]


def test_waveform_of_vertical_ramp_fills_every_column_uniformly():
    height = 256
    ramp = np.tile(np.linspace(0, 1, height)[:, None], (1, 32))
    wf = scopes.waveform(ramp)
    assert np.all(wf.sum(axis=0) == height)
    assert np.count_nonzero(wf[:, 0]) == height


def test_vectorscope_of_neutral_grey_lands_at_centre():
    rgb = np.full((8, 8, 3), 0.5)
    vs = scopes.vectorscope(rgb)
    assert vs.shape == (256, 256)
    assert vs[128, 128] == 64
    assert vs.sum() == 64


def test_vectorscope_of_saturated_red_is_off_centre():
    rgb = np.zeros((4, 4, 3))
    rgb[..., 0] = 1.0
    vs = scopes.vectorscope(rgb)
    y, x = np.unravel_index(int(np.argmax(vs)), vs.shape)
    assert (y, x) != (128, 128)


def test_all_scopes_are_deterministic():
    rgb = np.random.default_rng(3).random((16, 16, 3))
    assert np.array_equal(scopes.vectorscope(rgb), scopes.vectorscope(rgb))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/fcr-reference && python -m pytest tests/test_scopes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fcrref.scopes'`

- [ ] **Step 3: Write `scopes.py`**

`tools/fcr-reference/src/fcrref/scopes.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tools/fcr-reference && python -m pytest tests/test_scopes.py -v`
Expected: PASS — 9 passed

- [ ] **Step 5: Commit**

```bash
git add tools/fcr-reference/src/fcrref/scopes.py tools/fcr-reference/tests/test_scopes.py
git commit -m "feat(fcrref): add ground-truth histogram, waveform and vectorscope"
```

---

## Task 13: Look LUTs and false-colour IRE table (W4)

**Files:**
- Create: `tools/fcr-reference/src/fcrref/looks.py`
- Test: `tools/fcr-reference/tests/test_looks.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `write_cube(path, lut: np.ndarray, title: str) -> None` — `lut` is `(N, N, N, 3)` float
  - `read_cube(path) -> tuple[np.ndarray, str]`
  - `identity_lut(size: int = 33) -> np.ndarray`
  - `rec709_lut(size: int = 33) -> np.ndarray`
  - `cineon_to_rec709_lut(size: int = 33) -> np.ndarray`
  - `FALSE_COLOUR_BANDS: tuple[tuple[float, float, str], ...]` — `(ire_low, ire_high, hex_colour)`
  - `false_colour(ire: np.ndarray) -> np.ndarray` — `(…, 3)` uint8 RGB

The false-colour band table is normative and must match the on-screen key in spec §7.

- [ ] **Step 1: Write the failing test**

`tools/fcr-reference/tests/test_looks.py`:

```python
import numpy as np

from fcrref import looks


def test_identity_lut_maps_corners_to_themselves():
    lut = looks.identity_lut(9)
    assert np.allclose(lut[0, 0, 0], (0.0, 0.0, 0.0))
    assert np.allclose(lut[-1, -1, -1], (1.0, 1.0, 1.0))


def test_identity_lut_shape():
    assert looks.identity_lut(17).shape == (17, 17, 17, 3)


def test_cube_roundtrip(tmp_path):
    lut = looks.identity_lut(5)
    path = tmp_path / "identity.cube"
    looks.write_cube(str(path), lut, "Identity")
    loaded, title = looks.read_cube(str(path))
    assert title == "Identity"
    assert np.allclose(loaded, lut, atol=1e-6)


def test_cube_file_declares_size(tmp_path):
    path = tmp_path / "identity.cube"
    looks.write_cube(str(path), looks.identity_lut(5), "Identity")
    assert "LUT_3D_SIZE 5" in path.read_text()


def test_rec709_lut_is_monotonic_on_the_neutral_axis():
    lut = looks.rec709_lut(17)
    neutral = np.array([lut[i, i, i, 0] for i in range(17)])
    assert np.all(np.diff(neutral) > 0)


def test_rec709_lut_preserves_black_and_white():
    lut = looks.rec709_lut(17)
    assert np.allclose(lut[0, 0, 0], 0.0, atol=1e-6)
    assert np.allclose(lut[-1, -1, -1], 1.0, atol=1e-6)


def test_cineon_lut_is_monotonic_and_bounded():
    lut = looks.cineon_to_rec709_lut(17)
    neutral = np.array([lut[i, i, i, 0] for i in range(17)])
    assert np.all(np.diff(neutral) >= 0)
    assert lut.min() >= 0.0 and lut.max() <= 1.0


def test_false_colour_bands_are_contiguous_and_cover_zero_to_hundred():
    bands = looks.FALSE_COLOUR_BANDS
    assert bands[0][0] == 0.0
    assert bands[-1][1] == 100.0
    for lower, upper in zip(bands, bands[1:]):
        assert lower[1] == upper[0]


def test_false_colour_maps_crush_to_the_first_band():
    rgb = looks.false_colour(np.array([0.0]))
    expected = looks.FALSE_COLOUR_BANDS[0][2]
    assert tuple(rgb[0]) == tuple(int(expected[i:i + 2], 16) for i in (1, 3, 5))


def test_false_colour_maps_clip_to_the_last_band():
    rgb = looks.false_colour(np.array([100.0]))
    expected = looks.FALSE_COLOUR_BANDS[-1][2]
    assert tuple(rgb[0]) == tuple(int(expected[i:i + 2], 16) for i in (1, 3, 5))


def test_false_colour_preserves_input_shape():
    assert looks.false_colour(np.zeros((4, 5))).shape == (4, 5, 3)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/fcr-reference && python -m pytest tests/test_looks.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fcrref.looks'`

- [ ] **Step 3: Write `looks.py`**

`tools/fcr-reference/src/fcrref/looks.py`:

```python
"""Look LUTs and the false-colour IRE table.

LUTs are Adobe .cube 3-D LUTs, the format the Metal shader in Stage M1
will consume. The false-colour band table is normative and must match
the on-screen key described in spec 7.
"""

from __future__ import annotations

import numpy as np

# (ire_low, ire_high, hex colour). Contiguous, covering 0..100.
FALSE_COLOUR_BANDS: tuple[tuple[float, float, str], ...] = (
    (0.0, 2.5, "#2b2b8f"),    # crush
    (2.5, 20.0, "#1f7fbf"),   # deep shadow
    (20.0, 42.0, "#2f9e4a"),  # shadow
    (42.0, 52.0, "#d8d84a"),  # skin, low
    (52.0, 62.0, "#e08a2a"),  # skin, mid
    (62.0, 75.0, "#c9c9c9"),  # 70 IRE reference grey
    (75.0, 95.0, "#e8437a"),  # skin, high / highlight
    (95.0, 100.0, "#ff2020"), # clip
)


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


def identity_lut(size: int = 33) -> np.ndarray:
    axis = np.linspace(0.0, 1.0, size)
    r, g, b = np.meshgrid(axis, axis, axis, indexing="ij")
    return np.stack([r, g, b], axis=-1)


def rec709_lut(size: int = 33) -> np.ndarray:
    """Linear light in, Rec.709 OETF out."""
    lut = identity_lut(size)
    v = np.clip(lut, 0.0, 1.0)
    low = v * 4.5
    high = 1.099 * np.power(np.maximum(v, 1e-12), 0.45) - 0.099
    return np.where(v < 0.018, low, high).clip(0.0, 1.0)


def cineon_to_rec709_lut(size: int = 33) -> np.ndarray:
    """Cineon log in (10-bit density, black 95, white 685, gamma 0.6),
    Rec.709 out."""
    lut = identity_lut(size)
    code = lut * 1023.0
    black, white, gamma, density_per_code = 95.0, 685.0, 0.6, 0.002

    def to_linear(c: np.ndarray) -> np.ndarray:
        return np.power(10.0, (c - white) * density_per_code / gamma)

    floor = to_linear(np.array(black))
    linear = (to_linear(code) - floor) / (1.0 - floor)
    linear = np.clip(linear, 0.0, 1.0)

    low = linear * 4.5
    high = 1.099 * np.power(np.maximum(linear, 1e-12), 0.45) - 0.099
    return np.where(linear < 0.018, low, high).clip(0.0, 1.0)


def write_cube(path: str, lut: np.ndarray, title: str) -> None:
    if lut.ndim != 4 or lut.shape[3] != 3 or len({*lut.shape[:3]}) != 1:
        raise ValueError("lut must be (N, N, N, 3)")
    size = lut.shape[0]
    lines = [f'TITLE "{title}"', f"LUT_3D_SIZE {size}", "DOMAIN_MIN 0.0 0.0 0.0",
             "DOMAIN_MAX 1.0 1.0 1.0", ""]
    # .cube order: red varies fastest.
    for b in range(size):
        for g in range(size):
            for r in range(size):
                pixel = lut[r, g, b]
                lines.append(f"{pixel[0]:.6f} {pixel[1]:.6f} {pixel[2]:.6f}")
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")


def read_cube(path: str) -> tuple[np.ndarray, str]:
    title = ""
    size = 0
    values: list[tuple[float, float, float]] = []
    with open(path, "r", encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("TITLE"):
                title = line.split('"')[1] if '"' in line else line[6:].strip()
            elif line.startswith("LUT_3D_SIZE"):
                size = int(line.split()[1])
            elif line.startswith("DOMAIN_"):
                continue
            else:
                parts = line.split()
                if len(parts) == 3:
                    values.append(tuple(float(p) for p in parts))

    if size == 0 or len(values) != size ** 3:
        raise ValueError(f"{path}: expected {size ** 3} entries, got {len(values)}")

    lut = np.empty((size, size, size, 3), dtype=np.float64)
    index = 0
    for b in range(size):
        for g in range(size):
            for r in range(size):
                lut[r, g, b] = values[index]
                index += 1
    return lut, title


def false_colour(ire: np.ndarray) -> np.ndarray:
    """Map IRE values (0..100) to the normative false-colour palette."""
    values = np.clip(np.asarray(ire, dtype=np.float64), 0.0, 100.0)
    out = np.zeros(values.shape + (3,), dtype=np.uint8)
    for low, high, colour in FALSE_COLOUR_BANDS:
        if high >= 100.0:
            mask = (values >= low) & (values <= high)
        else:
            mask = (values >= low) & (values < high)
        out[mask] = _hex_to_rgb(colour)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tools/fcr-reference && python -m pytest tests/test_looks.py -v`
Expected: PASS — 11 passed

- [ ] **Step 5: Commit**

```bash
git add tools/fcr-reference/src/fcrref/looks.py tools/fcr-reference/tests/test_looks.py
git commit -m "feat(fcrref): add .cube LUT support and false-colour IRE table"
```

---

## Task 14: Conformance vector generation (W6)

**Files:**
- Create: `tools/fcr-reference/src/fcrref/vectors.py`
- Test: `tools/fcr-reference/tests/test_vectors.py`
- Create (generated): `tools/fcr-reference/vectors/manifest.json` and payload files

**Interfaces:**
- Consumes: everything above
- Produces:
  - `generate(out_dir: str) -> dict` — writes source frames, Rice bitstreams, frame payloads, **scope ground truth**, and LUTs; returns the manifest
  - CLI: `python -m fcrref.vectors --out vectors/`

These are Stage M1 Task "port the codec to Swift"'s acceptance criteria. The Swift implementation is correct when, and only when, it reproduces every SHA-256 in this manifest.

- [ ] **Step 1: Write the failing test**

`tools/fcr-reference/tests/test_vectors.py`:

```python
import json

from fcrref import vectors


def test_generate_writes_a_manifest(tmp_path):
    manifest = vectors.generate(str(tmp_path))
    path = tmp_path / "manifest.json"
    assert path.exists()
    assert json.loads(path.read_text()) == manifest


def test_manifest_records_a_sha256_per_artifact(tmp_path):
    manifest = vectors.generate(str(tmp_path))
    assert manifest["artifacts"]
    for entry in manifest["artifacts"]:
        assert len(entry["sha256"]) == 64
        assert (tmp_path / entry["name"]).exists()


def test_manifest_pins_the_format_constants(tmp_path):
    manifest = vectors.generate(str(tmp_path))
    constants = manifest["constants"]
    assert constants["bit_depth"] == 14
    assert constants["rice_limit"] == 24
    assert constants["block_size"] == 512
    assert constants["raw_bits"] == 15


def test_generation_is_byte_identical_across_runs(tmp_path):
    first = tmp_path / "a"
    second = tmp_path / "b"
    first.mkdir()
    second.mkdir()
    manifest_a = vectors.generate(str(first))
    manifest_b = vectors.generate(str(second))
    assert manifest_a == manifest_b
    for entry in manifest_a["artifacts"]:
        assert (first / entry["name"]).read_bytes() == (second / entry["name"]).read_bytes()


def test_vectors_cover_every_cfa_pattern(tmp_path):
    manifest = vectors.generate(str(tmp_path))
    names = " ".join(e["name"] for e in manifest["artifacts"])
    for pattern in ("RGGB", "BGGR", "GRBG", "GBRG"):
        assert pattern.lower() in names


def test_vectors_include_scope_ground_truth(tmp_path):
    """Stage M1's Metal scopes are asserted against these."""
    manifest = vectors.generate(str(tmp_path))
    names = {e["name"] for e in manifest["artifacts"]}
    for source in ("hramp", "vramp", "flat", "noise", "zone"):
        assert f"scope_hist_{source}.i64" in names
        assert f"scope_wave_{source}.i64" in names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd tools/fcr-reference && python -m pytest tests/test_vectors.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'fcrref.vectors'`

- [ ] **Step 3: Write `vectors.py`**

`tools/fcr-reference/src/fcrref/vectors.py`:

```python
"""Conformance vector generation.

The Swift port in Stage M1 is correct when it reproduces every SHA-256
recorded here. Generation must be byte-identical across runs and
machines: no timestamps, no unseeded randomness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os

import numpy as np

from . import patterns
from .constants import (
    BIT_DEPTH,
    BLOCK_SIZE,
    CFA_PATTERNS,
    K_BITS,
    MAX_VALUE,
    RAW_BITS,
    RICE_LIMIT,
)
from .framecodec import encode_frame
from .looks import cineon_to_rec709_lut, identity_lut, rec709_lut, write_cube
from .predictor import forward
from .rice import encode_plane
from .scopes import histogram, waveform

_GEOMETRY = (64, 96)  # small enough to commit, large enough to span blocks


def _write(out_dir: str, name: str, data: bytes) -> dict:
    with open(os.path.join(out_dir, name), "wb") as fh:
        fh.write(data)
    return {
        "name": name,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def generate(out_dir: str) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    height, width = _GEOMETRY
    artifacts: list[dict] = []

    # 1. Raw source frames, so the Swift side starts from identical input.
    sources = {
        "hramp": patterns.horizontal_ramp(height, width),
        "vramp": patterns.vertical_ramp(height, width),
        "flat": patterns.flat(height, width, 4096),
        "noise": patterns.shot_noise(height, width, seed=20260819),
        "zone": patterns.zone_plate(height, width),
    }
    for name, mosaic in sources.items():
        artifacts.append(
            _write(out_dir, f"source_{name}.raw16", mosaic.astype("<u2").tobytes())
        )

    # 2. Single-plane Rice bitstreams, isolating the entropy coder.
    for name, mosaic in sources.items():
        residuals = forward(mosaic[0::2, 0::2])
        artifacts.append(
            _write(out_dir, f"rice_{name}.bin", encode_plane(residuals))
        )

    # 3. Full frame payloads across every CFA pattern and both strip modes.
    for pattern in CFA_PATTERNS:
        for strips in (1, 4):
            payload = encode_frame(sources["noise"], pattern, strips=strips)
            artifacts.append(
                _write(
                    out_dir,
                    f"frame_{pattern.lower()}_s{strips}.fcrpayload",
                    payload,
                )
            )

    # 4. Scope ground truth. Without this, Stage M1's Metal histogram and
    #    waveform have nothing to be asserted against.
    for name, mosaic in sources.items():
        proxy = mosaic.astype(np.float64) / MAX_VALUE
        artifacts.append(
            _write(
                out_dir,
                f"scope_hist_{name}.i64",
                histogram(proxy).astype("<i8").tobytes(),
            )
        )
        artifacts.append(
            _write(
                out_dir,
                f"scope_wave_{name}.i64",
                waveform(proxy).astype("<i8").tobytes(),
            )
        )

    # 5. LUTs, so the shader loads identical data.
    for name, lut in (
        ("identity", identity_lut(17)),
        ("rec709", rec709_lut(17)),
        ("cineon_rec709", cineon_to_rec709_lut(17)),
    ):
        path = os.path.join(out_dir, f"lut_{name}.cube")
        write_cube(path, lut, name)
        with open(path, "rb") as fh:
            data = fh.read()
        artifacts.append(
            {
                "name": f"lut_{name}.cube",
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )

    manifest = {
        "version": 1,
        "geometry": {"height": height, "width": width},
        "constants": {
            "bit_depth": BIT_DEPTH,
            "raw_bits": RAW_BITS,
            "rice_limit": RICE_LIMIT,
            "block_size": BLOCK_SIZE,
            "k_bits": K_BITS,
        },
        "artifacts": sorted(artifacts, key=lambda a: a["name"]),
    }

    with open(
        os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8", newline="\n"
    ) as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
        fh.write("\n")

    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate conformance vectors")
    parser.add_argument("--out", default="vectors", help="output directory")
    args = parser.parse_args(argv)
    manifest = generate(args.out)
    print(f"wrote {len(manifest['artifacts'])} artifacts to {args.out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd tools/fcr-reference && python -m pytest tests/test_vectors.py -v`
Expected: PASS — 6 passed

- [ ] **Step 5: Generate the committed vectors**

```bash
cd tools/fcr-reference
python -m fcrref.vectors --out vectors/
```

- [ ] **Step 6: Verify regeneration is byte-identical**

```bash
cd tools/fcr-reference
python -m fcrref.vectors --out /tmp/vectors-check
diff -r vectors/ /tmp/vectors-check && echo "IDENTICAL"
```

Expected: `IDENTICAL`. Any difference is a determinism bug and must be fixed before committing.

- [ ] **Step 7: Run the full suite**

Run: `cd tools/fcr-reference && python -m pytest -v`
Expected: PASS — all tests

- [ ] **Step 8: Commit**

```bash
git add tools/fcr-reference/src/fcrref/vectors.py tools/fcr-reference/tests/test_vectors.py tools/fcr-reference/vectors/
git commit -m "feat(fcrref): add conformance vector generation for the Swift port"
```

---

## Definition of Done

Stage W is complete when:

1. `python -m pytest` passes in `tools/fcr-reference/`.
2. `vectors/manifest.json` is committed and regeneration is byte-identical.
3. `python -m fcrref.analyze` has been run against **real iPhone 15 Bayer data**, and the measured aggregate ratio is recorded in spec §5.4, replacing the inferred figure.
4. If the measured ratio is below 2.0:1, spec §2.1's primary mode has been revised before Stage M0 begins.

## What this plan deliberately does not cover

- **Stage M0** (the capability probe) — needs a Mac. Gets its own short plan.
- **Stage M1/M2** — must be planned *after* P0 reports, because probe results determine which `CaptureSource` is built and can reshape the container's geometry assumptions.
- **Throughput benchmarking.** Python timings on x86 predict nothing about A16 performance. Compression *ratio* is portable; speed is not. Speed is measured in Stage M1 against the Swift implementation.
