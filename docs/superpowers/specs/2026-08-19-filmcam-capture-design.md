# FilmCam — RAW Capture Engine & Monitoring (v1) — Design

**Date:** 2026-08-19
**Status:** Approved design, pending implementation plan
**Scope:** Subsystem A (capture engine) + Subsystem B (monitoring & controls)
**Target device:** iPhone 15 (base model), iOS 17+

---

## 1. What this is

A professional RAW video camera for iPhone that bypasses Apple's ISP, records 14-bit Bayer
sensor data, and gives the operator monitoring they can trust.

It exists because the closest existing apps (RAW Cam, Log Cam) get the capture right and the
experience wrong. Their users report three things consistently: the preview lies about
exposure, the app feels fragile, and it looks like a developer tool. All three are addressed
here by architecture, not decoration.

### Goals

1. Record 14-bit Bayer video at 24 fps without dropping frames, or say clearly when it does.
2. Give the operator metering that reflects **sensor data**, not the tone-mapped preview.
3. Never surprise the operator — degrade visibly and in a published order, never silently.
4. Record everything post-production stabilization will need, even though stabilization
   itself is not in v1.

### Non-goals for v1

- On-device debayer → ProRes/HEVC transcode pipeline (subsystem C)
- Gyro stabilization (subsystem D) — but see Appendix A, which constrains v1's recorded data
- Library, playback, offload UI (subsystem E) — minimal file management only
- Autofocus during recording. Not available on this capture path. Not a deferred feature; an
  architectural impossibility on the RAW pipeline.

### Deliberate constraint

Development happens on Windows; there is no Mac yet. **No Swift in this design has been
compiled or run.** Phase 0 exists precisely because of this.

This is not a full blocker. The container format and the lossless codec — the highest-risk
components — are platform-agnostic algorithms, and are built first on Windows as a reference
implementation with conformance vectors. See Stage W in §10.

---

## 2. The hardware reality

Everything below follows from one table.

### 2.1 Bandwidth budget

| Mode | Frame @14-bit packed | Uncompressed @24 fps | Verdict |
|---|---|---|---|
| Full 48 MP open gate | 84 MB | 2.0 GB/s | **Impossible** |
| **12 MP binned open gate** | 21 MB | **504 MB/s** | Viable **only with lossless compression** |
| 4K crop (8.3 MP) | 14.5 MB | 350 MB/s | Viable, less stabilization margin |

**Decision: 12 MP binned open gate is the primary mode.** 4K crop is a fallback if the probe
shows 12 MP cannot hold 24 fps.

### 2.2 Why 48 MP is not available

Five independent walls, any one of which is decisive:

1. **The format does not exist.** `AVCaptureDevice.formats` enumerates what the sensor→ISP link
   can stream. There is no 48 MP video format at any frame rate. 48 MP is a stills readout
   taking hundreds of milliseconds per frame.
2. **Quad-Bayer is not Bayer.** The 48 MP array puts 2×2 sub-pixel groups under a single colour
   filter. Standard demosaic algorithms cannot process this pattern. Apple's ISP runs a
   proprietary *remosaic* step to synthesise a true Bayer grid — inside the very ISP we are
   bypassing. Binning 2×2 instead yields a real Bayer 12 MP frame with **4× the signal and
   lower read noise**: a better image, not a lesser one.
3. **Write bandwidth.** ~800 MB/s even compressed; sustained NVMe write falls well below that
   once warm.
4. **Compression compute.** 1.15 gigapixels/sec of entropy coding on an A16. Off by an order
   of magnitude.
5. **Memory and storage.** An 8-frame ring buffer alone is 672 MB against ~2–3 GB usable.
   128 GB of storage holds ~2.5 minutes.

### 2.3 Bit depth

14-bit throughout, stored packed at 7 bytes per 4 pixels (1.75 B/px).

iOS's only Bayer pixel formats are 14-bit (`kCVPixelFormatType_14Bayer_{RGGB,BGGR,GRBG,GBRG}`).
There is no 12-bit format to fall back to. Reducing bit depth is not a useful lever anyway:
12-bit would save 25% of bandwidth at the cost of two stops of shadow latitude, while
compression saves ~60% for free.

### 2.4 Other device facts that shape the design

| Fact | Consequence |
|---|---|
| USB-C at **USB 2** speed (~40 MB/s) | External SSD recording is impossible. A 5-min take takes ~25 min to offload. |
| 6 GB RAM, ~2–3 GB usable | Fixed pre-allocated buffer pool; zero allocation on the capture path. |
| No Apple-sanctioned ProRes encode | Probe must determine whether `VTCompressionSession` vends ProRes anyway. |
| No hardware HEVC 4:4:4 on A16 | 4:4:4 output is a desktop-export path, not an on-device one. |
| Thin thermal envelope | Degradation ladder is a core feature, not a safety net. |

---

## 3. Architecture

```
        ┌──────────────┐
        │ CaptureCore  │   device selection, format negotiation,
        │              │   CaptureSource protocol + 3 implementations
        └──────┬───────┘
               │  Frame (pixel buffer + PTS + per-frame metadata)
        ┌──────▼───────┐
        │ FrameBroker  │   single producer → prioritised fan-out
        └──┬───┬────┬──┘
           │   │    │
    ┌──────▼─┐ │  ┌─▼──────────┐
    │Recorder│ │  │ScopeEngine │   throttled, best-effort
    │        │ │  │            │
    └────────┘ │  └────────────┘
          ┌────▼──────┐
          │Viewfinder │   Metal preview
          └───────────┘

        ┌──────────────┐
        │  Telemetry   │   thermal · storage · drops · duration
        └──────────────┘   observed by everything, blocks nothing
```

### 3.1 The governing rule

**Recording is privileged; everything else is best-effort.**

`FrameBroker` delivers each frame to `Recorder` synchronously and to all other consumers
opportunistically. If `ScopeEngine` is still computing when the next frame arrives, that frame
is skipped **for scopes** and recorded anyway.

This is the structural answer to "it feels fragile". Log Cam crashes on base iPhone 15s when
false colour is toggled during exposure changes — the signature of monitoring work contending
with capture on a shared queue. Making that contention impossible is cheaper than debugging it.

### 3.2 `CaptureSource`

One protocol, three implementations, selected at runtime from probe results:

| Implementation | Used when |
|---|---|
| `BayerVideoSource` | Device vends a Bayer format via `AVCaptureVideoDataOutput`. The good path: real frame pacing, proper timestamps, low overhead. |
| `PhotoBurstSource` | Fallback. `AVCapturePhotoOutput` fired repeatedly. Proven (RAW Cam ships on it), but jittery pacing and heavy memory churn. |
| `FileBackedSource` | Development and tests. Replays canned sequences or synthetic patterns at exact timing. |

`FileBackedSource` is not a convenience — it is what makes the monitoring subsystem testable
against ground truth. See §9.

### 3.3 Module boundaries

| Module | Responsibility | Depends on |
|---|---|---|
| `CapabilityProbe` | Enumerate device capabilities; used by both app and probe target | — |
| `CaptureCore` | Device/format negotiation, `CaptureSource` implementations, `Frame` model | `CapabilityProbe` |
| `FrameBroker` | Prioritised fan-out, backpressure accounting | `CaptureCore` |
| `RecordingEngine` | Ring buffer, `.fcr` writer, Rice codec, motion sidecar, state machine. Shown as `Recorder` in the diagram above. | `FrameBroker` |
| `ScopeEngine` | Metal compute for histogram / waveform / vectorscope | `FrameBroker` |
| `Viewfinder` | Metal preview: debayer, look LUT, false colour, zebras, peaking | `FrameBroker` |
| `Telemetry` | Thermal, storage runway, drop counts, degradation state | observes all |
| `AppUI` | SwiftUI shell, control surface | all |

---

## 4. Phase 0 — the capability probe

A **separate, disposable Xcode target** (`FilmCamProbe`) wrapping the shared `CapabilityProbe`
module in a verbose diagnostic UI. One screen, one button, writes JSON.

The app itself calls the same module silently at launch to select a `CaptureSource`. Shared
logic, two front-ends: no duplication, no diagnostic code shipped.

### 4.1 What it must answer

| Question | Method |
|---|---|
| **Does a Bayer video format exist?** | `format.availableVideoCVPixelFormatTypes` — look for `14Bayer_*` |
| Which devices/formats/frame rates exist | Enumerate `AVCaptureDevice.formats` across main, ultrawide, front |
| Open-gate dimensions per format | `formatDescription` dimensions vs. `supportedMaxPhotoDimensions` |
| RAW photo formats available | `AVCapturePhotoOutput.availableRawPhotoPixelFormatTypes` |
| **Does ProRes encode exist on a non-Pro?** | `VTCopyVideoEncoderList`, filter for ProRes codec types |
| Which HEVC profiles encode | `VTCopyVideoEncoderList` + `VTSessionCopySupportedPropertyDictionary` |
| **Rolling-shutter readout time** | Per-format sensor readout duration (needed by Appendix A) |
| **Camera intrinsics availability** | Whether `AVCameraCalibrationData` is vended on this device/format |
| **Black/white level metadata availability** | Whether per-frame sensor level attachments are present on RAW buffers (see §6.1) |
| Sustained write throughput | Write 500 MB, report actual MB/s and variance |
| Thermal behaviour | 60 s capture soak, sample `thermalState` and frame delivery, report the knee |

That last row converts "will a base 15 survive a take?" from an argument into a number.

### 4.2 Output

A single JSON file, AirDropped or exported via Files, structured for direct use as a
capability manifest and as input to the implementation plan.

**Phase 0 gates Phase 3 and can reshape Phase 2.** Everything else is stable regardless of
what it finds.

---

## 5. The capture engine

### 5.1 Ring buffer

Fixed-size pool of pre-allocated `IOSurface`-backed buffers. **No allocation on the capture
path, ever.** Pool size derived from the probe's measured write throughput; target ~0.5 s of
headroom.

On pool exhaustion: **drop one frame, increment the counter, surface it on screen.** Never
stall, never hide it. A visible drop count is the difference between a tool you trust and one
you don't.

### 5.2 Recording format decision

**Record `.fcr` always. CinemaDNG is an export from the library, never a capture mode.**

CinemaDNG at capture time would mean ~24 file creates per second plus per-frame header
construction on the capture path — on a device that also has to compress 500 MB/s and offload
over USB 2. Converting afterwards gives full DaVinci Resolve interop without paying for it
during the take, when headroom is scarcest.

### 5.3 The `.fcr` container

Append-only, crash-resilient by construction.

```
┌──────────────────────────────────────────────┐
│ Header — 4096 bytes, fixed                   │
│   magic "FCR1", version, flags               │
│   width, height, bitDepth, cfaPattern        │
│   frameRate numerator / denominator          │
│   blackLevel[4], whiteLevel[4]               │
│   colorMatrix1, colorMatrix2, asShotNeutral  │
│   lensId, focalLength35, aperture            │
│   intrinsicMatrix (3×3)   ← see Appendix A   │
│   readoutTimeNs           ← see Appendix A   │
│   oisEnabled (bool)       ← see Appendix A   │
│   startTimecode, createdAt, deviceModel      │
├──────────────────────────────────────────────┤
│ Frame record ×N                              │
│   marker  "FRM0" (u32)                       │
│   sequence (u32)                             │
│   ptsHostTimeNs (u64)   ← host clock         │
│   exposureNs (u32), iso (u16)                │
│   lensPosition (f32)                         │
│   payloadBytes (u32), crc32 (u32)            │
│   payload — Rice-coded Bayer, strip-parallel │
├──────────────────────────────────────────────┤
│ Index — appended at Finalize                 │
│   frameCount, [offset:u64, size:u32] × N     │
│   trailer "FCRX" + indexOffset:u64           │
└──────────────────────────────────────────────┘
```

**Crash recovery:** if the trailer is absent or the index is unreadable, a repair scan walks
the file matching `FRM0` markers and validating CRCs, rebuilding the index. **A crash costs
exactly one frame** — the one in flight. Recovered clips appear in the library flagged
`RECOVERED`.

### 5.4 Lossless compression

Mandatory, not an optimisation. 504 MB/s must become ~200 MB/s. This is the **highest-risk
component in the build.**

LZ-family compression is useless here — sensor noise yields ~1.1:1. A predictor is required:

1. **Deinterleave** the Bayer frame into four planes (R, G1, G2, B). Same-colour neighbours
   correlate; adjacent Bayer pixels do not.
2. **Predict** with the MED / LOCO-I predictor (as in JPEG-LS) from left, above, and
   above-left neighbours.
3. **Entropy-code** residuals with Rice/Golomb, adaptive *k* per 512-sample block.
4. **Parallelise** by horizontal strips, one per core, with per-strip offsets in the payload
   header. A16 has 2 performance + 4 efficiency cores.

Expected ratio 2.2–2.6:1 on typical footage, consistent with RAW Cam's published ~12 GB/min.

**Fallback if throughput targets are missed:** drop to 4K crop (350 MB/s uncompressed) or
reduce to 18 fps. Both are preferable to dropping frames.

### 5.5 The motion sidecar

Written to a **separate append-only `.fcm` file** during recording, so a crash preserves it
independently of the video container.

- **Gyro at 200 Hz**, timestamped on `CMClockGetHostTimeClock` — the *same clock* as frame PTS.
  Uncorrelated clocks are the classic silent failure in this domain.
- **Accelerometer at 200 Hz** (for horizon and future translational refinement).
- Per-frame: exposure duration, ISO, lens position, PTS (also in the video container, for
  redundancy).
- Gaps in gyro delivery are recorded explicitly as marked spans, not interpolated away.
- **Gyroflow-compatible GCSV export** from the library, so the user is never locked into our
  own stabilizer.

**OIS must be disabled while recording** when post-stabilization is intended. Optical
stabilization moves the lens in ways the gyro cannot observe, so a gyro-derived correction
fights motion that has already been partly cancelled. This is a correctness requirement, not a
preference — and is why RAW Cam ships an OIS toggle. The header records the OIS state so the
stabilizer can refuse to run on footage shot with it on.

---

## 6. Monitoring

### 6.1 Two truths, kept separate

RAW Cam's preview lies because it is tone-mapped for viewing, and its histogram is computed
from that same tone-mapped preview. It describes the picture on screen, not the data on disk.

| Path | Source | Answers |
|---|---|---|
| Preview | Debayered → selected look LUT | "What will this shot look like?" |
| Scopes | Same signal, user-selectable scene- or display-referred | "Where are my values sitting?" |
| **Clipping** | **Raw sensor values, pre-debayer, per CFA channel, vs. calibrated white level** | "Am I actually losing data?" |

The third row is the one that matters. Clipping is a property of the sensor well, not of the
picture. Per-lens white-level calibration is required for it to be true — RAW Cam added
exactly this in v1.1, having learned it the hard way.

**Where white and black levels come from.** Two sources, in priority order:

1. **Per-frame sensor metadata**, when iOS provides it (`kCVImageBufferBlackLevelKey` and
   equivalent RAW attachments). Authoritative when present, and it tracks gain changes.
2. **A stored per-lens calibration**, when it is not. This is a short user-run routine —
   shoot a deliberately over-exposed flat field per lens, record the measured per-channel
   saturation point — stored in app preferences and keyed by lens identity.

**The probe must report which of these is available on this device** (added to §4.1). If (1)
is present, (2) becomes an optional refinement rather than a v1 requirement; if it is absent,
(2) is required for the clipping indicator to mean anything, and the indicator must display a
"uncalibrated" state until the routine has been run for the active lens. Showing a confident
clipping indicator built on a guessed white level would be the exact failure this app exists
to fix.

### 6.2 GPU budget

| Consumer | Resolution | Rate | Cost |
|---|---|---|---|
| Recorder | 4032×3024 | 24 fps | The budget |
| Preview | 1008×756 (¼) | 24 fps | Bilinear/Malvar debayer — cheap |
| Waveform / vectorscope / histogram | **504×378 (⅛)** | **10 Hz** | ~0.19 MP per pass — trivial |
| False colour · zebras · peaking | free-riding in preview shader | 24 fps | ≈0 |

False colour, zebras and focus peaking are per-pixel functions of values the preview shader has
already computed — LUT applications, not passes. Toggling one must be as safe as changing a
colour. Everything renders from **one sensor readout**, fanned out by `FrameBroker`. Never a
second `AVCaptureOutput`.

### 6.3 Scope implementations

- **Histogram** — 256 bins × 4 channels, Metal compute with atomics.
- **Waveform** — per-column luma histogram into a 504×256 texture; luma and RGB parade modes.
- **Vectorscope** — 256×256 accumulation in (Cb, Cr), with graticule and skin-tone line.
- **False colour** — luma → colour LUT post-look, with an IRE-calibrated key on screen.
- **Zebras** — threshold on post-look luma, user-set IRE.
- **Focus peaking** — Sobel magnitude on preview luma, thresholded, tinted.
- **Raw clipping** — pre-debayer per-channel comparison against `whiteLevel − margin`,
  accumulated as a coarse ⅛-res mask and overlaid.

### 6.4 Look presets

3D LUTs (`.cube`) applied in the same shader as the debayer. Rec.709, Rec.709 + Cineon,
log curves, and film emulations. Adding a preset costs a file and a picker row — near-zero
runtime cost, and the cheapest differentiation available.

### 6.5 Degradation ladder

When thermal pressure or write backpressure rises, budget is spent in a fixed, **published**
order:

```
scopes 10 Hz → 5 Hz → 2 Hz
   → preview 24 → 12 fps
      → preview resolution ⅛
         → scopes off
            → (only now) consider dropping recorded frames
```

The status bar states which rung it is on, in words. The recording is the last thing to
suffer, and the operator always knows before it does.

---

## 7. Control surface

**Layout: instrument panel** (Blackmagic Camera lineage). Full camera state readable at rest;
nothing hidden.

### 7.1 At rest

- **Top bar:** record state + timecode · format badge (`12MP OPEN GATE · 24.00p · 14-BIT · FCR`)
  · thermal state · **storage runway in minutes** · drop counter.
- **Viewfinder:** full bleed, optional grids and horizon.
- **Bottom strip:** chips for ISO · SHUTTER · WB · FOCUS · LENS · LOOK, each showing its
  current value.
- **Record button:** bottom right, thumb-reachable in landscape.
- **Scopes:** docked right, collapsible.

Details that matter:

- **Storage in minutes, not gigabytes.** Minutes is the number the operator needs.
- **Drop counter reads `—` before rolling, `0` once rolling.** A fake zero is a lie.
- **Manual focus is the default**, because AF during recording does not exist on this path.

### 7.2 Engaged

Tapping a chip raises a **scrubber above the strip** — never a modal, never a pushed screen,
and the viewfinder never shrinks. Haptic detent per stop, stronger detent at native ISO. The
active chip stays lit. Tap elsewhere to dismiss.

### 7.3 Rolling

**Exposure stays live (ISO, shutter, WB). Lens, focus and look are locked.**

Lens switching mid-take is the documented cause of RAW Cam's freezes; a mid-clip look change
produces footage that cannot be graded consistently. This is strict by design with no
override — an unlockable setting would mean every bug report arrives with an unknown
configuration behind it.

**OIS is not a viewfinder control.** It lives in settings, is locked while rolling like
everything else in that group, and defaults to **off** because post-stabilization is the
intended workflow (§5.5). Turning it on must surface a plain-language warning that footage
shot with OIS active cannot be gyro-stabilized afterwards, and the resulting clips are
flagged in the library. Burying this in a settings toggle with no consequence shown is how
an operator discovers the problem in post instead of on set.

### 7.4 Visual language

Near-black chrome (never pure black). Monospaced digits so numerals do not jitter as they
change. **Red means recording and nothing else.** One accent colour for "active/armed".
Chrome rotates with the device; the viewfinder never does.

---

## 8. Failure handling

### 8.1 State machine

```
Idle → Configuring → Ready → Recording → Finalizing → Ready
```

**`Finalizing` always completes.** Index written, sidecar flushed, file closed. Every exit
from `Recording` routes through it. No code path deliberately leaves a take half-written.

### 8.2 Failure taxonomy

| Failure | Detection | Response |
|---|---|---|
| Writer falls behind | Buffer pool exhausted | Drop one frame, increment counter, flash it |
| Thermal rising | `ProcessInfo.thermalState` | Walk the degradation ladder, announce each rung |
| Thermal critical | `thermalState == .critical` | **Stop cleanly at our threshold**, before iOS kills the session |
| Storage low | Runway < 30 s | Stop cleanly with margin. Never fill the disk |
| Call / Control Center / backgrounding | `AVCaptureSession` interruption notifications | Stop cleanly, flag clip as interrupted |
| Crash or force-quit | Orphaned `.fcr` at next launch | Repair scan rebuilds index; clip flagged `RECOVERED` |
| Gyro dropout | Sample gap in sidecar | Mark the span; stabilizer flags rather than guesses |
| Probe/reality mismatch | Format negotiation fails at runtime | Fall back down the `CaptureSource` chain, tell the user which path is active |

---

## 9. Testing

`FileBackedSource` is what makes this testable at all.

| Test | Approach | Runs headless? |
|---|---|---|
| **Scope correctness** | Synthetic luma ramps and colour bars have provably correct waveforms and vectorscope plots. Assert against ground truth. | Yes |
| **Rice codec** | Property test: generate sensor-like noise, encode, decode, assert bit-identical. Thousands of iterations. | Yes |
| **Container repair** | Truncate `.fcr` at 1000 random offsets; assert every complete frame recovers and no partial frame is ever returned. | Yes |
| **Drop accounting** | Replay a known sequence at exact 24 fps with an artificially throttled writer; assert the counter matches exactly. | Yes |
| **Clock correlation** | Gyro↔frame alignment is pure math on recorded data. | Yes |
| **Degradation ladder** | Inject synthetic thermal/backpressure states; assert rung order and that recording is never sacrificed first. | Yes |
| **Sustained capture** | 10-minute take on device, assert zero drops and index integrity. | No |
| **Thermal soak** | Record until degradation; verify announced rungs match observed behaviour. | No |

None of this needs a camera. Most of it needs a Mac — but the codec and container tests are
written first as a platform-agnostic reference implementation in Stage W (§10), so their
assertions exist before any Swift does.

---

## 10. Build order

Ordered by **what each phase actually requires**, so that no time is spent waiting on hardware
that isn't needed yet. Three distinct gates: a Mac, and a device.

### Stage W — no Mac required (start immediately, on Windows)

The container and codec are pure data algorithms with nothing Apple-specific about them. Built
here as a reference implementation in Rust or Python, they produce **conformance test vectors**
that the later Swift port must match bit-for-bit — turning the riskiest port in the project
into a verification exercise.

| Phase | Deliverable | Why it can happen now |
|---|---|---|
| **W1** | `.fcr` container reference implementation: writer, reader, index rebuild, repair scan | Pure byte-layout work |
| **W2** | **Rice codec reference implementation, and a measured compression ratio on real Bayer data** | Pure algorithm. **Settles the project's biggest open assumption** — see below |
| W3 | Synthetic test assets: Bayer ramps, colour bars, noise fields, simulated motion sequences | Input data for `FileBackedSource` |
| W4 | Look LUT library (`.cube`), false-colour IRE mapping tables | Data files, platform-agnostic |
| W5 | Scope ground truth: expected histogram / waveform / vectorscope output for each W3 pattern | These become the test assertions in P5 |
| W6 | Conformance vector suite covering W1–W2 | The Swift port's acceptance criteria |

**W2 is the priority.** The design assumes 2.2–2.6:1 lossless compression, inferred from RAW
Cam's published ~12 GB/min. If the true figure on this sensor is nearer 1.6:1, 12 MP at 24 fps
does not fit and the primary mode must change. Resolving this needs **real Bayer frames from an
iPhone 15**, obtainable without a Mac by shooting a short clip in RAW Cam ($11.99) and
exporting the DNGs. Cheapest possible de-risking of the highest-risk component.

### Stage M0 — first day with a Mac (one afternoon)

| Phase | Deliverable | Requires |
|---|---|---|
| **P0** | `CapabilityProbe` + `FilmCamProbe` target *(disposable)* | Mac + device |

Runs before anything else is written, because it gates P3, reshapes P2, and answers every
question in Appendix B. It is an afternoon of work that can invalidate months of assumptions.

### Stage M1 — Mac, no device needed

Everything here is developed and tested against `FileBackedSource` and the Stage W assets.
This is the bulk of the application.

| Phase | Deliverable |
|---|---|
| P1 | `CaptureCore`, `Frame` model, `FrameBroker`, `FileBackedSource` |
| P2 | Swift port of `.fcr` + Rice codec, **validated against W6 vectors**; ring buffer; repair scan |
| P4a | Viewfinder: preview debayer + look LUTs, rendered offscreen and compared against W3/W5 |
| P5a | `ScopeEngine`: histogram, waveform, vectorscope, false colour, zebras, peaking, raw clipping — asserted against W5 ground truth |
| P6a | Control surface, telemetry, degradation ladder — driven by injected synthetic thermal and backpressure states |
| P7 | Minimal library, `.fcr` → CinemaDNG export, GCSV export |

### Stage M2 — Mac + device

| Phase | Deliverable |
|---|---|
| P3 | `BayerVideoSource` / `PhotoBurstSource`, selected by P0's results |
| P4b | Viewfinder validation against live sensor output |
| P5b | Scope validation against real scenes; per-lens white-level calibration routine |
| P6b | Control surface on-device passes; real thermal soak against the announced degradation ladder |
| P8 | Sustained-capture acceptance: 10-minute take, zero drops, index integrity |

### Dependency notes

- **P0 gates P3 and can reshape P2.** Nothing else depends on its results.
- **Stage W gates nothing but de-risks everything.** If W2 finds the compression ratio is
  insufficient, §2.1's primary mode changes before any Swift is written.
- Stage M1 is roughly 70% of the application and needs no camera at all — a direct dividend of
  the `FileBackedSource` design in §3.2.

---

## Appendix A — What stabilization (subsystem D) needs from v1

Subsystem D is not being built now, but v1 must record enough for it. This appendix exists to
prove sufficiency before the data is unrecoverable.

### A.1 Algorithm sketch

Gyro-driven rolling-shutter-aware warp:

1. **Integrate** gyro samples into an orientation quaternion trajectory `q(t)`.
2. **Smooth** that trajectory into `q_smooth(t)` under a crop constraint — the smoothed path
   may not demand more margin than the frame has.
3. **Per output frame, per scanline** `y`, compute the sample time
   `t = pts + (y / height) × readoutTime`, then the correction rotation
   `R(t) = q_smooth(t) · q(t)⁻¹`.
4. **Warp** with a per-scanline homography `x' = K · R(t) · K⁻¹ · x`, where `K` is the camera
   intrinsic matrix. In practice, evaluate per N scanlines and interpolate.
5. **Crop** to hide the resulting edges.

This runs as a Metal fragment shader over the debayered frame inside subsystem C's pipeline —
no real-time constraint, which is exactly why deferring it is the right call.

**Open gate is what makes this work.** Gyro correction pushes content off the frame edge;
crop margin is the budget. Recording the full sensor area maximises that budget, which is
why open gate and post-stabilization are a designed pair rather than two separate features.

### A.2 Required inputs, and where v1 records them

| Input | Why | Where |
|---|---|---|
| Gyro @200 Hz, host-clock timestamps | The trajectory itself | `.fcm` sidecar |
| Frame PTS on the **same clock** | Aligns rotation to frame | `.fcr` frame record + `.fcm` |
| **Rolling-shutter readout time** | Without it, scanlines share one rotation and fast pans wobble | `.fcr` header, from probe |
| **Camera intrinsic matrix `K`** | The homography is undefined without it | `.fcr` header |
| OIS state | Gyro correction is invalid if OIS was active | `.fcr` header |
| Exposure duration | Mid-exposure timestamping; motion-blur awareness | `.fcr` frame record |
| Lens identity / focal length | `K` changes per lens | `.fcr` header |
| Gyro gap markers | Stabilizer must flag, not guess | `.fcm` sidecar |

### A.3 Design change this appendix produced

Writing this surfaced **two fields that were not in the original container design**:

- **`intrinsicMatrix`** — obtainable via `AVCameraCalibrationData` when
  `isCameraCalibrationDataDeliverySupported` is true. **The probe must check availability on
  this device**; if unavailable, we must derive `K` from focal length and sensor dimensions and
  record that fact.
- **`readoutTimeNs`** — added to both the probe's required outputs and the container header.

Both are now in §4.1 and §5.3. This is the value of writing the appendix before building.

### A.4 Known limitation

Gyro correction handles **rotation only**. Translational shake (walking, handheld drift) needs
optical flow, which subsystem D may add later as a refinement pass. Nothing in v1's recorded
data prevents that — optical flow is computed from the frames themselves.

---

## Appendix B — Open questions the probe resolves

These are unanswerable from a Windows machine and are the reason Phase 0 exists.

1. **Does the iPhone 15 vend `14Bayer_*` through `AVCaptureVideoDataOutput`?** Determines
   `BayerVideoSource` vs `PhotoBurstSource` — the single highest-impact unknown.
2. **Does `VTCompressionSession` offer ProRes on a non-Pro device?** Apple gates ProRes
   *capture* to Pro models; whether the *encoder* is gated is genuinely unknown. Determines
   whether ProRes output survives into subsystem C.
3. **Which HEVC profiles encode in hardware?** 10-bit 4:2:0 is certain; 4:2:2 is unlikely;
   4:4:4 almost certainly absent.
4. **Sustained write throughput under thermal load.** Determines ring buffer size and whether
   12 MP or 4K crop is the primary mode.
5. **Is `AVCameraCalibrationData` delivered on this device/format?** See A.3.
6. **Per-format rolling-shutter readout time.** See A.3.
7. **Where is the thermal knee?** Converts take-length guesses into a number.
8. **Are per-frame black/white level attachments delivered?** Determines whether the manual
   per-lens calibration routine (§6.1) is a v1 requirement or an optional refinement.

---

## Appendix C — Requirements captured for later subsystems

Recorded here so they are not lost, though they are out of scope for v1:

- **Subsystem C outputs:** HEVC 4:2:0, HEVC 4:4:4, ProRes — subject to Appendix B items 2–3.
  HEVC 4:4:4 is expected to become a desktop-export path.
- **Colour presets:** Rec.709, Rec.709 + Cineon, and a broader library in the Log Cam mould.
  Cheap to add; see §6.4.
- **CinemaDNG export** from `.fcr` — §5.2.
- **GCSV export** for Gyroflow — §5.5.
