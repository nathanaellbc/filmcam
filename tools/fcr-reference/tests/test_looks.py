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
