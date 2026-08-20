import json

import numpy as np

from fcrref import vectors
from fcrref.constants import HEADER_SIZE
from fcrref.container import FcrReader, unpack_header
from fcrref.sidecar import find_gaps, read_sidecar


def test_generate_writes_a_manifest(tmp_path):
    manifest = vectors.generate(str(tmp_path))
    path = tmp_path / "manifest.json"
    assert path.exists()
    assert json.loads(path.read_text()) == manifest


def test_manifest_records_a_sha256_per_artifact(tmp_path):
    manifest = vectors.generate(str(tmp_path))
    assert manifest["artifacts"]
    for entry in manifest["artifacts"]:
        assert len(entry["sha256"]) == 64
        assert (tmp_path / entry["name"]).exists()


def test_manifest_pins_the_format_constants(tmp_path):
    manifest = vectors.generate(str(tmp_path))
    constants = manifest["constants"]
    assert constants["bit_depth"] == 14
    assert constants["rice_limit"] == 24
    assert constants["block_size"] == 512
    assert constants["raw_bits"] == 15


def test_generation_is_byte_identical_across_runs(tmp_path):
    first = tmp_path / "a"
    second = tmp_path / "b"
    first.mkdir()
    second.mkdir()
    manifest_a = vectors.generate(str(first))
    manifest_b = vectors.generate(str(second))
    assert manifest_a == manifest_b
    for entry in manifest_a["artifacts"]:
        assert (first / entry["name"]).read_bytes() == (second / entry["name"]).read_bytes()


def test_vectors_cover_every_cfa_pattern(tmp_path):
    manifest = vectors.generate(str(tmp_path))
    names = " ".join(e["name"] for e in manifest["artifacts"])
    for pattern in ("RGGB", "BGGR", "GRBG", "GBRG"):
        assert pattern.lower() in names


def test_vectors_include_scope_ground_truth(tmp_path):
    """Stage M1's Metal scopes are asserted against these."""
    manifest = vectors.generate(str(tmp_path))
    names = {e["name"] for e in manifest["artifacts"]}
    for source in ("hramp", "vramp", "flat", "noise", "zone"):
        assert f"scope_hist_{source}.i64" in names
        assert f"scope_wave_{source}.i64" in names


def test_manifest_pins_k_max_and_plane_order(tmp_path):
    """A port searching k over 0..14 instead of 0..15 produces different
    bytes and fails every vector with no diagnostic."""
    constants = vectors.generate(str(tmp_path))["constants"]
    assert constants["k_max"] == 15
    assert constants["k_bits"] == 4
    assert constants["plane_order"] == ["R", "G1", "G2", "B"]
    assert constants["max_value"] == 16383
    assert constants["lut_size"] == 17


def test_every_artifact_says_what_produced_it(tmp_path):
    """A Swift implementer holding only vectors/ must be able to tell that
    frame_rggb_s1.fcrpayload came from the noise source."""
    manifest = vectors.generate(str(tmp_path))
    for entry in manifest["artifacts"]:
        assert entry["source"].strip(), entry["name"]
    by_name = {e["name"]: e["source"] for e in manifest["artifacts"]}
    assert "source_noise" in by_name["frame_rggb_s1.fcrpayload"]
    assert "17" in by_name["lut_identity.cube"]


def test_vectors_cover_the_container_byte_layout(tmp_path):
    """Stage W6 says the suite covers W1-W2. W1 is the container."""
    names = {e["name"] for e in vectors.generate(str(tmp_path))["artifacts"]}
    for name in ("clip_header.bin", "clip_2frame.fcr", "clip_repaired.fcr",
                 "motion.fcm"):
        assert name in names


def test_clip_header_vector_is_a_full_4096_byte_header(tmp_path):
    vectors.generate(str(tmp_path))
    data = (tmp_path / "clip_header.bin").read_bytes()
    assert len(data) == HEADER_SIZE
    assert unpack_header(data) == vectors._reference_header()


def test_clip_vector_reads_back_as_the_frames_that_went_in(tmp_path):
    vectors.generate(str(tmp_path))
    reader = FcrReader(str(tmp_path / "clip_2frame.fcr"))
    assert reader.frame_count == 2
    assert reader.header == vectors._reference_header()

    height, width = vectors._GEOMETRY
    expected = [
        np.frombuffer((tmp_path / f"source_{n}.raw16").read_bytes(), dtype="<u2")
        .reshape(height, width)
        for n in ("noise", "zone")
    ]
    for i, want in enumerate(expected):
        decoded, meta = reader.read_frame(i)
        assert np.array_equal(decoded, want)
        assert meta.sequence == i


def test_repaired_clip_vector_reproduces_the_original_bytes(tmp_path):
    """repair() must rebuild the index and trailer exactly, so a clip that
    lost only its trailer comes back byte-identical. That invariant is the
    point of the vector."""
    vectors.generate(str(tmp_path))
    assert ((tmp_path / "clip_repaired.fcr").read_bytes()
            == (tmp_path / "clip_2frame.fcr").read_bytes())


def test_motion_vector_has_the_documented_rate_and_one_gap(tmp_path):
    vectors.generate(str(tmp_path))
    rate, samples = read_sidecar(str(tmp_path / "motion.fcm"))
    assert rate == 200
    assert len(samples) == 200
    assert len(find_gaps(samples, expected_hz=rate)) == 1


def test_vectors_include_the_w3_source_assets(tmp_path):
    """Spec W3 names colour bars and motion sequences in the asset set."""
    names = {e["name"] for e in vectors.generate(str(tmp_path))["artifacts"]}
    assert "source_bars.raw16" in names
    assert {"source_motion_0.raw16", "source_motion_1.raw16",
            "source_motion_2.raw16"} <= names


def test_vectors_include_vectorscope_ground_truth(tmp_path):
    """Spec W5 names the vectorscope; it was implemented but never emitted."""
    names = {e["name"] for e in vectors.generate(str(tmp_path))["artifacts"]}
    for source in ("hramp", "vramp", "flat", "noise", "zone"):
        assert f"scope_vector_{source}.i64" in names
    data = np.frombuffer(
        (tmp_path / "scope_vector_flat.i64").read_bytes(), dtype="<i8"
    )
    assert data.size == 256 * 256
