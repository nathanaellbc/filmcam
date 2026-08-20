import pytest

from fcrref.constants import BIT_DEPTH, MAX_VALUE, max_value_for


def test_bit_depth_and_max_value_defaults_unchanged():
    """BIT_DEPTH/MAX_VALUE are the defaults for callers that don't specify a depth."""
    assert BIT_DEPTH == 14
    assert MAX_VALUE == 16383


@pytest.mark.parametrize(
    "depth, expected",
    [
        (8, 255),
        (10, 1023),
        (12, 4095),
        (14, 16383),
    ],
)
def test_max_value_for_valid_depths(depth, expected):
    assert max_value_for(depth) == expected


@pytest.mark.parametrize("depth", [7, 15])
def test_max_value_for_rejects_out_of_range_depths(depth):
    with pytest.raises(ValueError):
        max_value_for(depth)
