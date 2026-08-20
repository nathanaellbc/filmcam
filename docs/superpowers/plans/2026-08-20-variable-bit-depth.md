# Implementation Plan: Variable Bit Depth

**Date:** 2026-08-20
**Status:** Awaiting approval
**Spec:** `docs/superpowers/specs/2026-08-19-filmcam-capture-design.md` §2.3, §2.5, §2.6
**Applies to:** `tools/fcr-reference/`

> **Plan location note.** The planning skill defaults to `tasks/plan.md` + `tasks/todo.md`.
> This project already keeps plans in `docs/superpowers/plans/`, the spec cross-references
> that path, and no `/build`-style tooling is in use here. Keeping one location beats
> matching a default. The task checklist lives in this document rather than a separate
> `tasks/todo.md`, to avoid splitting tasks across two files.

## Overview

The reference implementation hardcodes 14-bit sample depth via a module-level
`BIT_DEPTH = 14` in `constants.py`, from which `MAX_VALUE` and `RAW_BITS` derive. Measurement
on the target device (spec §2.3) found it actually delivers **10-bit** data, and §2.6 now
commits the design to offering the full {10, 12, 14}-bit × {open gate, 4K} matrix and letting
the hardware disqualify modes rather than excluding them by estimate.

This work makes bit depth a **per-clip property** rather than a module constant, so a single
build can encode, decode and measure all three depths. The container header already carries
`bit_depth` — the format needs no change. Only the code that ignores it does.

## Architecture Decisions

### D1. `RAW_BITS` stays fixed at 15. **This is the decision that shapes everything else.**

The Rice escape path writes a zigzag value in `RAW_BITS` bits. The tempting change is
`RAW_BITS = bit_depth + 1`, which is optimal packing. **Rejected.**

A 14-bit residual zigzags to at most 32766, which fits in 15 bits; every shallower depth fits
with room to spare. Holding `RAW_BITS` at 15 therefore costs `15 - (depth + 1)` bits **per
escaped sample only** — 4 bits at 10-bit depth. Escapes are rare: measured at ~47 per
3M-sample plane, roughly **24 bytes per frame against a 5 MB frame**.

What it buys:

- **`rice.py` is not touched at all.** The entropy coder, the length calculator, the escape
  logic and `ESCAPE_LENGTH` all stay exactly as they are — including the one-bit desync fix
  that took a fix round to find.
- **All 44 committed conformance vectors stay byte-valid.** No regeneration, no re-verification
  of the Swift port's existing acceptance criteria.
- **One escape width for the porter** instead of a depth-dependent one.

Cost: sample depth is capped at 14-bit. That is the sensor's ceiling anyway, and §2.3 records
it. Supporting 16-bit later would mean `RAW_BITS = 17`, which is a format break and would
invalidate every existing vector — so it is a deliberate, documented boundary rather than an
oversight.

### D2. `BIT_DEPTH` becomes a documented default, not a law.

`constants.BIT_DEPTH` and `MAX_VALUE` remain, retaining their current values, so nothing that
already imports them changes behaviour. They are re-documented as *defaults for callers that
do not specify a depth*, and a `max_value_for(bit_depth)` helper is added.

### D3. Depth threads through as a parameter, defaulting to current behaviour.

Every signature that gains a `bit_depth` parameter defaults it to `BIT_DEPTH`. Existing
callers, tests and vectors are unaffected — which is what makes this safe to do in steps.

### D4. The committed-vector regression test is the safety net.

`test_committed_artifacts_match_their_recorded_hashes` already pins all 44 artifacts by
SHA-256. Any change that accidentally alters existing encoder output fails immediately and
loudly. **Do not weaken or regenerate the existing vectors during Tasks 1–5.**

## Dependency Graph

```
constants.py  (max_value_for helper; BIT_DEPTH re-documented as default)
     │
     ├── framecodec.py  (encode_frame / decode_frame / estimate_frame_bits gain bit_depth)
     │        │
     │        ├── container.py   (writer passes header.bit_depth; reader passes it back)
     │        │
     │        └── analyze.py     (thread the measured depth into estimation)
     │
     ├── patterns.py   (generators gain a depth/max_value parameter)
     │
     └── vectors.py    (emit 10-bit and 12-bit artifacts; record depth per artifact)

rice.py — UNTOUCHED, per D1
```

Implementation order follows the graph bottom-up. Tasks 3 and 6 are the vertical slices that
deliver something real: a full 10-bit clip round-tripping through the container, and the
Swift port gaining multi-depth acceptance criteria.

---

## Task List

### Phase 1: Foundation

- [ ] **Task 1: Depth helpers in `constants.py`**
- [ ] **Task 2: `framecodec` accepts a bit depth**

### Checkpoint: Foundation
- [ ] `python -m pytest` — 219 passing, no change to existing counts
- [ ] Committed-vector hash test still green (proves no existing output moved)

### Phase 2: End-to-end depth

- [ ] **Task 3: `container` carries depth end-to-end** ← first real vertical slice
- [ ] **Task 4: `analyze` estimates at the measured depth**

### Checkpoint: End-to-end
- [ ] A 10-bit clip writes, reads back identical, and reports a correct ratio
- [ ] All 44 committed vectors unchanged

### Phase 3: Coverage for the port

- [ ] **Task 5: `patterns` generates at any depth**
- [ ] **Task 6: conformance vectors gain 10-bit and 12-bit clips**
- [ ] **Task 7: document supported depths**

### Checkpoint: Complete
- [ ] Vectors regenerate byte-identically; all pre-existing 44 unchanged
- [ ] Spec and README state the supported depths and the 14-bit ceiling
- [ ] Ready for review

---

## Task 1: Depth helpers in `constants.py`

**Description:** Add a `max_value_for(bit_depth)` helper and re-document `BIT_DEPTH` /
`MAX_VALUE` as defaults rather than laws. Record decision D1 in the module docstring, next to
`RAW_BITS`, so the next reader learns why it is fixed before they try to "fix" it.

**Acceptance criteria:**
- [ ] `max_value_for(d)` returns `(1 << d) - 1` and raises `ValueError` outside 8–14
- [ ] `RAW_BITS` carries a comment stating it is deliberately fixed at 15, why, and that this
      caps sample depth at 14-bit
- [ ] `BIT_DEPTH` and `MAX_VALUE` keep their current values

**Verification:**
- [ ] Tests pass: `python -m pytest tests/ -q`
- [ ] New test asserts the bounds of `max_value_for` at 8, 10, 12, 14 and rejects 7 and 15

**Dependencies:** None
**Files:** `src/fcrref/constants.py`, `tests/test_constants.py` (new)
**Scope:** XS

---

## Task 2: `framecodec` accepts a bit depth

**Description:** Add `bit_depth: int = BIT_DEPTH` to `encode_frame`, `decode_frame` and
`estimate_frame_bits`, and make `_check_range` validate against `max_value_for(bit_depth)`
rather than the module `MAX_VALUE`. The payload layout does not change — depth is not written
into the payload, because the container header already carries it.

**Acceptance criteria:**
- [ ] All three functions accept `bit_depth`, defaulting to 14
- [ ] `_check_range` rejects samples above the depth's max, naming the depth in the message
- [ ] A 10-bit mosaic round-trips through `encode_frame` → `decode_frame` exactly
- [ ] Encoding a 10-bit mosaic **at default depth 14** still succeeds — values in range are
      always valid at a greater depth; only the ceiling moves

**Verification:**
- [ ] `python -m pytest tests/test_framecodec.py -v`
- [ ] Round-trip test parametrized over depths 10, 12, 14 and all four CFA patterns
- [ ] **Committed-vector hash test green** — proves default-path output did not move

**Dependencies:** Task 1
**Files:** `src/fcrref/framecodec.py`, `tests/test_framecodec.py`
**Scope:** S

---

## Task 3: `container` carries depth end-to-end

**Description:** `FcrWriter.append_frame` passes `self._header.bit_depth` into `encode_frame`;
`FcrReader.read_frame` passes `self.header.bit_depth` into `decode_frame`. This is the first
slice that delivers real capability: a 10-bit clip written and read back correctly, with the
depth travelling in the header where it already had a field.

**Acceptance criteria:**
- [ ] Writer encodes at the header's declared depth, not the module default
- [ ] Reader decodes at the header's declared depth
- [ ] A 10-bit clip of ≥3 frames round-trips with mosaics and metadata identical
- [ ] `append_frame` raises if a sample exceeds the header's declared depth — a clip that
      declares 10-bit must not silently accept 14-bit data

**Verification:**
- [ ] `python -m pytest tests/test_container.py tests/test_repair.py -v`
- [ ] New test writes a 10-bit clip, reads it back, asserts exact equality
- [ ] New test asserts out-of-range data is rejected at `append_frame`, not at read time
- [ ] Repair scan still recovers a truncated **10-bit** clip

**Dependencies:** Task 2
**Files:** `src/fcrref/container.py`, `tests/test_container.py`, `tests/conftest.py`
**Scope:** S

---

## Task 4: `analyze` estimates at the measured depth

**Description:** `analyze_frame` already accepts and reports `bit_depth`, but passes nothing to
`estimate_frame_bits`, which still assumes 14. Thread it through so the coded-bit estimate and
the raw baseline agree on depth. Without this, the range guard from Task 2 can reject real
10-bit DNGs — or worse, mis-measure them.

**Acceptance criteria:**
- [ ] `analyze_frame` passes its `bit_depth` into `estimate_frame_bits`
- [ ] The per-plane loop uses the same depth as the frame-level estimate
- [ ] Measuring the committed sample footage reproduces the values already recorded in spec
      §2.5 — 2.936:1 main open gate, 1.933:1 ultrawide, 2.675:1 main 4K

**Verification:**
- [ ] `python -m pytest tests/test_analyze.py -v`
- [ ] Manual: re-run against `sample/20260820_142535_dng` and confirm 2.936:1 unchanged
- [ ] Test asserts a 10-bit frame's `raw_bits` is `pixels × 10`, not `pixels × 14`

**Dependencies:** Task 2
**Files:** `src/fcrref/analyze.py`, `tests/test_analyze.py`
**Scope:** S

---

## Task 5: `patterns` generates at any depth

**Description:** The generators scale to `MAX_VALUE`. Add a `bit_depth: int = BIT_DEPTH`
parameter so Task 6 can emit shallower test material. **The default must reproduce current
output byte-for-byte** — this is the highest regression risk in the plan, because these
functions feed 44 committed hashes.

**Acceptance criteria:**
- [ ] `horizontal_ramp`, `vertical_ramp`, `flat`, `colour_bars`, `shot_noise`, `zone_plate`
      accept `bit_depth`
- [ ] `motion_sequence` threads it to `zone_plate`
- [ ] **Default-depth output is byte-identical to current output** for every generator
- [ ] At 10-bit, no sample exceeds 1023

**Verification:**
- [ ] `python -m pytest tests/test_patterns.py -v`
- [ ] **Committed-vector hash test green — this is the gate for this task**
- [ ] Test asserts each generator's 14-bit output is unchanged and its 10-bit output is in range

**Dependencies:** Task 1
**Scope:** S
**Files:** `src/fcrref/patterns.py`, `tests/test_patterns.py`

---

## Task 6: Conformance vectors gain 10-bit and 12-bit clips

**Description:** The payoff. Add artifacts at 10-bit and 12-bit so the Swift port has
acceptance criteria for every depth it will encounter, not just 14-bit. Record each artifact's
depth in the manifest.

Add: `source_*_d10.raw16` and `_d12` variants for at least the noise and ramp patterns;
`frame_*_d10.fcrpayload` / `_d12` across CFA patterns; `clip_2frame_d10.fcr`.

**Acceptance criteria:**
- [ ] New artifacts at 10-bit and 12-bit covering source, frame payload and a full clip
- [ ] Each manifest entry records its `bit_depth`
- [ ] Manifest `constants` block notes `raw_bits` is fixed at 15 across all depths (D1)
- [ ] **All 44 pre-existing artifacts are byte-identical** — verify explicitly, do not assume
- [ ] Regeneration remains byte-identical across runs

**Verification:**
- [ ] `python -m pytest tests/test_vectors.py -v`
- [ ] `python -m fcrref.vectors --out vectors/` then diff against a temp regeneration
- [ ] Explicit check that the 44 original hashes are unchanged in the new manifest
- [ ] `git status` confirms every new artifact is staged and none is swallowed by `.gitignore`

**Dependencies:** Tasks 3, 5
**Files:** `src/fcrref/vectors.py`, `tests/test_vectors.py`, `vectors/*`
**Scope:** M

---

## Task 7: Document supported depths

**Description:** Update spec §2.3 and the tool README to state which depths the reference
implementation supports, that `RAW_BITS` is fixed at 15 with a 14-bit ceiling, and that the
container header is the authority on a clip's depth.

**Acceptance criteria:**
- [ ] Spec §2.3 states supported depths {10, 12, 14} and the 14-bit ceiling with D1's rationale
- [ ] README documents the `bit_depth` parameter and the conformance procedure across depths
- [ ] The §2.6 mode matrix cross-references this plan's outcome

**Verification:**
- [ ] Manual read-through
- [ ] No stale claim that depth is fixed remains — `grep -rn "14-bit throughout"` returns nothing

**Dependencies:** Task 6
**Files:** `docs/superpowers/specs/2026-08-19-filmcam-capture-design.md`, `tools/fcr-reference/README.md`
**Scope:** S

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| A change silently alters existing encoder output, staling all 44 vectors | **High** | The committed-vector hash test (added in the last fix wave) fails immediately. It is the checkpoint gate after every phase. |
| `patterns` default output shifts, breaking every downstream artifact | **High** | Task 5's acceptance criterion is byte-identical default output; the hash test is its gate. Defaults must be exact, not merely equivalent. |
| Depth cap at 14-bit surprises a future implementer | Medium | D1 documented in `constants.py` beside `RAW_BITS`, in the spec, and in the manifest's constants block. |
| A clip declares one depth and carries data of another | Medium | Task 3 makes `append_frame` reject out-of-range samples at write time rather than at playback. |
| Scope creep into `rice.py` | Medium | D1 makes it unnecessary. Any diff touching `rice.py` in this work is a signal the implementer took the rejected path. |
| Vector count grows the repo | Low | Artifacts are small (12 KB sources); the whole existing set is well under 1 MB. |

## Open Questions

- **Does the device actually vend 12-bit or 14-bit?** Unknown — RAW Cam writes 10-bit with the
  signature of 14-bit right-shifted by four (§2.3). The Phase 0 probe answers it. **This does
  not block this work**: supporting all three depths is what lets us use whichever turns out to
  be available.
- **Should the reference tool ever support 16-bit?** Currently impossible without changing
  `RAW_BITS` to 17, which is a format break invalidating every vector. Recommend: no, unless a
  sensor requiring it appears.
- **Should `analyze` gain a `--bit-depth` override for `--raw16` inputs?** It already has one.
  Worth confirming it interacts correctly with Task 4's threading.

## Definition of Done

1. `python -m pytest` green in `tools/fcr-reference/`.
2. All 44 pre-existing conformance artifacts byte-identical; new artifacts registered and
   regenerating identically.
3. A 10-bit clip writes, reads, repairs and measures correctly end to end.
4. `rice.py` unchanged.
5. Spec §2.3 and the README state the supported depths and the 14-bit ceiling.
