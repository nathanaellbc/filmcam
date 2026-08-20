import numpy as np

from fcrref import patterns
from fcrref.constants import MAX_VALUE


def test_horizontal_ramp_increases_left_to_right():
    m = patterns.horizontal_ramp(32, 64)
    assert m[0, 0] == 0
    assert m[0, -1] == MAX_VALUE
    assert np.all(np.diff(m[0].astype(np.int32)) >= 0)


def test_horizontal_ramp_is_constant_down_each_column():
    m = patterns.horizontal_ramp(32, 64)
    assert np.all(m == m[0][None, :])


def test_vertical_ramp_is_constant_across_each_row():
    m = patterns.vertical_ramp(32, 64)
    assert np.all(m == m[:, 0][:, None])


def test_flat_returns_requested_value():
    m = patterns.flat(16, 16, 1234)
    assert np.all(m == 1234)


def test_colour_bars_has_expected_distinct_columns():
    m = patterns.colour_bars(64, 64, "RGGB")
    assert len(np.unique(m[0])) > 1


def test_shot_noise_is_deterministic_for_a_seed():
    a = patterns.shot_noise(64, 64, seed=7)
    b = patterns.shot_noise(64, 64, seed=7)
    assert np.array_equal(a, b)


def test_shot_noise_differs_between_seeds():
    a = patterns.shot_noise(64, 64, seed=7)
    b = patterns.shot_noise(64, 64, seed=8)
    assert not np.array_equal(a, b)


def test_all_patterns_stay_in_range():
    for m in (
        patterns.horizontal_ramp(40, 40),
        patterns.vertical_ramp(40, 40),
        patterns.colour_bars(40, 40, "RGGB"),
        patterns.shot_noise(40, 40, seed=1),
        patterns.zone_plate(40, 40),
    ):
        assert m.dtype == np.uint16
        assert m.min() >= 0
        assert m.max() <= MAX_VALUE


def test_motion_sequence_returns_requested_frame_count():
    frames = patterns.motion_sequence(32, 32, frames=5, seed=2)
    assert len(frames) == 5


def test_motion_sequence_frames_differ():
    frames = patterns.motion_sequence(32, 32, frames=3, seed=2)
    assert not np.array_equal(frames[0], frames[1])


def test_motion_sequence_is_deterministic():
    a = patterns.motion_sequence(32, 32, frames=3, seed=2)
    b = patterns.motion_sequence(32, 32, frames=3, seed=2)
    assert all(np.array_equal(x, y) for x, y in zip(a, b))
