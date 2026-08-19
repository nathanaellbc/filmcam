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


def test_roundtrip_extremes_forces_escape_path():
    res = np.array([[16383, -16383, 0, 16383]], dtype=np.int32)
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
