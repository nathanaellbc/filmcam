import numpy as np

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
