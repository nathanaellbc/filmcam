# Implementation Plan: Embedded Audio in `.fcr`

**Date:** 2026-08-21
**Status:** Awaiting approval
**Spec:** `docs/superpowers/specs/2026-08-19-filmcam-capture-design.md` §5.3, §5.5, §8
**Applies to:** `tools/fcr-reference/`
**Research basis:** MCRAW decoder source (`mirsadm/motioncam-decoder`, `motioncam-decoder` crate) — see Research Notes.

> **Plan location note.** Plans live in `docs/superpowers/plans/`, matching the Stage W and
> variable-bit-depth plans; the spec cross-references that path. The task checklist lives in
> this document rather than a separate `tasks/todo.md`, to avoid splitting tasks across files.

## Overview

`.fcr` today is a **video-only** container: a fixed header, an append-only run of `FRM0`
frame records, an index, and a trailer. The capture design records gyro in a separate `.fcm`
sidecar but never specifies an audio path — a real gap, because a camera that records no
audio is not a camera.

This work adds **first-class audio to `.fcr`**, so a single file carries video and audio
together, in the model MCRAW has already proven: a typed-record stream with a **second,
timestamped index** for audio. The change is confined to the reference implementation and its
conformance vectors — the project is still Windows-only (no Mac, no compiled Swift) — so this
is format work plus reference code, exactly like Stage W. The Swift port in Stage M1 will
implement against the vectors this plan freezes.

**Decisions locked at planning (from the human):**

| # | Decision | Choice |
|---|---|---|
| A | Platform scope | Windows-only: reference implementation + conformance vectors |
| B | Container model | Extend `.fcr` with an interleaved audio record type (MCRAW-style) |
| C | Audio payload | PCM, uncompressed — 16-bit integer or 32-bit float |
| D | A/V sync | Shared host clock, sample-accurate (spec §5.5 discipline) |
| E | Versioning | Bump container version 1 → 2 for audio-capable files |
| F | Repair | Skip unknown records, keep scanning; recover audio too |
| G | Interleave granularity | Chunked, ~0.5 s of audio per record |

## Research Notes — what MCRAW actually does

Read from the real decoder source (`container.rs`, `decoder.rs`). MCRAW is a typed-item
stream. Every item is an 8-byte header `(item_type: u32, size: u32)` plus payload, of 7
types: `BufferIndex`, `BufferIndexData`, `Buffer` (a compressed video frame), `Metadata`
(JSON), `AudioIndex`, `AudioData`, `AudioDataMetadata`.

- **Audio is a parallel stream, not interleaved per-frame.** Each `AudioData` item is a chunk
  of 16-bit little-endian PCM. Each chunk is followed by an `AudioDataMetadata` item carrying
  `timestamp_ns`. An `AudioIndex` near EOF holds `num_offsets`, `start_timestamp_ms`, and an
  `(offset, timestamp)` table.
- **Sync is one clock, two indexes.** Both frame offsets and audio offsets are
  `(offset, timestamp)` pairs on a shared timeline. A player aligns audio to video purely by
  matching timestamps; sample rate and channel count come from container JSON
  (`extraData.audioSampleRate`, `extraData.audioChannels`).
- **Frame index lives at the very end of the file.** A crash before that index is written
  orphans the file; MCRAW documents no repair scan. `.fcr` is strictly stronger here: its
  `FRM0` markers + CRCs already let a repair scan walk the record stream. This plan keeps that
  advantage and extends it to audio.

**The lesson `.fcr` adopts:** a second timestamped record type and a second index — *without*
giving up the append-only, crash-safe design, because per-record markers and CRCs let the
repair scan walk past audio records as easily as frames.

## Architecture Decisions

### D1. A new record type `AUD0`, not a repurposed frame record.

Audio travels in its own record with its own magic, so readers, the repair scan, and the
index can tell record kinds apart by their first four bytes. Wire layout, little-endian,
mirroring the frame record's shape so the same parsing idioms apply:

```
" AUD0 " magic (4 bytes, b"AUD0")
u32  sequence            audio-chunk sequence, monotonic from 0
u64  pts_host_time_ns    host-clock time of the FIRST sample in the chunk
                         (same clock as frame pts and gyro — Decision D)
u32  sample_rate_hz      e.g. 48000
u16  channel_count       e.g. 2
u8   sample_format       0 = s16le interleaved, 1 = f32le interleaved
u8   flags               reserved, 0
u32  payload_bytes
u32  crc32               of the payload
...  payload             channel_count * n samples, interleaved, little-endian
```

The fixed header is 28 bytes (`<4sIQIHBBII`), then the payload. A chunk carries a whole
number of **frames-worth of samples is not required** — audio runs on its own chunk cadence
(G), aligned to video only through the shared clock.

### D2. `RAW_BITS` and the Rice codec are untouched. Audio is not compressed by the video codec.

Audio is stored as raw PCM (Decision C). At 48 kHz stereo 16-bit that is ~192 KB/s — noise
against a 125–271 MB/s video budget. There is no Rice path for audio; adding one would be
scope creep with no payoff. The conformance vectors already pin the codec; this plan does not
touch them.

### D3. The index gains a parallel audio table; the trailer gains a second offset.

The container version bumps to **2** (Decision E). A v2 file's index is:

```
u32 frame_count
[ offset:u64, size:u32 ] × frame_count     (as today)
u32 audio_count
[ offset:u64, size:u32 ] × audio_count     (NEW)
```

and the trailer becomes `"FCRX" + u64 index_offset` as today (the index already
self-describes its two counts, so the trailer needs no new fields). **Version 1 files remain
readable:** `unpack_header` already rejects unknown versions, so the reader must special-case
`version == 1` (no audio table) vs `version == 2` (audio table present). A v1 reader opening
a v2 file fails cleanly at the version gate — the desired behaviour.

### D4. The repair scan becomes record-type-aware.

Today `scan_frames` breaks at the first non-`FRM0` marker — which, with audio interleaved,
would truncate every clip at the first audio chunk. The scan must instead walk **both**
record magics, validating each by CRC, and collecting frame and audio offsets into separate
lists. Unknown/garbage bytes still halt the scan (that is how truncation is detected). A
crash therefore still costs only the in-flight record, and audio is recovered alongside video
(Decision F). The function is renamed conceptually to `scan_records`, returning
`(frames, audios)`; `scan_frames` is kept as a thin wrapper for the existing callers/tests.

### D5. Sync is by shared-clock PTS, sample-accurate.

`pts_host_time_ns` on every `AUD0` chunk is the host-clock time of the chunk's first sample,
on the **same clock** as frame `pts_ns` and the gyro sidecar (spec §5.5). Post aligns audio
to video by `audio_pts - first_frame_pts`, with sample-rate precision. No drift-prone
"audio starts at zero" assumption. This is the property MCRAW gets via `timestamp_ns`, and the
property your spec's clock discipline already demands.

### D6. Interleave is chunked at ~0.5 s of audio.

Audio is buffered and flushed as ~0.5 s chunks (Decision G), interleaved between frame
records as they are produced. 0.5 s at 48 kHz stereo 16-bit is 96 KB per record — bounded
memory, coarse enough that record overhead is negligible (~24 records per 12 s of audio at 48
kHz), fine enough that a streaming reader never waits long for either stream.

## Dependency Graph

```
constants.py   (AUD0 magic, sample-format ids, AUDIO_CHUNK_NS)
     │
     ├── container.py  (version 2; AUD0 pack/unpack; writer.append_audio;
     │     │            index gains audio table; reader exposes audio)
     │     │
     │     └── repair.py  (record-type-aware scan; rebuilds both indexes)
     │
     ├── vectors.py    (v2 conformance vectors: a clip with interleaved audio)
     │
     └── inspect.py    (structural check validates AUD0 CRCs too; report audio)
```

`framecodec.py`, `rice.py`, `bayer.py`, `predictor.py` — **UNTOUCHED** (D2). The 66 committed
v1 vectors must remain byte-identical throughout; `test_committed_artifacts_match_their_recorded_hashes`
is the standing gate.

## Task List

### Phase 1: Format foundation

- [ ] **Task 1: Audio constants and the `AUD0` record codec**
- [ ] **Task 2: Container version 2 — index with parallel audio table**

### Checkpoint: Foundation
- [ ] `python -m pytest` green; all 66 v1 vectors unchanged
- [ ] A v1 file still reads identically; a v2 header is accepted

### Phase 2: Writer / reader / repair end-to-end

- [ ] **Task 3: `FcrWriter.append_audio` and `FcrReader` audio access** ← first vertical slice
- [ ] **Task 4: record-type-aware repair scan**

### Checkpoint: End-to-end
- [ ] A clip with interleaved audio writes, reads back identical (frames + audio)
- [ ] Truncation mid-audio recovers video AND earlier audio; CRC corruption halts cleanly

### Phase 3: Coverage for the port

- [ ] **Task 5: v2 conformance vectors with interleaved audio**
- [ ] **Task 6: `inspect` validates and reports audio; documentation**

### Checkpoint: Complete
- [ ] Vectors regenerate byte-identically; all 66 v1 vectors unchanged
- [ ] Spec §5.3 documents the v2 layout and the audio record
- [ ] Ready for review

---

## Task 1: Audio constants and the `AUD0` record codec

**Description:** Add `AUDIO_MAGIC = b"AUD0"`, sample-format ids (`SAMPLE_FORMAT_S16LE = 0`,
`SAMPLE_FORMAT_F32LE = 1`), and `AUDIO_CHUNK_NS` (0.5 s) to `constants.py`. Implement
`pack_audio(...)` / `unpack_audio(...)` in a new module `audio.py`, mirroring
`container.pack_frame`: fixed 28-byte header + payload + CRC32. Pure byte work, independently
testable, no container dependency.

**Acceptance criteria:**
- [ ] `pack_audio(samples: bytes, sequence, pts_ns, sample_rate_hz, channel_count,
      sample_format) -> bytes` produces the D1 wire layout
- [ ] `unpack_audio(data: bytes) -> AudioMeta + payload` round-trips every header field
- [ ] CRC mismatch raises `ValueError` naming the chunk sequence
- [ ] Rejects an unknown `sample_format` and a payload size not divisible by the format's
      bytes-per-sample × channel_count

**Verification:**
- [ ] `python -m pytest tests/test_audio.py -v`
- [ ] Round-trip over s16le and f32le, mono and stereo

**Dependencies:** None
**Files:** `src/fcrref/constants.py`, `src/fcrref/audio.py`, `tests/test_audio.py`
**Scope:** S

---

## Task 2: Container version 2 — index with parallel audio table

**Description:** Bump `_HDR_VERSION` handling so the container reads **and** writes v2 while
still reading v1. The index writer appends the audio table; the reader loads it when
`version == 2`, and treats a v1 file as having zero audio records. The header fields do not
change; only the version number and the index/trailer region do.

**Acceptance criteria:**
- [ ] `_HDR_VERSION = 2`; `unpack_header` accepts both 1 and 2 (v1 → audio table absent)
- [ ] Index round-trips: N frame entries followed by M audio entries, then trailer
- [ ] A committed v1 vector (e.g. `clip_2frame.fcr`) still reads with `frame_count == 2` and
      zero audio records — proving backward compatibility
- [ ] Writing a new clip emits version 2

**Verification:**
- [ ] `python -m pytest tests/test_container.py -v`
- [ ] **Committed-vector hash test green** (v1 bytes must not move)

**Dependencies:** Task 1
**Files:** `src/fcrref/container.py`, `tests/test_container.py`
**Scope:** M

---

## Task 3: `FcrWriter.append_audio` and `FcrReader` audio access

**Description:** The vertical slice. `FcrWriter.append_audio(samples, pts_ns, sample_rate_hz,
channel_count, sample_format)` packs an `AUD0` record, appends it, and records its offset in
a parallel audio index written at `finalize()`. `FcrReader` exposes `audio_count` and
`read_audio(index) -> (samples_bytes, AudioMeta)`, validating the chunk CRC. Interleaving is
the caller's responsibility — the writer simply appends records in the order it is given
them, frames and audio alike.

**Acceptance criteria:**
- [ ] `append_audio` before `write_header` raises, like `append_frame`
- [ ] A clip of interleaved frames + audio reads back with both streams byte-identical
- [ ] `audio_count` matches the number of `append_audio` calls
- [ ] `read_audio` CRC failure raises `ValueError`

**Verification:**
- [ ] `python -m pytest tests/test_container.py -v`
- [ ] Interleaved 3-frame / 2-chunk clip round-trips exactly

**Dependencies:** Task 2
**Files:** `src/fcrref/container.py`, `tests/test_container.py`, `tests/conftest.py`
**Scope:** M

---

## Task 4: Record-type-aware repair scan

**Description:** Replace the "stop at first non-`FRM0`" logic with a scan that recognises
**both** `FRM0` and `AUD0`, validates each record's CRC, and collects frame and audio offsets
into separate lists. `repair()` rebuilds the index with both tables and the trailer, so a
crashed v2 clip recovers video *and* all complete audio. `scan_frames` remains as a wrapper
returning only the frame list, so existing callers and tests are undisturbed.

**Acceptance criteria:**
- [ ] Scanning a healthy interleaved clip finds every frame AND every audio chunk
- [ ] Truncation mid-audio-payload recovers all earlier frames and audio, drops the partial
- [ ] A flipped bit inside an audio payload halts recovery at that record (CRC gate)
- [ ] The 50-seed truncation property test still passes on video-only clips
- [ ] New truncation property test: interleaved clip, 50 seeds, never a partial record

**Verification:**
- [ ] `python -m pytest tests/test_repair.py -v`
- [ ] Existing video-only repair tests unchanged and green

**Dependencies:** Task 3
**Files:** `src/fcrref/repair.py`, `tests/test_repair.py`
**Scope:** M

---

## Task 5: v2 conformance vectors with interleaved audio

**Description:** The payoff — give the Swift port acceptance criteria for audio. Add a v2
clip to `vectors/`: the existing reference header (at version 2), 3 frames, and a short
interleaved deterministic PCM tone (e.g. a fixed-seed sine or ramp) split into `AUD0` chunks.
Record the container version and audio constants in the manifest's constants block. **The 66
v1 artifacts must remain byte-identical** — new artifacts are additive, and the v1 clip
vectors (`clip_2frame.fcr`, `clip_repaired.fcr`) stay at version 1 by construction.

**Acceptance criteria:**
- [ ] New artifact(s): a v2 `.fcr` with interleaved audio, plus its source PCM committed
- [ ] Manifest constants record `container_version: 2`, `audio_magic`, sample-format ids
- [ ] **All 66 pre-existing artifacts byte-identical** — verified explicitly against git
- [ ] Regeneration byte-identical across runs
- [ ] A test reads the v2 vector and asserts frames and audio round-trip to their sources

**Verification:**
- [ ] `python -m pytest tests/test_vectors.py -v`
- [ ] `git status` confirms new artifacts staged, none swallowed by `.gitignore`

**Dependencies:** Task 4
**Files:** `src/fcrref/vectors.py`, `tests/test_vectors.py`, `vectors/*`
**Scope:** M

---

## Task 6: `inspect` validates audio; documentation

**Description:** Extend `inspect.check` to validate `AUD0` record CRCs alongside frames and
report the audio stream (chunk count, sample rate, channels, format, total duration from
PTS span). Update spec §5.3 with the v2 container layout (audio record, parallel index,
version 2) and a short subsection on the shared-clock A/V sync guarantee. Update the
`fcr-reference` README's container description.

**Acceptance criteria:**
- [ ] `inspect --check` on a v2 clip reports audio and validates every record
- [ ] `inspect` on a v1 clip reports zero audio without error
- [ ] Spec §5.3 shows the `AUD0` wire layout and the v2 index/trailer
- [ ] Spec §5.5 cross-references the shared-clock audio PTS

**Verification:**
- [ ] `python -m pytest tests/test_convert.py -v` (inspect tests)
- [ ] Manual read-through of the spec diff

**Dependencies:** Task 5
**Files:** `src/fcrref/inspect.py`, `tests/test_convert.py`,
`docs/superpowers/specs/2026-08-19-filmcam-capture-design.md`, `tools/fcr-reference/README.md`
**Scope:** S

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Repair scan stops early on interleaved audio (today's behaviour) | **High** — truncates every clip | D4 makes the scan record-type-aware; Task 4's truncation property tests are the gate. |
| v1 vectors accidentally move | **High** — stales the Swift port's acceptance criteria | D2 keeps the codec untouched; the committed-hash test runs after every phase; Task 5 verifies the 66 explicitly via git. |
| v1 reader mishandles a v2 file | Medium | The version gate (Task 2) rejects v2 in v1 readers cleanly, by design. |
| A/V sync drifts on long takes | Medium | D5: shared host-clock PTS on every chunk, sample-accurate; no "audio starts at zero" assumption. |
| Scope creep into audio compression | Medium | D2 forbids it — PCM only; the bandwidth cost is negligible. |
| Writer/reader index asymmetry (frame count vs audio count) | Medium | Task 2 round-trips the index; Task 5's vector pins the exact byte layout for the port. |

## Open Questions

- **Chunk-duration adaptivity.** 0.5 s is the planning default (D6). If a real capture shows
  audio delivery arriving in bursts, the writer could adapt chunk size to delivery — the
  format does not care (each record self-describes its sample count). Defer to Stage M1
  device testing.
- **Multiple audio sources** (built-in + external mic). The `channel_count` field covers
  channels of one source; multiple *sources* would need a source id. v1 scope: one source.
  Flagged for the spec, not this plan.
- **Does iOS deliver audio on the identical host clock as video PTS?** Believed yes
  (`CMClockGetHostTimeClock`), but this is a Phase 0 probe item to confirm on-device, like
  every §4.1 question. The format is correct either way; the probe confirms the *clock*.

## Definition of Done

1. `python -m pytest` green in `tools/fcr-reference/`.
2. All 66 pre-existing v1 conformance artifacts byte-identical; new v2 artifacts registered
   and regenerating identically.
3. A clip with interleaved audio writes, reads, repairs, and inspects correctly end to end.
4. `rice.py`, `framecodec.py`, `bayer.py`, `predictor.py` unchanged (D2).
5. Spec §5.3 documents the v2 layout and the audio record; v1 files still read cleanly.
