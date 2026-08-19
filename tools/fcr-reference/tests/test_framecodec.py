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
