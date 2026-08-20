import numpy as np
import pytest

from fcrref.container import ClipHeader


def build_header(width: int = 64, height: int = 48) -> ClipHeader:
    """A valid header. All float fields are float32-exact on purpose."""
    return ClipHeader(
        width=width,
        height=height,
        bit_depth=14,
        cfa_pattern="RGGB",
        frame_rate_num=24000,
        frame_rate_den=1000,
        black_level=(64, 64, 64, 64),
        white_level=(16383, 16383, 16383, 16383),
        color_matrix1=tuple(float(i) for i in range(9)),
        color_matrix2=tuple(float(i) for i in range(100, 109)),
        as_shot_neutral=(0.5, 1.0, 0.75),
        lens_id="main",
        focal_length_35=24.0,
        aperture=1.5,
        intrinsic_matrix=(1000.0, 0.0, 32.0, 0.0, 1000.0, 24.0, 0.0, 0.0, 1.0),
        readout_time_ns=16_000_000,
        ois_enabled=False,
        start_timecode="01:00:00:00",
        created_at_ns=0,
        device_model="iPhone15,4",
    )


def build_frame(header: ClipHeader, seed: int = 1) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(
        0, 16384, size=(header.height, header.width), dtype=np.uint16
    )


@pytest.fixture
def make_header():
    return build_header


@pytest.fixture
def make_frame():
    return build_frame
