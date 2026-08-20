import json

from fcrref import vectors


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
