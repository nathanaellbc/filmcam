import numpy as np
import pytest

from fcrref import analyze
from fcrref.constants import BIT_DEPTH


def test_raw_bits_counts_bit_depth_per_pixel():
    m = np.zeros((64, 64), dtype=np.uint16)
    stats = analyze.analyze_frame(m, "RGGB")
    assert stats.pixels == 64 * 64
    assert stats.raw_bits == 64 * 64 * BIT_DEPTH


def test_flat_frame_reports_very_high_ratio():
    """Ceiling is ~13.9:1 — one bit per sample plus block headers."""
    m = np.full((256, 256), 4000, dtype=np.uint16)
    assert analyze.analyze_frame(m, "RGGB").ratio > 12.0


def test_uniform_noise_reports_ratio_near_one():
    """Full-scale white noise is incompressible; ratio must not exceed ~1.1."""
    rng = np.random.default_rng(20260819)
    m = rng.integers(0, 16384, size=(256, 256), dtype=np.uint16)
    assert analyze.analyze_frame(m, "RGGB").ratio < 1.1


def test_per_plane_ratios_are_reported_for_all_four_planes():
    rng = np.random.default_rng(3)
    m = rng.integers(0, 16384, size=(64, 64), dtype=np.uint16)
    stats = analyze.analyze_frame(m, "RGGB")
    assert set(stats.per_plane_ratio) == {"R", "G1", "G2", "B"}


def test_realistic_sensor_noise_compresses_meaningfully():
    """Photon-noise-dominated image data — a smooth scene plus shot noise
    proportional to sqrt(signal), which is what a real sensor produces.

    This is a CHARACTERISATION test, not a spec check. Hand analysis puts
    this proxy near 1.6:1: at signal ~2000 the shot noise is ~45 DN, MED
    residuals run ~1.5x that, so the mean zigzag value is ~108, optimal
    k ~6, and the cost lands around 8.7 bits against 14.

    Do NOT relax or tighten this bound to make the spec's 2.2-2.6:1 target
    appear met. That number can only be settled by Task 7 Step 7, against
    real DNGs. See the warning in the Task 7 preamble.
    """
    rng = np.random.default_rng(11)
    y, x = np.mgrid[0:512, 0:512]
    signal = (2000 + 1500 * np.sin(x / 60.0) * np.cos(y / 80.0)).astype(np.float64)
    noisy = rng.poisson(np.clip(signal, 1.0, None)).clip(0, 16383).astype(np.uint16)
    ratio = analyze.analyze_frame(noisy, "RGGB").ratio
    assert 1.2 < ratio < 3.0


def test_load_raw16_reads_little_endian_pairs(tmp_path):
    src = np.arange(24, dtype=np.uint16).reshape(4, 6)
    path = tmp_path / "frame.raw16"
    path.write_bytes(src.astype("<u2").tobytes())
    assert np.array_equal(analyze.load_raw16(str(path), 4, 6), src)


def test_raw_bits_honours_a_twelve_bit_source():
    """A 12-bit DNG must not be scored against a 14-bit baseline: that
    inflates every ratio by 14/12 in the optimistic direction."""
    m = np.zeros((64, 64), dtype=np.uint16)
    stats = analyze.analyze_frame(m, "RGGB", bit_depth=12)
    assert stats.bit_depth == 12
    assert stats.raw_bits == 64 * 64 * 12
    assert stats.raw_bits < analyze.analyze_frame(m, "RGGB").raw_bits


def test_per_plane_ratios_also_honour_the_bit_depth():
    rng = np.random.default_rng(7)
    m = rng.integers(0, 4096, size=(64, 64), dtype=np.uint16)
    at14 = analyze.analyze_frame(m, "RGGB")
    at12 = analyze.analyze_frame(m, "RGGB", bit_depth=12)
    for name in at12.per_plane_ratio:
        assert at12.per_plane_ratio[name] == pytest.approx(
            at14.per_plane_ratio[name] * 12 / 14
        )


def test_bit_depth_is_derived_from_the_white_level():
    assert analyze._bit_depth_from_white_level(16383) == 14
    assert analyze._bit_depth_from_white_level(4095) == 12
    assert analyze._bit_depth_from_white_level(1023) == 10
    assert analyze._bit_depth_from_white_level([4095, 4095, 4095, 4095]) == 12


def test_bit_depth_falls_back_when_the_file_says_nothing_usable():
    assert analyze._bit_depth_from_white_level(0) == BIT_DEPTH
    assert analyze._bit_depth_from_white_level(None) == BIT_DEPTH


def test_colour_descriptor_is_read_from_the_file_not_assumed():
    class Raw:
        color_desc = b"RGBG"

    class Odd:
        color_desc = b"GRBG"

    class Silent:
        color_desc = None

    assert analyze._color_desc(Raw()) == "RGBG"
    assert analyze._color_desc(Odd()) == "GRBG"
    assert analyze._color_desc(Silent()) == "RGBG"


def test_report_prints_the_bit_depth(capsys):
    m = np.zeros((8, 8), dtype=np.uint16)
    analyze._report(["fake.dng"], lambda _p: (m, "RGGB", 12), None)
    out = capsys.readouterr().out
    assert "12-bit" in out


def test_report_rejects_out_of_range_samples_instead_of_reporting_a_ratio():
    """The estimator must not print a confident ratio for a bitstream the
    encoder cannot produce."""
    m = np.full((8, 8), 40000, dtype=np.uint16)
    with pytest.raises(ValueError):
        analyze.analyze_frame(m, "RGGB")
