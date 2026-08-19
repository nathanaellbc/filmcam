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
