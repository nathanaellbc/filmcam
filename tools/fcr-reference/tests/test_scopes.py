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
