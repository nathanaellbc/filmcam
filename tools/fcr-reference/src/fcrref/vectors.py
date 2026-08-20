"""Conformance vector generation.

The Swift port in Stage M1 is correct when it reproduces every SHA-256
recorded here. Generation must be byte-identical across runs and
machines: no timestamps, no unseeded randomness.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os

import numpy as np

from . import patterns
from .constants import (
    BIT_DEPTH,
    BLOCK_SIZE,
    CFA_PATTERNS,
    K_BITS,
    MAX_VALUE,
    RAW_BITS,
    RICE_LIMIT,
)
from .framecodec import encode_frame
from .looks import cineon_to_rec709_lut, identity_lut, rec709_lut, write_cube
from .predictor import forward
from .rice import encode_plane
from .scopes import histogram, waveform

_GEOMETRY = (64, 96)  # small enough to commit, large enough to span blocks


def _write(out_dir: str, name: str, data: bytes) -> dict:
    with open(os.path.join(out_dir, name), "wb") as fh:
        fh.write(data)
    return {
        "name": name,
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def generate(out_dir: str) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    height, width = _GEOMETRY
    artifacts: list[dict] = []

    # 1. Raw source frames, so the Swift side starts from identical input.
    sources = {
        "hramp": patterns.horizontal_ramp(height, width),
        "vramp": patterns.vertical_ramp(height, width),
        "flat": patterns.flat(height, width, 4096),
        "noise": patterns.shot_noise(height, width, seed=20260819),
        "zone": patterns.zone_plate(height, width),
    }
    for name, mosaic in sources.items():
        artifacts.append(
            _write(out_dir, f"source_{name}.raw16", mosaic.astype("<u2").tobytes())
        )

    # 2. Single-plane Rice bitstreams, isolating the entropy coder.
    for name, mosaic in sources.items():
        residuals = forward(mosaic[0::2, 0::2])
        artifacts.append(
            _write(out_dir, f"rice_{name}.bin", encode_plane(residuals))
        )

    # 3. Full frame payloads across every CFA pattern and both strip modes.
    for pattern in CFA_PATTERNS:
        for strips in (1, 4):
            payload = encode_frame(sources["noise"], pattern, strips=strips)
            artifacts.append(
                _write(
                    out_dir,
                    f"frame_{pattern.lower()}_s{strips}.fcrpayload",
                    payload,
                )
            )

    # 4. Scope ground truth. Without this, Stage M1's Metal histogram and
    #    waveform have nothing to be asserted against.
    for name, mosaic in sources.items():
        proxy = mosaic.astype(np.float64) / MAX_VALUE
        artifacts.append(
            _write(
                out_dir,
                f"scope_hist_{name}.i64",
                histogram(proxy).astype("<i8").tobytes(),
            )
        )
        artifacts.append(
            _write(
                out_dir,
                f"scope_wave_{name}.i64",
                waveform(proxy).astype("<i8").tobytes(),
            )
        )

    # 5. LUTs, so the shader loads identical data.
    for name, lut in (
        ("identity", identity_lut(17)),
        ("rec709", rec709_lut(17)),
        ("cineon_rec709", cineon_to_rec709_lut(17)),
    ):
        path = os.path.join(out_dir, f"lut_{name}.cube")
        write_cube(path, lut, name)
        with open(path, "rb") as fh:
            data = fh.read()
        artifacts.append(
            {
                "name": f"lut_{name}.cube",
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )

    manifest = {
        "version": 1,
        "geometry": {"height": height, "width": width},
        "constants": {
            "bit_depth": BIT_DEPTH,
            "raw_bits": RAW_BITS,
            "rice_limit": RICE_LIMIT,
            "block_size": BLOCK_SIZE,
            "k_bits": K_BITS,
        },
        "artifacts": sorted(artifacts, key=lambda a: a["name"]),
    }

    with open(
        os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8", newline="\n"
    ) as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
        fh.write("\n")

    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate conformance vectors")
    parser.add_argument("--out", default="vectors", help="output directory")
    args = parser.parse_args(argv)
    manifest = generate(args.out)
    print(f"wrote {len(manifest['artifacts'])} artifacts to {args.out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
