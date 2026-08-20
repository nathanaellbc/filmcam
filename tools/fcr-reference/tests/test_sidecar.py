import pytest

from fcrref.constants import SIDECAR_MAGIC
from fcrref.sidecar import FcmWriter, MotionSample, find_gaps, read_sidecar


def _samples(count, hz=200, start=0):
    step = int(1e9 / hz)
    return [
        MotionSample(
            host_time_ns=start + i * step,
            gyro=(0.1 * i, -0.2 * i, 0.3 * i),
            accel=(0.0, 9.81, 0.0),
        )
        for i in range(count)
    ]


def test_file_starts_with_magic(tmp_path):
    path = tmp_path / "clip.fcm"
    w = FcmWriter(str(path))
    w.write_header(200)
    w.close()
    assert path.read_bytes()[:4] == SIDECAR_MAGIC


def test_roundtrip_preserves_samples(tmp_path):
    path = tmp_path / "clip.fcm"
    samples = _samples(500)
    w = FcmWriter(str(path))
    w.write_header(200)
    for s in samples:
        w.append(s)
    w.close()

    rate, loaded = read_sidecar(str(path))
    assert rate == 200
    assert len(loaded) == len(samples)
    for a, b in zip(samples, loaded):
        assert a.host_time_ns == b.host_time_ns
        assert a.gyro == pytest.approx(b.gyro)
        assert a.accel == pytest.approx(b.accel)


def test_truncated_sidecar_reads_all_complete_samples(tmp_path):
    path = tmp_path / "clip.fcm"
    w = FcmWriter(str(path))
    w.write_header(200)
    for s in _samples(100):
        w.append(s)
    w.close()

    data = bytearray(path.read_bytes())
    del data[-10:]  # a partial final record
    path.write_bytes(bytes(data))

    _rate, loaded = read_sidecar(str(path))
    assert len(loaded) == 99


def test_find_gaps_returns_empty_for_regular_sampling():
    assert find_gaps(_samples(400), expected_hz=200) == []


def test_find_gaps_detects_a_stall():
    head = _samples(100)
    tail = _samples(100, start=head[-1].host_time_ns + 50_000_000)  # 50 ms hole
    gaps = find_gaps(head + tail, expected_hz=200)
    assert len(gaps) == 1
    assert gaps[0] == (head[-1].host_time_ns, tail[0].host_time_ns)


def test_find_gaps_requires_at_least_two_samples():
    assert find_gaps(_samples(1), expected_hz=200) == []


def test_append_before_write_header_is_refused(tmp_path):
    """FcrWriter.append_frame already guards this exact case; the
    asymmetry was the defect. A record written ahead of the 8-byte header
    silently shifts every sample by 8 bytes on read."""
    w = FcmWriter(str(tmp_path / "clip.fcm"))
    try:
        with pytest.raises(RuntimeError):
            w.append(_samples(1)[0])
    finally:
        w.close()


def test_append_is_allowed_once_the_header_is_written(tmp_path):
    path = tmp_path / "clip.fcm"
    w = FcmWriter(str(path))
    w.write_header(200)
    w.append(_samples(1)[0])
    w.close()
    _rate, loaded = read_sidecar(str(path))
    assert len(loaded) == 1
