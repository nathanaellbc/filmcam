"""The .fcm motion sidecar: append-only gyro and accelerometer records.

Written separately from the video container so a crash preserves it
independently. Gaps are reported, never interpolated (spec 5.5).

Layout (little-endian):
    "FCM1"  u16 version  u16 sample_rate_hz   (8 bytes)
    then repeated 32-byte records:
        u64 host_time_ns
        f32 gyro_x, gyro_y, gyro_z
        f32 accel_x, accel_y, accel_z
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .constants import SIDECAR_MAGIC

_HEADER_FMT = "<4sHH"
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)
_RECORD_FMT = "<Q6f"
_RECORD_SIZE = struct.calcsize(_RECORD_FMT)


@dataclass(frozen=True)
class MotionSample:
    host_time_ns: int
    gyro: tuple[float, float, float]
    accel: tuple[float, float, float]


class FcmWriter:
    def __init__(self, path: str) -> None:
        self._file = open(path, "wb")

    def write_header(self, sample_rate_hz: int) -> None:
        self._file.write(struct.pack(_HEADER_FMT, SIDECAR_MAGIC, 1, sample_rate_hz))

    def append(self, sample: MotionSample) -> None:
        self._file.write(
            struct.pack(_RECORD_FMT, sample.host_time_ns, *sample.gyro, *sample.accel)
        )

    def close(self) -> None:
        self._file.close()


def read_sidecar(path: str) -> tuple[int, list[MotionSample]]:
    with open(path, "rb") as fh:
        data = fh.read()

    magic, _version, rate = struct.unpack_from(_HEADER_FMT, data, 0)
    if magic != SIDECAR_MAGIC:
        raise ValueError(f"bad sidecar magic {magic!r}")

    samples: list[MotionSample] = []
    offset = _HEADER_SIZE
    while offset + _RECORD_SIZE <= len(data):
        values = struct.unpack_from(_RECORD_FMT, data, offset)
        samples.append(
            MotionSample(
                host_time_ns=values[0],
                gyro=(values[1], values[2], values[3]),
                accel=(values[4], values[5], values[6]),
            )
        )
        offset += _RECORD_SIZE

    return rate, samples


def find_gaps(
    samples: list[MotionSample], expected_hz: int, tolerance: float = 2.0
) -> list[tuple[int, int]]:
    """Return (start_ns, end_ns) spans where the interval exceeded
    `tolerance` times the nominal sample period."""
    if len(samples) < 2:
        return []
    nominal = 1e9 / expected_hz
    threshold = nominal * tolerance
    gaps: list[tuple[int, int]] = []
    for previous, current in zip(samples, samples[1:]):
        if current.host_time_ns - previous.host_time_ns > threshold:
            gaps.append((previous.host_time_ns, current.host_time_ns))
    return gaps
