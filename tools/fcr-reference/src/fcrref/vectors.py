"""Conformance vector generation.

The Swift port in Stage M1 is correct when it reproduces every SHA-256
recorded here. Generation must be byte-identical across runs and
machines: no timestamps, no unseeded randomness.

The suite covers Stage W1 (container: header, writer, index, repair,
motion sidecar) and W2 (codec: predictor, Rice, frame payload), plus the
W3 source assets and the W5 scope ground truth those stages are asserted
against. Every artifact carries a `source` line in the manifest saying
exactly what produced it, because a Swift implementer holding only
`vectors/` has nothing else to go on.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os

import numpy as np

from . import patterns
from .bayer import PLANE_ORDER, split_planes
from .constants import (
    BIT_DEPTH,
    BLOCK_SIZE,
    CFA_PATTERNS,
    K_BITS,
    K_MAX,
    MAX_VALUE,
    RAW_BITS,
    RICE_LIMIT,
    max_value_for,
)
from .container import ClipHeader, FcrWriter, pack_header
from .framecodec import encode_frame
from .looks import cineon_to_rec709_lut, identity_lut, rec709_lut, write_cube
from .predictor import forward
from .repair import repair
from .rice import encode_plane
from .scopes import histogram, vectorscope, waveform
from .sidecar import FcmWriter, MotionSample

_GEOMETRY = (64, 96)  # small enough to commit, large enough to span blocks
_LUT_SIZE = 17        # not the module default of 33; the ports must match this
_NOISE_SEED = 20260819
_MOTION_SEED = 20260820
_EXTRA_DEPTHS = (10, 12)  # beyond BIT_DEPTH, so the port meets every depth

# Fixed clip metadata. Nothing here may be derived from the wall clock or
# the host: the committed SHA-256 is the deliverable.
_SIDECAR_HZ = 200
_SIDECAR_SAMPLES = 200
_SIDECAR_START_NS = 1_000_000_000
_SIDECAR_GAP_AT = 120
_SIDECAR_GAP_NS = 50_000_000

_FRAME_PTS_STEP_NS = 41_666_667
_FRAME_EXPOSURE_NS = 20_833_333
_FRAME_ISO = 400
_FRAME_LENS_POSITION = 0.5


def _reference_header(bit_depth: int = BIT_DEPTH, version: int = 1) -> ClipHeader:
    """A fully-populated header with every field distinct, so a port that
    mis-orders two fields of the same type cannot match the bytes.

    Every float is float32-exact, so the header round-trips to an equal
    dataclass and a port can compare values rather than tolerances. The
    white level follows `bit_depth` so the header is self-consistent at
    any depth; at the default the bytes are unchanged.

    `version` defaults to 1 because the committed clip vectors are version
    1 on disk and must stay byte-identical; the v2 audio vectors (Task 5)
    pass 2 explicitly.
    """
    height, width = _GEOMETRY
    white = max_value_for(bit_depth)
    return ClipHeader(
        width=width,
        height=height,
        bit_depth=bit_depth,
        cfa_pattern="RGGB",
        frame_rate_num=24000,
        frame_rate_den=1001,
        black_level=(64, 65, 66, 67),
        white_level=(white, white - 1, white - 2, white - 3),
        color_matrix1=tuple(float(i) / 8.0 for i in range(9)),
        color_matrix2=tuple(float(i) / 16.0 for i in range(9, 18)),
        as_shot_neutral=(0.5, 1.0, 0.75),
        lens_id="main",
        focal_length_35=24.0,
        aperture=1.75,  # float32-exact, like every other float here
        intrinsic_matrix=(1000.0, 0.0, 48.0, 0.0, 1000.0, 32.0, 0.0, 0.0, 1.0),
        readout_time_ns=16_000_000,
        ois_enabled=True,
        start_timecode="01:00:00:00",
        created_at_ns=1_755_561_600_000_000_000,  # fixed, never time.time()
        device_model="iPhone15,4",
        flags=0,
        version=version,
    )


def _rgb_proxy(mosaic: np.ndarray) -> np.ndarray:
    """Half-resolution RGB from an RGGB mosaic: R, mean(G1, G2), B, scaled
    to 0..1 by MAX_VALUE. The scopes take RGB, the sources are mosaics."""
    planes = split_planes(mosaic, "RGGB")
    green = (planes["G1"].astype(np.float64) + planes["G2"].astype(np.float64)) / 2.0
    stacked = np.stack(
        [planes["R"].astype(np.float64), green, planes["B"].astype(np.float64)],
        axis=-1,
    )
    return stacked / MAX_VALUE


def _motion_samples() -> list[MotionSample]:
    """Deterministic gyro/accel at 200 Hz with one deliberate stall, so a
    port's find_gaps has something with a known answer to run against."""
    step = 1_000_000_000 // _SIDECAR_HZ
    samples: list[MotionSample] = []
    t = _SIDECAR_START_NS
    for i in range(_SIDECAR_SAMPLES):
        if i == _SIDECAR_GAP_AT:
            t += _SIDECAR_GAP_NS  # the stall a real capture would drop
        samples.append(
            MotionSample(
                host_time_ns=t,
                gyro=(i / 1024.0, -i / 2048.0, i / 4096.0),
                accel=(i / 512.0, 9.8125, -i / 256.0),
            )
        )
        t += step
    return samples


class _Collector:
    """Accumulates artifact entries. Every entry must carry a `source`."""

    def __init__(self, out_dir: str) -> None:
        self.out_dir = out_dir
        self.entries: list[dict] = []

    def path(self, name: str) -> str:
        return os.path.join(self.out_dir, name)

    def add(self, name: str, data: bytes, source: str) -> None:
        self.entries.append(
            {
                "name": name,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "source": source,
            }
        )

    def write(self, name: str, data: bytes, source: str) -> None:
        with open(self.path(name), "wb") as fh:
            fh.write(data)
        self.add(name, data, source)

    def record(self, name: str, source: str) -> None:
        """Register a file some other writer already put in place."""
        with open(self.path(name), "rb") as fh:
            self.add(name, fh.read(), source)


def _previous_artifact_names(out_dir: str) -> set[str]:
    path = os.path.join(out_dir, "manifest.json")
    if not os.path.exists(path):
        return set()
    with open(path, encoding="utf-8") as fh:
        return {a["name"] for a in json.load(fh).get("artifacts", [])}


def _prune_orphans(out_dir: str, previous: set[str], current: set[str]) -> None:
    """Delete artifacts the *previous* manifest registered that this run no
    longer produces, so a renamed artifact cannot linger as an orphan and
    break the on-disk-set assertion in test_vectors.

    Scoped to names the old manifest listed, on purpose: the directory also
    holds .gitattributes, which is not an artifact and must survive.
    """
    for name in previous - current:
        target = os.path.join(out_dir, name)
        if os.path.isfile(target):
            os.remove(target)


def generate(out_dir: str) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    previous = _previous_artifact_names(out_dir)
    height, width = _GEOMETRY
    c = _Collector(out_dir)

    # 1. Raw source frames, so the Swift side starts from identical input.
    sources = {
        "hramp": patterns.horizontal_ramp(height, width),
        "vramp": patterns.vertical_ramp(height, width),
        "flat": patterns.flat(height, width, 4096),
        "noise": patterns.shot_noise(height, width, seed=_NOISE_SEED),
        "zone": patterns.zone_plate(height, width),
    }
    source_calls = {
        "hramp": f"patterns.horizontal_ramp({height}, {width})",
        "vramp": f"patterns.vertical_ramp({height}, {width})",
        "flat": f"patterns.flat({height}, {width}, 4096)",
        "noise": f"patterns.shot_noise({height}, {width}, seed={_NOISE_SEED})",
        "zone": f"patterns.zone_plate({height}, {width})",
    }
    for name, mosaic in sources.items():
        c.write(
            f"source_{name}.raw16",
            mosaic.astype("<u2").tobytes(),
            f"{source_calls[name]} as little-endian uint16, row-major",
        )

    # Spec W3 names colour bars and motion sequences in the asset set.
    bars = patterns.colour_bars(height, width, "RGGB")
    c.write(
        "source_bars.raw16",
        bars.astype("<u2").tobytes(),
        f'patterns.colour_bars({height}, {width}, "RGGB") as little-endian '
        "uint16, row-major",
    )

    motion_frames = patterns.motion_sequence(height, width, 3, seed=_MOTION_SEED)
    for n, mosaic in enumerate(motion_frames):
        c.write(
            f"source_motion_{n}.raw16",
            mosaic.astype("<u2").tobytes(),
            f"patterns.motion_sequence({height}, {width}, 3, "
            f"seed={_MOTION_SEED})[{n}] as little-endian uint16, row-major",
        )

    # 2. Single-plane Rice bitstreams, isolating the entropy coder.
    for name, mosaic in sources.items():
        residuals = forward(mosaic[0::2, 0::2])
        c.write(
            f"rice_{name}.bin",
            encode_plane(residuals),
            f"rice.encode_plane(predictor.forward(source_{name}[0::2, 0::2]))",
        )

    # 3. Full frame payloads across every CFA pattern and both strip modes.
    for pattern in CFA_PATTERNS:
        for strips in (1, 4):
            c.write(
                f"frame_{pattern.lower()}_s{strips}.fcrpayload",
                encode_frame(sources["noise"], pattern, strips=strips),
                f'framecodec.encode_frame(source_noise, "{pattern}", '
                f"strips={strips})",
            )

    # 4. Scope ground truth. Without this, Stage M1's Metal histogram,
    #    waveform and vectorscope have nothing to be asserted against.
    for name, mosaic in sources.items():
        proxy = mosaic.astype(np.float64) / MAX_VALUE
        c.write(
            f"scope_hist_{name}.i64",
            histogram(proxy).astype("<i8").tobytes(),
            f"scopes.histogram(source_{name} / {MAX_VALUE}), 256 bins, "
            "little-endian int64",
        )
        c.write(
            f"scope_wave_{name}.i64",
            waveform(proxy).astype("<i8").tobytes(),
            f"scopes.waveform(source_{name} / {MAX_VALUE}), 256 bins x "
            "width, little-endian int64, row-major",
        )
        c.write(
            f"scope_vector_{name}.i64",
            vectorscope(_rgb_proxy(mosaic)).astype("<i8").tobytes(),
            f"scopes.vectorscope(rgb_proxy(source_{name})) where rgb_proxy "
            'is split_planes(m, "RGGB") -> (R, mean(G1, G2), B) / '
            f"{MAX_VALUE}; 256x256 little-endian int64, row-major in "
            "(Cr, Cb)",
        )

    # 5. Container byte layout (Stage W1). This is the surface a Swift port
    #    is most likely to mis-order and currently cannot verify at all.
    header = _reference_header()
    c.write(
        "clip_header.bin",
        pack_header(header),
        "container.pack_header of the fixed reference ClipHeader: "
        f"{width}x{height} RGGB, {header.frame_rate_num}/"
        f"{header.frame_rate_den}, flags={header.flags}; "
        "4096 bytes, zero-padded",
    )

    clip_name = "clip_2frame.fcr"
    writer = FcrWriter(c.path(clip_name))
    writer.write_header(header)
    for i, key in enumerate(("noise", "zone")):
        writer.append_frame(
            sources[key],
            sequence=i,
            pts_ns=i * _FRAME_PTS_STEP_NS,
            exposure_ns=_FRAME_EXPOSURE_NS,
            iso=_FRAME_ISO,
            lens_position=_FRAME_LENS_POSITION,
        )
    writer.finalize()
    c.record(
        clip_name,
        "container.FcrWriter over the reference header then source_noise "
        "(sequence 0) and source_zone (sequence 1), pts step "
        f"{_FRAME_PTS_STEP_NS} ns, exposure {_FRAME_EXPOSURE_NS} ns, "
        f"iso {_FRAME_ISO}, lens_position {_FRAME_LENS_POSITION}, "
        "strips=1, then finalize()",
    )

    repaired_name = "clip_repaired.fcr"
    with open(c.path(clip_name), "rb") as fh:
        clip_bytes = fh.read()
    with open(c.path(repaired_name), "wb") as fh:
        fh.write(clip_bytes[:-12])  # lose the trailer, as a crash would
    repair(c.path(repaired_name))
    c.record(
        repaired_name,
        f"{clip_name} with its 12-byte trailer removed, then "
        "repair.repair() applied. Repair must reproduce the index and "
        f"trailer exactly, so this is byte-identical to {clip_name}",
    )

    sidecar_name = "motion.fcm"
    fcm = FcmWriter(c.path(sidecar_name))
    fcm.write_header(_SIDECAR_HZ)
    for sample in _motion_samples():
        fcm.append(sample)
    fcm.close()
    c.record(
        sidecar_name,
        f"sidecar.FcmWriter at {_SIDECAR_HZ} Hz, {_SIDECAR_SAMPLES} samples "
        f"from host_time_ns {_SIDECAR_START_NS}, gyro "
        "(i/1024, -i/2048, i/4096) and accel (i/512, 9.8125, -i/256) for "
        f"sample i, with one deliberate {_SIDECAR_GAP_NS} ns gap inserted "
        f"before sample {_SIDECAR_GAP_AT}",
    )

    # 6. LUTs, so the shader loads identical data.
    for name, lut in (
        ("identity", identity_lut(_LUT_SIZE)),
        ("rec709", rec709_lut(_LUT_SIZE)),
        ("cineon_rec709", cineon_to_rec709_lut(_LUT_SIZE)),
    ):
        lut_name = f"lut_{name}.cube"
        write_cube(c.path(lut_name), lut, name)
        c.record(
            lut_name,
            f"looks.write_cube(looks.{name}_lut({_LUT_SIZE}), "
            f'"{name}") — LUT_3D_SIZE {_LUT_SIZE}, not the module default '
            "of 33; 6 decimal places, red varies fastest, LF newlines",
        )

    # 7. Shallower depths, so the port meets every depth the container
    #    header can declare — not just the 14-bit default. RAW_BITS is
    #    fixed at 15 across all depths (D1), so the bitstream layout here
    #    differs from the 14-bit vectors only in the data it carries.
    for depth in _EXTRA_DEPTHS:
        depth_sources = {
            "noise": patterns.shot_noise(
                height, width, seed=_NOISE_SEED, bit_depth=depth
            ),
            "hramp": patterns.horizontal_ramp(height, width, bit_depth=depth),
        }
        for key, mosaic in depth_sources.items():
            c.write(
                f"source_{key}_d{depth}.raw16",
                mosaic.astype("<u2").tobytes(),
                f"{source_calls[key].rstrip(')')}, bit_depth={depth}) as "
                "little-endian uint16, row-major",
            )
        for pattern in CFA_PATTERNS:
            for strips in (1, 4):
                c.write(
                    f"frame_{pattern.lower()}_s{strips}_d{depth}.fcrpayload",
                    encode_frame(
                        depth_sources["noise"], pattern, strips=strips,
                        bit_depth=depth,
                    ),
                    f'framecodec.encode_frame(source_noise_d{depth}, '
                    f'"{pattern}", strips={strips}, bit_depth={depth})',
                )
        clip_name = f"clip_2frame_d{depth}.fcr"
        writer = FcrWriter(c.path(clip_name))
        writer.write_header(_reference_header(bit_depth=depth))
        for i, key in enumerate(("noise", "hramp")):
            writer.append_frame(
                depth_sources[key],
                sequence=i,
                pts_ns=i * _FRAME_PTS_STEP_NS,
                exposure_ns=_FRAME_EXPOSURE_NS,
                iso=_FRAME_ISO,
                lens_position=_FRAME_LENS_POSITION,
            )
        writer.finalize()
        c.record(
            clip_name,
            f"container.FcrWriter over the reference header at {depth}-bit "
            f"then source_noise_d{depth} (sequence 0) and "
            f"source_hramp_d{depth} (sequence 1), pts step "
            f"{_FRAME_PTS_STEP_NS} ns, exposure {_FRAME_EXPOSURE_NS} ns, "
            f"iso {_FRAME_ISO}, lens_position {_FRAME_LENS_POSITION}, "
            "strips=1, then finalize()",
        )

    manifest = {
        "version": 1,
        "geometry": {"height": height, "width": width},
        "constants": {
            "bit_depth": BIT_DEPTH,
            "supported_bit_depths": sorted({BIT_DEPTH, *_EXTRA_DEPTHS}),
            # D1: raw_bits is 15 at every supported depth, not depth + 1.
            # The Rice escape width never varies with the sample depth, so
            # a port has exactly one escape width to implement.
            "raw_bits": RAW_BITS,
            "rice_limit": RICE_LIMIT,
            "block_size": BLOCK_SIZE,
            "k_bits": K_BITS,
            # A port searching k over 0..14 instead of 0..15 produces
            # different bytes and fails every vector with no diagnostic.
            "k_max": K_MAX,
            "max_value": MAX_VALUE,
            "plane_order": list(PLANE_ORDER),
            "lut_size": _LUT_SIZE,
        },
        "artifacts": sorted(c.entries, key=lambda a: a["name"]),
    }

    with open(
        os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8", newline="\n"
    ) as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
        fh.write("\n")

    _prune_orphans(out_dir, previous, {a["name"] for a in manifest["artifacts"]})
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
