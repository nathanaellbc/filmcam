"""The AUD0 embedded-audio record.

Audio lives in the .fcr container as its own record type, interleaved
between FRM0 frame records and located via a parallel index (container
version 2). This is the model MCRAW proves — a second timestamped stream
in one file — adapted to .fcr's append-only, crash-safe design: every
record carries a magic and a CRC32, so the repair scan walks past audio
records exactly as it walks frames.

Sync (plan D5): `pts_ns` is the host-clock time of the chunk's FIRST
sample, on the same clock as frame pts and the gyro sidecar (spec 5.5).
Post aligns audio to video by `audio_pts - first_frame_pts`, at sample
precision. There is no "audio starts at zero" assumption to drift.

Wire layout (little-endian), fixed 28-byte header then payload:
    "AUD0" magic (4 bytes)
    u32  sequence          audio-chunk sequence, monotonic from 0
    u64  pts_ns            host-clock time of the first sample
    u32  sample_rate_hz    e.g. 48000
    u16  channel_count     e.g. 2
    u8   sample_format     0 = s16le, 1 = f32le (constants.SAMPLE_FORMAT_*)
    u8   flags             reserved, 0
    u32  payload_bytes
    u32  crc32             of the payload
    ...  payload           channel_count * sample_count interleaved samples
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

from .constants import AUDIO_MAGIC, SAMPLE_FORMAT_F32LE, SAMPLE_FORMAT_S16LE

AUDIO_RECORD_FMT = "<4sIQIHBBII"
AUDIO_RECORD_SIZE = struct.calcsize(AUDIO_RECORD_FMT)

_BYTES_PER_SAMPLE = {
    SAMPLE_FORMAT_S16LE: 2,
    SAMPLE_FORMAT_F32LE: 4,
}


@dataclass(frozen=True)
class AudioMeta:
    sequence: int
    pts_ns: int
    sample_rate_hz: int
    channel_count: int
    sample_format: int
    sample_count: int  # per channel


def _bytes_per_sample(sample_format: int) -> int:
    try:
        return _BYTES_PER_SAMPLE[sample_format]
    except KeyError:
        raise ValueError(f"unknown sample_format {sample_format}") from None


def pack_audio(
    payload: bytes,
    sequence: int,
    pts_ns: int,
    sample_rate_hz: int,
    channel_count: int,
    sample_format: int,
    flags: int = 0,
) -> bytes:
    """Pack a chunk of PCM into an AUD0 record."""
    bps = _bytes_per_sample(sample_format)
    if channel_count < 1:
        raise ValueError(f"channel_count must be >= 1, got {channel_count}")
    frame_bytes = bps * channel_count
    if len(payload) % frame_bytes:
        raise ValueError(
            f"payload of {len(payload)} bytes is not a whole number of "
            f"{frame_bytes}-byte audio frames ({channel_count} ch x {bps} B)"
        )
    header = struct.pack(
        AUDIO_RECORD_FMT,
        AUDIO_MAGIC,
        sequence,
        pts_ns,
        sample_rate_hz,
        channel_count,
        sample_format,
        flags,
        len(payload),
        zlib.crc32(payload) & 0xFFFFFFFF,
    )
    return header + payload


def unpack_audio(data: bytes) -> tuple[AudioMeta, bytes]:
    """Unpack an AUD0 record into its metadata and PCM payload."""
    if len(data) < AUDIO_RECORD_SIZE:
        raise ValueError("audio record truncated")
    (magic, sequence, pts_ns, sample_rate_hz, channel_count, sample_format,
     _flags, payload_bytes, crc) = struct.unpack_from(AUDIO_RECORD_FMT, data, 0)
    if magic != AUDIO_MAGIC:
        raise ValueError(f"bad audio record magic {magic!r}")
    end = AUDIO_RECORD_SIZE + payload_bytes
    payload = data[AUDIO_RECORD_SIZE:end]
    if len(payload) != payload_bytes:
        raise ValueError(
            f"audio record payload truncated: expected {payload_bytes}, "
            f"got {len(payload)}"
        )
    if (zlib.crc32(payload) & 0xFFFFFFFF) != crc:
        raise ValueError(f"CRC mismatch on audio chunk {sequence}")
    bps = _bytes_per_sample(sample_format)
    sample_count = payload_bytes // (bps * channel_count)
    meta = AudioMeta(
        sequence=sequence,
        pts_ns=pts_ns,
        sample_rate_hz=sample_rate_hz,
        channel_count=channel_count,
        sample_format=sample_format,
        sample_count=sample_count,
    )
    return meta, payload
