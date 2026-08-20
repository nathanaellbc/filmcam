import struct

import numpy as np
import pytest

from fcrref import framecodec
from fcrref.constants import CFA_PATTERNS, MAX_VALUE, max_value_for


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


def test_estimator_and_encoder_agree_on_rejecting_out_of_range_input():
    """analyze is built entirely on the estimator. If the estimator accepts
    what encode_frame cannot physically produce, analyze prints a confident
    ratio for a bitstream that does not exist."""
    m = np.full((8, 8), 40000, dtype=np.uint16)
    with pytest.raises(ValueError):
        framecodec.encode_frame(m, "RGGB")
    with pytest.raises(ValueError):
        framecodec.estimate_frame_bits(m, "RGGB")


def test_max_value_itself_is_accepted():
    m = np.full((8, 8), MAX_VALUE, dtype=np.uint16)
    assert framecodec.estimate_frame_bits(m, "RGGB") > 0
    assert framecodec.encode_frame(m, "RGGB")


@pytest.mark.parametrize("bit_depth", [10, 12, 14])
@pytest.mark.parametrize("pattern", CFA_PATTERNS)
def test_roundtrip_all_bit_depths_and_patterns(bit_depth, pattern):
    """A mosaic with values in range for `bit_depth` round-trips exactly
    when encoded and decoded at that declared depth."""
    max_value = max_value_for(bit_depth)
    rng = np.random.default_rng(20260819)
    m = rng.integers(0, max_value + 1, size=(64, 96), dtype=np.uint16)
    payload = framecodec.encode_frame(m, pattern, bit_depth=bit_depth)
    decoded = framecodec.decode_frame(payload, *m.shape, pattern, bit_depth=bit_depth)
    assert np.array_equal(decoded, m)


def test_check_range_rejects_sample_above_declared_depth():
    m = np.full((8, 8), 1024, dtype=np.uint16)  # 1024 > 1023, the 10-bit max
    with pytest.raises(ValueError, match=r"\b10\b"):
        framecodec.encode_frame(m, "RGGB", bit_depth=10)


def test_check_range_message_names_the_declared_depth():
    m = np.full((8, 8), 5000, dtype=np.uint16)  # exceeds 12-bit max (4095)
    with pytest.raises(ValueError, match=r"\b12\b"):
        framecodec.estimate_frame_bits(m, "RGGB", bit_depth=12)


def test_10bit_valued_data_is_valid_at_default_depth_14():
    """Values in range at a shallower depth are always in range at a
    greater depth -- only the ceiling moves. Encoding 10-bit-valued data
    without specifying bit_depth (default 14) must succeed."""
    m = np.full((8, 8), max_value_for(10), dtype=np.uint16)
    payload = framecodec.encode_frame(m, "RGGB")
    assert np.array_equal(framecodec.decode_frame(payload, *m.shape, "RGGB"), m)
