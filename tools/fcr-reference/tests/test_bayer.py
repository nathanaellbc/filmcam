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
