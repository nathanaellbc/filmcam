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


def test_roundtrip_large_magnitude_values():
    """Large-magnitude values on the normal (non-escape) Rice path.

    NOTE: despite what an earlier name for this test claimed, these values
    do NOT force the escape path — with only 4 samples, choose_k picks a
    large k (14) that keeps q small (q in {0, 1}) for all of them. See
    test_roundtrip_forces_true_escape_path for actual escape-path coverage.
    """
    res = np.array([[16383, -16383, 0, 16383]], dtype=np.int32)
    data = rice.encode_plane(res)
    assert np.array_equal(rice.decode_plane(data, res.shape), res)


def test_roundtrip_forces_true_escape_path():
    """A mostly-zero block with a rare large outlier makes k=0 optimal,
    which makes the outlier's q >= RICE_LIMIT and genuinely triggers the
    escape path (RICE_LIMIT zero bits + terminator + RAW_BITS raw value).

    This reproduces the encode/decode desync found in review: the decoder
    must consume the escape terminator bit that read_unary(RICE_LIMIT)
    leaves unconsumed, or every value after the first escape in the block
    decodes as garbage.
    """
    res = np.zeros((1, BLOCK_SIZE), dtype=np.int32)
    res[0, 0] = 16000
    res[0, 100] = 5
    res[0, 200] = -3
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
