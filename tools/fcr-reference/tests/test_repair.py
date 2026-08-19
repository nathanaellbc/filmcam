import numpy as np
import pytest

from conftest import build_header as _header
from fcrref import repair
from fcrref.constants import HEADER_SIZE
from fcrref.container import FcrReader, FcrWriter


def _write_clip(path, frame_count=6, seed=4):
    h = _header(width=32, height=24)
    rng = np.random.default_rng(seed)
    frames = [
        rng.integers(0, 16384, size=(h.height, h.width), dtype=np.uint16)
        for _ in range(frame_count)
    ]
    w = FcrWriter(str(path))
    w.write_header(h)
    for i, m in enumerate(frames):
        w.append_frame(m, i, i * 41_666_667, 20833333, 400, 0.5)
    w.finalize()
    return frames


def test_scan_finds_every_frame_in_a_complete_file(tmp_path):
    path = tmp_path / "clip.fcr"
    frames = _write_clip(path)
    assert len(repair.scan_frames(str(path))) == len(frames)


def test_repair_restores_readability_after_trailer_loss(tmp_path):
    path = tmp_path / "clip.fcr"
    frames = _write_clip(path)

    data = bytearray(path.read_bytes())
    del data[-12:]  # lose the trailer, as a crash would
    path.write_bytes(bytes(data))

    with pytest.raises(ValueError):
        FcrReader(str(path))

    recovered = repair.repair(str(path))
    assert recovered == len(frames)

    r = FcrReader(str(path))
    for i, expected in enumerate(frames):
        decoded, _ = r.read_frame(i)
        assert np.array_equal(decoded, expected)


@pytest.mark.parametrize("seed", range(50))
def test_truncation_never_yields_a_partial_frame(tmp_path, seed):
    """Spec 9: every complete frame recovers, no partial frame is returned."""
    path = tmp_path / f"clip_{seed}.fcr"
    frames = _write_clip(path, frame_count=8, seed=seed)
    full = bytearray(path.read_bytes())

    rng = np.random.default_rng(seed)
    cut = int(rng.integers(HEADER_SIZE, len(full)))
    path.write_bytes(bytes(full[:cut]))

    recovered = repair.repair(str(path))
    assert 0 <= recovered <= len(frames)

    if recovered:
        r = FcrReader(str(path))
        assert r.frame_count == recovered
        for i in range(recovered):
            decoded, _ = r.read_frame(i)
            assert np.array_equal(decoded, frames[i])


def test_repair_on_header_only_file_recovers_nothing(tmp_path):
    path = tmp_path / "clip.fcr"
    _write_clip(path)
    data = path.read_bytes()[:HEADER_SIZE]
    path.write_bytes(data)
    assert repair.repair(str(path)) == 0
