import struct

import pytest

from fcrref import audio
from fcrref.constants import (
    AUDIO_CHUNK_NS,
    AUDIO_MAGIC,
    SAMPLE_FORMAT_F32LE,
    SAMPLE_FORMAT_S16LE,
)


def _samples_s16(frames, channels=2):
    """Deterministic s16le interleaved PCM, `frames` per channel."""
    count = frames * channels
    return struct.pack(f"<{count}h", *[(i % 32768) - 16384 for i in range(count)])


def test_audio_magic_is_aud0():
    assert AUDIO_MAGIC == b"AUD0"


def test_chunk_duration_is_half_a_second():
    assert AUDIO_CHUNK_NS == 500_000_000


def test_sample_format_ids_are_stable():
    assert SAMPLE_FORMAT_S16LE == 0
    assert SAMPLE_FORMAT_F32LE == 1


def test_pack_then_unpack_roundtrips_every_field():
    payload = _samples_s16(24000)
    record = audio.pack_audio(
        payload,
        sequence=7,
        pts_ns=1_234_567_890,
        sample_rate_hz=48000,
        channel_count=2,
        sample_format=SAMPLE_FORMAT_S16LE,
    )
    meta, out = audio.unpack_audio(record)
    assert meta.sequence == 7
    assert meta.pts_ns == 1_234_567_890
    assert meta.sample_rate_hz == 48000
    assert meta.channel_count == 2
    assert meta.sample_format == SAMPLE_FORMAT_S16LE
    assert out == payload


def test_record_starts_with_magic():
    record = audio.pack_audio(
        _samples_s16(4), 0, 0, 48000, 2, SAMPLE_FORMAT_S16LE
    )
    assert record[:4] == AUDIO_MAGIC


def test_unpack_rejects_a_crc_mismatch():
    record = bytearray(
        audio.pack_audio(_samples_s16(64), 3, 0, 48000, 2, SAMPLE_FORMAT_S16LE)
    )
    record[-1] ^= 0xFF  # corrupt the last payload byte
    with pytest.raises(ValueError, match="CRC"):
        audio.unpack_audio(bytes(record))


def test_pack_rejects_an_unknown_sample_format():
    with pytest.raises(ValueError, match="sample_format"):
        audio.pack_audio(b"\x00\x00", 0, 0, 48000, 2, 9)


def test_pack_rejects_a_payload_misaligned_to_frame():
    """Payload bytes must be a whole number of (channel x bytes-per-sample)
    audio frames — a partial frame is a corrupt chunk, not audio."""
    # s16le stereo frame is 4 bytes; 3 bytes is a partial frame.
    with pytest.raises(ValueError, match="payload"):
        audio.pack_audio(b"\x00\x01\x02", 0, 0, 48000, 2, SAMPLE_FORMAT_S16LE)


def test_pack_rejects_a_bad_magic_on_unpack():
    payload = _samples_s16(4)
    record = bytearray(audio.pack_audio(payload, 0, 0, 48000, 2, SAMPLE_FORMAT_S16LE))
    record[0:4] = b"XXXX"
    with pytest.raises(ValueError, match="magic"):
        audio.unpack_audio(bytes(record))


def test_f32le_payload_roundtrips():
    frames, channels = 100, 1
    payload = struct.pack(f"<{frames * channels}f", *[i * 0.5 for i in range(frames)])
    record = audio.pack_audio(
        payload, 0, 500, 44100, channels, SAMPLE_FORMAT_F32LE
    )
    meta, out = audio.unpack_audio(record)
    assert meta.sample_rate_hz == 44100
    assert meta.channel_count == 1
    assert meta.sample_format == SAMPLE_FORMAT_F32LE
    assert out == payload


def test_sample_count_is_derived_from_format_and_channels():
    frames = 24000
    payload = _samples_s16(frames, channels=2)
    record = audio.pack_audio(payload, 0, 0, 48000, 2, SAMPLE_FORMAT_S16LE)
    meta, _ = audio.unpack_audio(record)
    assert meta.sample_count == frames
