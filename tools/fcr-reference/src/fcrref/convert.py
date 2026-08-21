"""DNG sequence -> .fcr conversion.

A development tool: it reuses the real container writer and codec to turn a
folder of DNGs into a valid `.fcr` clip, then optionally reads the clip back
and asserts every frame is bit-identical to its source.

This is a reference path, not a production one. Encoding is per-sample
Python, so a 12 MP frame takes minutes. Use it to prove the format on real
footage and to produce small known-good clips, not to convert whole takes —
that is what the Swift port is for.
"""

from __future__ import annotations

import argparse
import glob
import sys
import time

import numpy as np

from .analyze import load_dng
from .constants import AUDIO_CHUNK_NS, SAMPLE_FORMAT_S16LE
from .container import ClipHeader, FcrReader, FcrWriter


def load_wav(path: str) -> tuple[bytes, int, int, int]:
    """Read a PCM WAV into (payload, sample_rate_hz, channel_count, format).

    Only uncompressed PCM is supported, and only the sample widths the
    container carries: 16-bit (s16le) and 32-bit float is not produced by
    the stdlib wave reader, so 16-bit is the practical path here.
    """
    import wave

    with wave.open(path, "rb") as f:
        channels = f.getnchannels()
        sampwidth = f.getsampwidth()
        rate = f.getframerate()
        if sampwidth != 2:
            raise ValueError(
                f"{path}: only 16-bit PCM WAV is supported, got "
                f"{sampwidth * 8}-bit"
            )
        payload = f.readframes(f.getnframes())
    return payload, rate, channels, SAMPLE_FORMAT_S16LE


def build_clip_header(
    width: int,
    height: int,
    bit_depth: int,
    cfa_pattern: str,
    frame_rate_num: int,
    frame_rate_den: int,
    version: int = 1,
) -> ClipHeader:
    """A valid header for a converted clip.

    Fields the DNGs do not tell us (lens identity, intrinsics, readout
    time, ...) are left at neutral defaults. They matter to a real capture,
    not to proving a converted sequence round-trips.
    """
    white = (1 << bit_depth) - 1
    return ClipHeader(
        width=width,
        height=height,
        bit_depth=bit_depth,
        cfa_pattern=cfa_pattern,
        frame_rate_num=frame_rate_num,
        frame_rate_den=frame_rate_den,
        black_level=(0, 0, 0, 0),
        white_level=(white, white, white, white),
        color_matrix1=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
        color_matrix2=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
        as_shot_neutral=(1.0, 1.0, 1.0),
        lens_id="unknown",
        focal_length_35=0.0,
        aperture=0.0,
        intrinsic_matrix=(0.0,) * 9,
        readout_time_ns=0,
        ois_enabled=False,
        start_timecode="00:00:00:00",
        created_at_ns=0,
        device_model="unknown",
        version=version,
    )


def convert(
    paths: list[str],
    out_path: str,
    frame_rate_num: int = 24,
    frame_rate_den: int = 1,
    strips: int = 1,
    pattern_override: str | None = None,
    verify: bool = True,
    audio_path: str | None = None,
) -> int:
    """Write `paths` to `out_path` as a .fcr clip. Returns the frame count.

    When `audio_path` is given, the clip is written at container version 2
    and the WAV's PCM is embedded as AUD0 chunks interleaved between the
    frame records, with the first chunk's pts aligned to frame 0.
    """
    if not paths:
        print("no input files", file=sys.stderr)
        return 0

    audio: tuple[bytes, int, int, int] | None = None
    if audio_path is not None:
        audio = load_wav(audio_path)

    writer: FcrWriter | None = None
    header: ClipHeader | None = None
    written = 0
    t0 = time.perf_counter()

    for sequence, path in enumerate(paths):
        mosaic, pattern, bit_depth = load_dng(path)
        pattern = pattern_override or pattern

        if header is None:
            header = build_clip_header(
                mosaic.shape[1], mosaic.shape[0], bit_depth, pattern,
                frame_rate_num, frame_rate_den,
                version=2 if audio is not None else 1,
            )
            writer = FcrWriter(out_path)
            writer.write_header(header)
            print(
                f"clip: {header.width}x{header.height} {pattern} "
                f"{bit_depth}-bit v{header.version} -> {out_path}"
            )
        else:
            if (mosaic.shape[1], mosaic.shape[0]) != (header.width, header.height):
                raise ValueError(
                    f"{path}: geometry {mosaic.shape[1]}x{mosaic.shape[0]} "
                    f"does not match the clip's {header.width}x{header.height}"
                )
            if pattern != header.cfa_pattern:
                raise ValueError(
                    f"{path}: CFA pattern {pattern} does not match the "
                    f"clip's {header.cfa_pattern}"
                )
            if bit_depth != header.bit_depth:
                raise ValueError(
                    f"{path}: bit depth {bit_depth} does not match the "
                    f"clip's {header.bit_depth}"
                )

        assert writer is not None
        frame_start = time.perf_counter()
        frame_pts = sequence * (1_000_000_000 * frame_rate_den // frame_rate_num)
        writer.append_frame(
            mosaic,
            sequence=sequence,
            pts_ns=frame_pts,
            exposure_ns=0,
            iso=0,
            lens_position=0.0,
            strips=strips,
        )
        written += 1

        # Interleave audio: after each frame, flush every 0.5 s audio chunk
        # whose start time has now passed. Chunk pts is on the same clock as
        # frame pts, with chunk 0 aligned to frame 0.
        if audio is not None:
            payload, rate, channels, sample_format = audio
            bytes_per_frame = 2 * channels  # s16le
            chunk_frames = rate * AUDIO_CHUNK_NS // 1_000_000_000
            while True:
                chunk_index = len(writer._audio_index)
                chunk_pts = chunk_index * AUDIO_CHUNK_NS
                if chunk_pts > frame_pts:
                    break
                start = chunk_index * chunk_frames * bytes_per_frame
                if start >= len(payload):
                    break
                chunk = payload[start:start + chunk_frames * bytes_per_frame]
                if not chunk:
                    break
                writer.append_audio(
                    chunk,
                    pts_ns=chunk_pts,
                    sample_rate_hz=rate,
                    channel_count=channels,
                    sample_format=sample_format,
                )

        elapsed = time.perf_counter() - frame_start
        print(f"  frame {sequence:3d}  {elapsed:6.1f}s  {path}", flush=True)

    # Flush any audio that runs past the last frame.
    if audio is not None:
        assert writer is not None
        payload, rate, channels, sample_format = audio
        bytes_per_frame = 2 * channels
        chunk_frames = rate * AUDIO_CHUNK_NS // 1_000_000_000
        while True:
            chunk_index = len(writer._audio_index)
            start = chunk_index * chunk_frames * bytes_per_frame
            if start >= len(payload):
                break
            chunk = payload[start:start + chunk_frames * bytes_per_frame]
            if not chunk:
                break
            writer.append_audio(
                chunk,
                pts_ns=chunk_index * AUDIO_CHUNK_NS,
                sample_rate_hz=rate,
                channel_count=channels,
                sample_format=sample_format,
            )

    assert writer is not None
    writer.finalize()
    total = time.perf_counter() - t0
    print(f"wrote {written} frames in {total:.1f}s")

    if verify and header is not None:
        print("verifying round-trip...", flush=True)
        reader = FcrReader(out_path)
        if reader.frame_count != written:
            raise AssertionError(
                f"clip holds {reader.frame_count} frames, wrote {written}"
            )
        for i, path in enumerate(paths):
            mosaic, _, _ = load_dng(path)
            decoded, meta = reader.read_frame(i)
            if meta.sequence != i:
                raise AssertionError(f"frame {i}: sequence is {meta.sequence}")
            if not np.array_equal(decoded, mosaic):
                raise AssertionError(f"frame {i} does not round-trip: {path}")
        print(f"verified: all {written} frames bit-identical")

    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Convert a DNG sequence to a .fcr clip (reference path)"
    )
    parser.add_argument("--input", required=True, help="DNG file glob")
    parser.add_argument("--out", required=True, help="output .fcr path")
    parser.add_argument(
        "--fps",
        default="24/1",
        help="frame rate as N/D (default 24/1)",
    )
    parser.add_argument(
        "--strips", type=int, default=1, help="encode strips per frame"
    )
    parser.add_argument(
        "--pattern", default=None, help="override the CFA pattern"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="convert at most N frames"
    )
    parser.add_argument(
        "--audio",
        default=None,
        metavar="WAV",
        help="embed a PCM WAV as AUD0 audio chunks (container version 2); "
             "the first chunk is aligned to frame 0",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="skip the bit-identical round-trip check",
    )
    args = parser.parse_args(argv)

    paths = sorted(glob.glob(args.input))
    if args.limit is not None:
        paths = paths[: args.limit]
    if not paths:
        print(f"no files matched {args.input!r}", file=sys.stderr)
        return 1

    num, _, den = args.fps.partition("/")
    written = convert(
        paths,
        args.out,
        frame_rate_num=int(num),
        frame_rate_den=int(den or 1),
        strips=args.strips,
        pattern_override=args.pattern,
        verify=not args.no_verify,
        audio_path=args.audio,
    )
    return 0 if written else 1


if __name__ == "__main__":
    raise SystemExit(main())
