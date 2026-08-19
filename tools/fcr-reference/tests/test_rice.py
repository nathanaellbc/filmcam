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
