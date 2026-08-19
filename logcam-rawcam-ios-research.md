# Deep Research: Log Cam & RAW Cam on iOS

**Compiled:** 19 August 2026
**Subject:** `RAW Cam: Open Gate DNG Video` and `Log Cam: Open Gate by RAW Cam` — two iPhone camera apps by Lead the way (Sebastijan Grabar), Zagreb, Croatia.
**Data current as of:** RAW Cam v1.8 (24 Jul 2026) · Log Cam v1.4 (9 Jul 2026)

---

## 0. Disambiguation — read this first

"RawCam" is an ambiguous name on the App Store. There are at least two unrelated apps:

| App | Developer | What it is | ID |
|---|---|---|---|
| **RAW Cam: Open Gate DNG Video** | Lead the way, vl. Sebastijan Grabar | **RAW *video*** (CinemaDNG / MCRAW). The one paired with Log Cam. | `6755047834` |
| RawCam – Raw DNG Camera | Santiago Alonso Alexandre | RAW *stills* (12 MP DNG) + basic clean HEVC video. Free. Unrelated. | `6765531876` |

Because the question paired it with "LogCam", **this document covers the Lead the way pair.** The stills-oriented `RawCam – Raw DNG Camera` is noted in §10 for completeness only.

Also not covered (different apps, similar names): `Loga - Log Still Cam`, `OpenCam`, `srRAW Cinema Camera`, `LogGate`.

---

## 1. Executive summary

Both apps do one unusual thing that defines everything else about them: **they do not use Apple's video capture pipeline at all.**

Every other iOS video app — Blackmagic Camera, Kino, Final Cut Camera, Mavis — receives frames from `AVFoundation`'s video streams (Rec.709, Rec.2020, and on 15/16/17 Pro, Apple Log). By the time a third-party app touches those frames, Apple's ISP has already baked in noise reduction, sharpening, tone mapping, contrast and saturation. That processing is irreversible.

Lead the way's apps instead pull a **continuous stream of full RAW photo frames** — the same sensor data path used for RAW DNG stills — and debayer it themselves, on device, in real time, at up to 30 fps.

The consequences fall out of that one decision:

- **RAW Cam** writes that stream straight to disk as CinemaDNG / DNG sequences or MCRAW — genuinely unprocessed Bayer data.
- **Log Cam** debayers the same stream and encodes it on device to ProRes or 10-bit HEVC in a log curve of your choice (Apple Log, Apple Log 2, ARRI LogC3, Sony S-Log3, Panasonic V-Log, Fuji F-Log/F-Log2), plus Rec.709 / HLG / PQ.
- Because they bypass Apple's video path, they also bypass **Apple's artificial feature gating**: ProRes on non-Pro iPhones, open gate on phones Apple never enabled it for, Apple Log on hardware that officially has no Log.
- The cost is severe: **no autofocus while recording, no EIS, max 30 fps, heavy thermal load, short takes, and stability that varies a lot by device.**

Both are **one-time purchases with no subscription** — unusual in this category and a large part of their appeal.

**Verdict in one line:** rough, early, occasionally unstable software from a solo developer that nonetheless produces the cleanest image available from an iPhone — including iPhones several generations old — and is cheap enough that trying it is close to a no-risk decision.

---

## 2. The developer

- **Studio:** Lead the way, vl. Sebastijan Grabar — a one-person operation based in Zagreb, Croatia.
- **Site:** [leadtheway.hr/rawcam](https://leadtheway.hr/rawcam/)
- **Channels:** [YouTube @RAWCamVideo](https://www.youtube.com/@RAWCamVideo), [Instagram @raw_cam_](https://www.instagram.com/raw_cam_/)
- **Privacy posture:** Apple's privacy card for both apps reads **"Data Not Collected."**
- **Responsiveness:** visible in the record. A May 2026 App Store review complaining about the lack of manual white balance drew a developer response ("White balance was added in the latest version") — and v1.7 shipped manual WB. Release cadence has been roughly monthly since launch.

This matters for risk assessment: it is a solo project, so bus-factor and long-term support are real considerations, but the iteration rate and direct engagement have been unusually good.

---

## 3. The core technical idea

### 3.1 What Apple gives third parties vs. what these apps take

```
Standard iOS video app:
  sensor → Apple ISP (NR, sharpening, tone map, HDR, saturation) → video stream → your app
                                    └── irreversible, baked in

RAW Cam / Log Cam:
  sensor → RAW photo frames (Bayer, unprocessed) → app's own debayer/encode → file
                                                    └── you control everything downstream
```

The RAW photo stream is the same one behind ProRAW/DNG stills. Apple exposes it for *photography*; these apps run it continuously at video rates and treat each frame as a video frame.

### 3.2 Why this unlocks features Apple "blocks"

Apple's restrictions on the video pipeline (ProRes only on Pro models, Apple Log only on 15 Pro and later, Apple Log 2 only on 17 Pro, open gate only on recent hardware) are **policy applied to that pipeline**, not universal hardware limits. Since these apps never enter that pipeline, the restrictions do not apply. Hence:

- 4K open gate recorded **internally** on iPhones Apple never allowed it on
- **ProRes to internal storage** on non-Pro iPhone 13/14/15
- **Apple Log 2, ARRI LogC3, S-Log3, V-Log, F-Log/F-Log2** on devices with no official Log stream at all
- Log video on hardware as old as the iPhone XS

Epic Tutorials' framing is fair: *"Apple's video restrictions are not entirely determined by hardware. Log Cam proves it."*

### 3.3 What it costs

Debayering and encoding up to 30 full-resolution RAW frames per second in real time is an extraordinary sustained load on a phone SoC. Everything in §7 (Limitations) follows directly from this. There is no clever fix coming; it is the price of the architecture.

---

## 4. RAW Cam: Open Gate DNG Video

### 4.1 Store facts

| Field | Value |
|---|---|
| Bundle ID | `hr.leadtheway.rawvideocamera` |
| Price | **$11.99 one-time**, no subscription, no IAP |
| Version | 1.8 (24 Jul 2026) |
| First released | 17 Dec 2025 |
| Min iOS | **17.0** |
| App size | 8.7 MB |
| Rating (US) | **4.7 / 5** from 21 ratings |
| Category | Photo & Video / Utilities |
| Family Sharing | Yes |

### 4.2 Capture

- **Formats:** DNG image sequences (CinemaDNG-style) and **MCRAW** (MotionCam's losslessly compressed single-file RAW container)
- **Framing modes:** open gate full sensor · open gate half resolution · classic 16:9 in 4K · Full HD
- **Frame rates:** 18 / 24 / 25 / 30 fps
- **Exposure:** full manual ISO + shutter; **shutter-priority mode** (locked 180° shutter angle with auto ISO)
- **White balance:** manual (added v1.7)
- **Focus:** manual with focus-distance slider and punch-in zoom; tap-to-focus and continuous AF **before** rolling only
- **Timecode:** included in DNG output
- **Stabilization:** optical / sensor-shift only (toggleable); **Gyroflow GCSV** gyro data export for post stabilization
- **Audio:** audio-input selector supporting Bluetooth and wired microphones

### 4.3 Monitoring & assists

Histogram with highlight-clipping indicator · per-lens calibration for accurate clipping · horizon indicator · rule-of-thirds grid · available-storage indicator with auto-stop on low storage · 180° image flip for DoF adapters.

**No waveform, no false color, no zebras** — those live in Log Cam, not RAW Cam.

### 4.4 Storage & transfer

Internal app gallery · user-chosen Files folders · **external SSD** · on-device playback of both internal and external clips · AirDrop hand-off (developer tip: enable Personal Hotspot and connect the receiving device to it for max transfer speed) · Bluetooth trigger to start/stop recording (volume-up implementations only).

### 4.5 Version history — what it tells you

| Ver | Date | Notable |
|---|---|---|
| 1.0 | 17 Dec 2025 | Launch |
| 1.1 | 14 Jan 2026 | 30 fps · histogram + clipping indicator + lens calibration · storage indicator · **in-app video playback** · external storage gallery · frame-drop fixes |
| 1.1.1 | 24 Jan 2026 | Wide-angle lens frame-rate fix · DNGs now pass DNG Validator |
| 1.2 | 11 Feb 2026 | **Direct DNG writing** (~10–15% smaller than via MCRAW) · stabilization toggle |
| 1.2.1 | 14 Feb 2026 | Stabilization toggle pulled — broke recording on some devices |
| 1.3 | 26 Feb 2026 | **Gyroflow GCSV** · OIS/sensor-shift toggle returns · horizon indicator · 0.5× lens fix |
| 1.4 | 13 Mar 2026 | Volume-button and Bluetooth shutter |
| 1.5 | 28 Mar 2026 | Manual-focus zoom · audio-input selector |
| 1.6 | 8 Apr 2026 | Performance |
| 1.7 | 11 May 2026 | **Shutter-priority (180° + auto ISO)** · **manual white balance** · 180° flip for DoF adapters |
| 1.8 | 24 Jul 2026 | iPhone XS recording fix |

The v1.2.1 rollback is a useful signal: features do occasionally ship broken and get pulled. Treat new releases with the caution you'd give any solo-dev capture tool before a paid job.

---

## 5. Log Cam: Open Gate by RAW Cam

### 5.1 Store facts

| Field | Value |
|---|---|
| Bundle ID | `hr.leadtheway.logvideocamera` |
| Price | **Free download · 10-day trial · $13.49 one-time "Unlock Full App"** |
| Optional | Donation tiers at $5 / $10 / $15 / $25 / $50 / $100 |
| Version | 1.4 (9 Jul 2026) |
| First released | 8 Jun 2026 |
| Min iOS | **17.4** |
| App size | 12.3 MB |
| Rating (US) | **4.0 / 5** from 40 ratings |

Note: the trial clock starts **at first download**, not at first launch. Don't install it until you can actually test it.

### 5.2 Codecs & color

- **Codecs:** ProRes · 10-bit HEVC 4:4:4 · 10-bit HEVC 4:2:0, bitrate configurable **up to 300 Mbps**
- ProRes works on **iPhone 13 and later including non-Pro** — Apple restricts ProRes to Pro models
- **Log curves:** Apple Log, **Apple Log 2**, ARRI LogC3, Sony S-Log3, Panasonic V-Log, Fuji F-Log, Fuji F-Log2
- **Other transfer/color:** Rec.709, HLG, PQ
- **Modes:** Open Gate or 4K
- **Frame rates:** up to 30 fps
- **LUTs:** drop `.cube` files into the `_LUTs` folder via the Files app; apply as monitor-only or **bake into the recording**; v1.4 adds the option to tag a baked output as Rec.709

HEVC 4:4:4 is the standout: full chroma resolution per pixel, grading latitude close to ProRes, at a fraction of the file size. Very few mobile apps offer it.

### 5.3 Monitoring

Accurate log preview · accurate LUT preview · **zebras** · **false color** · **Rec.709 gamma assist** for log · RAW linear histogram · horizon indicator · 3×3 grid.

This is the meaningful functional gap vs. RAW Cam — Log Cam is the one with real on-set exposure tools.

### 5.4 Image processing & rig features

Vignette correction · noise reduction · **anamorphic desqueeze** (v1.4) · 180° rotation for DoF adapters · optical stabilization · external microphone support · Gyroflow GCSV · internal or external storage.

### 5.5 Controls

Manual ISO/shutter or auto with **lock-at-start** · shutter-priority mode · **EV slider for auto-exposure** (v1.4) · manual focus **before recording only** · manual WB or auto with lock-at-start.

### 5.6 Version history

| Ver | Date | Notable |
|---|---|---|
| 1.0 | 8 Jun 2026 | Launch |
| 1.1 | 12 Jun 2026 | Fix: recording failed on XS/XR |
| 1.2 | 14 Jun 2026 | Fix: settings freeze |
| 1.3 | 18 Jun 2026 | Fix: iOS 17 settings · ProRes availability on some devices |
| 1.4 | 9 Jul 2026 | **Anamorphic desqueeze** · EV slider for AE · fixed monitor/output-file discrepancy · Rec.709 output tag · per-device performance work |

Three bugfix releases in the first ten days. Log Cam is roughly six months younger than RAW Cam and its 4.0 rating vs. RAW Cam's 4.7 reflects that.

---

## 6. Side by side

| | **RAW Cam** | **Log Cam** |
|---|---|---|
| Purpose | Maximum post flexibility | Edit-ready delivery files |
| Output | DNG / CinemaDNG sequences, MCRAW | ProRes, HEVC 4:4:4, HEVC 4:2:0 (≤300 Mbps) |
| Color | None baked — RAW | Apple Log / Log 2, LogC3, S-Log3, V-Log, F-Log, F-Log2, Rec.709, HLG, PQ |
| Framing | Open gate (full & half res), 4K 16:9, Full HD | Open gate, 4K |
| Frame rates | 18 / 24 / 25 / 30 | up to 30 |
| Monitoring | Histogram + clipping, horizon, grid | False color, zebras, Rec.709 assist, LUT preview, RAW linear histogram |
| LUTs | — | Monitor-only or baked in |
| Image tools | 180° flip | Vignette correction, NR, anamorphic desqueeze, 180° flip |
| Timecode | Yes (in DNG) | Not documented |
| Gyroflow GCSV | Yes | Yes |
| External SSD | Yes | Yes |
| Ext. microphone | Yes | Yes |
| File sizes | Enormous (~12 GB/min at 4K open gate) | Manageable |
| Price | $11.99 up front | Free + $13.49 unlock, 10-day trial |
| Min iOS | 17.0 | 17.4 |
| Rating | 4.7 (21) | 4.0 (40) |
| Maturity | Dec 2025, v1.8 | Jun 2026, v1.4 |

**Choosing between them:** RAW Cam if you are finishing in DaVinci Resolve with Camera RAW controls, doing VFX, or need maximum highlight recovery. Log Cam if you want files you can cut immediately, monitoring assists on set, or a log image that intercuts with other cameras. Many people will end up owning both — combined they run about $25.

---

## 7. Limitations — the honest list

These are structural, not bugs, and mostly follow from the real-time RAW transcode.

### Both apps
1. **No autofocus while recording.** Set focus before you roll; it cannot be pulled mid-clip. This is the single most-cited complaint in user reviews.
2. **No electronic image stabilization.** OIS / sensor-shift only. Gyroflow in post is the intended answer, and open gate exists partly to give it crop margin.
3. **Max 30 fps.** No 60p, no slow motion.
4. **Thermal-limited take length.** Shorter continuous recording than conventional video apps. Reported range is wide: one account cites **4–5 minutes** of 4K open gate on older phones before dropped frames; another reports an **iPhone 12 running 43+ minutes** at 4K in sunlight without drops. Test your own device, your own settings, your own ambient temperature.
5. **Manual focus is unreliable at slow shutter speeds**, and focus adjustment during recording can destabilize capture.
6. **The live preview is tone-mapped, not the RAW image.** Expose using the clipping indicators / false color, not by eye.
7. **Early-software stability.** Freezes when switching lenses after changing settings; crashes when toggling false color/zebras mid-adjust (reported on base iPhone 15); "video processing error" reports on iPhone 11 (reported fixed by mid-July 2026).

### RAW Cam specifically
8. **File sizes are brutal** — roughly **12 GB per minute** at 4K open gate. Plan storage and transfer time accordingly.
9. **MCRAW is not natively readable by most NLEs** (see §9 for the workaround).
10. **No vignette correction in-app** — fix in post. (Log Cam has it.)
11. ISO ceiling was reported capped around 495 in early builds; verify on current version.
12. No false color / zebras / waveform.

### Log Cam specifically
13. **Trial starts at download**, not first launch.
14. No audio meters, no metering modes, thin UI compared to Mavis or Blackmagic Camera.
15. Focus can only be set pre-roll, same as RAW Cam.

### What these apps are *not* for
Run-and-gun, continuous AF, slow motion, long uninterrupted takes, live streaming. For those, Blackmagic Camera, Kino, Mavis or Final Cut Camera remain the right tools. These apps are for **controlled, deliberate work**: interviews, short films, commercial and product shoots, landscape and locked-off cinematography.

---

## 8. The "true Apple Log 2" claim — examined

The marketing headline, repeated by the developer and by reviewers, is that Log Cam delivers *genuine* Apple Log 2 on iPhones Apple never enabled it for. CineD's Nino Leitner examined this against Apple's own white papers, and the analysis is worth internalizing:

**What Apple publishes, and what it means:**

- The **Apple Log Profile White Paper (Sept 2023)** and the **Apple Log 2 White Paper (Sept 2025)** define the **exact same transfer function** — a log curve transitioning smoothly into a parabola at the low end to capture negative signal values and preserve sensor noise — with identical encoding constants: 18% gray at 10-bit full-range code value **500**, clipping at **1200% scene reflection**.
- **Apple Log 2 therefore adds no dynamic range.** Claims of a new shadow curve or softer highlight roll-off in Log 2 are *not* supported by Apple's documentation.
- What actually changed in Log 2 is the **gamut**. Original Apple Log = BT.2020 primaries, D65. Apple Log 2 = **Apple Wide Gamut**, still D65, with published chromaticities: red at x 0.725 / y 0.301, green at 0.221 / 0.814, blue at **0.068 / −0.076** — a negative coordinate, an imaginary primary outside the visible spectrum. This is the same mathematical device ACES and ARRI Wide Gamut use to encode deeply saturated blues and violets without clipping, and it is where Log 2's advantage under neon and stage lighting comes from.

**The verdict on the claim:**

Because Apple publishes both the curve constants and the gamut coordinates, **Log Cam's Apple Log 2 implementation can in principle be mathematically exact.** The claim is not marketing vapor.

**But** — and this is the caveat that matters operationally — what Apple does *not* publish is **how each iPhone sensor's native spectral response is characterized and transformed into that space.** That upstream color science is proprietary, and it is precisely where a Log Cam capture would diverge from a genuine iPhone 17 Pro capture.

> **Practical takeaway:** treat intercutting Log Cam footage with real iPhone 17 Pro Apple Log 2 footage as **something to test, not assume.** Shoot a matching chart/scene on both, grade them side by side, and confirm before you build a multi-camera job around it.

**On the blind-test claim:** one reviewer ran a ~4.5-year-old iPhone 13 Mini on Log Cam against an iPhone 17 Pro shooting ProRes RAW and reported every viewer preferred and misidentified the older phone's footage. CineD's framing is the correct one — that is **one reviewer's single subjective test, not a controlled measurement.** It is suggestive, not evidence.

---

## 9. Post-production workflow

### 9.1 RAW Cam → DaVinci Resolve (CinemaDNG)

DNG sequences give you full **Camera RAW** controls in Resolve (free version included):

- proper highlight decode and clipped-channel recovery
- sharpening set to zero (or wherever you want it)
- non-destructive exposure adjustment
- choice of working color space — convert to **ARRI LogC**, **Blackmagic Film Gen 5**, or **P3-D60**, then apply professional cinema LUTs designed for real cameras

This is the entire point of the RAW Cam workflow, and it's why footage from a several-generation-old iPhone can hold up against much more expensive sources.

### 9.2 MCRAW — why it's interesting and how to use it

**MCRAW** is the container built by Mirsad Makalic for the Android app MotionCam Pro. It is a **single-file, losslessly compressed RAW container**:

- MotionCam's own figure: 30 frames at 4000×3000 = **234 MB in MCRAW** vs. **686 MB as uncompressed DNGs** — roughly a two-thirds reduction in that example. Their docs elsewhere cite ~50% savings vs. uncompressed RAW generally.
- The compression is **lossless**, which distinguishes it from ProRes RAW (whose compression is applied to the RAW data at capture).
- **White balance is stored as metadata, not baked in.**

**The hurdle:** most NLEs don't read MCRAW natively.

**The fix:** [**MotionCam Tools**](https://motioncamapp.com/tools) — free desktop companion that **mounts `.mcraw` files as a virtual CinemaDNG sequence**, so they appear directly in DaVinci Resolve, Premiere Pro and any other DNG-capable editor with **no conversion step and no duplicate files.**

- macOS: fully virtual mount
- Windows: small cache handles it
- Playback scrubbed on GPU
- Lets you set frame rate, crop, exposure compensation, vignette correction and log transforms **before the editor ever sees the footage**
- Can generate downscaled proxies for editing ahead of a full-quality render
- A community fork adds further options

Net effect: an MCRAW file from RAW Cam drops into a Resolve RAW workflow almost as easily as CinemaDNG, at a fraction of the storage.

Note also that RAW Cam v1.2 added **direct DNG writing**, ~10–15% smaller than the previous DNG-via-MCRAW path — so if MCRAW tooling isn't wanted, straight DNG is a first-class option.

### 9.3 Gyroflow stabilization

Both apps export the **GCSV** gyro-data file that [Gyroflow](https://gyroflow.xyz) needs.

The open gate + Gyroflow combination is deliberate, not incidental. Gyroflow crops into the frame to hide the black edges that motion correction introduces. **The more sensor area you record, the more margin it has before the final 16:9 crop.** Gyroflow's own guidance is to record the widest aspect ratio available — which is exactly what open gate gives you. Since neither app offers EIS, this is the intended stabilization pipeline.

### 9.4 Transfer

- External SSD recording avoids the transfer step entirely — strongly recommended for RAW Cam
- AirDrop for device-to-device; developer's tip is to enable Personal Hotspot on one device and connect the other to it for maximum speed
- Files app / user-chosen folders for everything else

---

## 10. Competitive landscape

| App | Approach | Devices | Price | Notes |
|---|---|---|---|---|
| **RAW Cam** | Custom RAW frame pipeline | iOS 17+, practically iPhone 13+ (XS/XR run it) | $11.99 once | Widest device reach, cheapest entry to real RAW |
| **Log Cam** | Same pipeline, encodes to log | iOS 17.4+ | $13.49 once | Only app offering multi-vendor log on old hardware |
| **srRAW Cinema Camera** | Custom engine, 14-bit CinemaDNG + synced WAV | iPhone 15/16 Pro & Pro Max, up to 3K | €39.99 lifetime **or** €3.99/mo · €19.99/yr after 7-day trial | Closest direct competitor (SWISS RIG FlexCo, Vienna). More mature, narrower device range, subscription option |
| **Blackmagic Camera** | Apple's video pipeline | Broad | Free | Far more stable, better UI, full AF/EIS — but ISP-processed image |
| **Kino** | Apple's video pipeline | Broad | Paid | 2024 iPhone App of the Year; excellent UX |
| **Final Cut Camera 2.0** | Apple, first-party | Open gate + Apple Log 2 + ProRes RAW + genlock on 17 Pro | Free | Sanctioned path, newest hardware only |
| **Mavis Camera** | Apple's video pipeline | Broad | Paid | Strong monitoring/LUT tooling |
| RawCam – Raw DNG Camera | RAW **stills** | iOS 17+ | Free | Different developer. 12 MP DNG, RAW+JPG, bracketing, clean HEVC video. Not a cinema tool |

**Against srRAW** — the two genuine arguments for the Lead the way apps are **one-time pricing with no subscription** and **much wider hardware reach** (back to iPhone 13 including non-Pro, vs. srRAW's 15/16 Pro and Pro Max at up to 3K). srRAW is the more polished and mature product with synchronized WAV audio. Neither is automatically better.

**Against Apple's own tools** — Apple's sanctioned Apple Log 2, internal ProRes RAW and genlock remain **iPhone 17 Pro features**; original Apple Log arrived with the iPhone 15 Pro. Enthusiasts have also found an internal ProRes RAW workaround on the 17 Pro. What Grabar's apps add is **reach onto older, cheaper hardware and a genuine RAW pipeline rather than a filter applied to Apple's already-processed stream.**

---

## 11. Device support — what's actually true

The App Store's `supportedDevices` list is Apple's boilerplate template and is not informative. The real picture, assembled from release notes, the developer site and reviews:

| Tier | Devices | Reality |
|---|---|---|
| **Nominal floor** | iPhone XS / XR (iOS 17) | Runs. Both apps shipped explicit XS/XR recording fixes (RAW Cam v1.8, Log Cam v1.1). Expect short takes and marginal headroom |
| **Usable** | iPhone 11, 12 | Confirmed working in reviews and hands-on reports; one iPhone 12 reported 43+ min at 4K |
| **Recommended floor** | **iPhone 13 and later, including non-Pro** | Developer's own stated floor for **ProRes** in Log Cam; CineD uses iPhone 13 as the practical reach |
| **Best experience** | iPhone 15 Pro / 16 Pro / 17 Pro, iPhone Air | Better thermals and faster SoC = longer sustained takes. One reviewer specifically praised open gate Apple Log 2 on **iPhone Air**, which neither Blackmagic Camera nor the native app can do |

Min iOS: **17.0** (RAW Cam) / **17.4** (Log Cam).

---

## 12. User reception

**RAW Cam — 4.7/5 from 21 US ratings.** Consistently positive from people who know RAW workflows.

- *"If you ever had a BMD Pocket Cinema Camera or Micro Cinema Camera, same workflow but now you got Gyroflow data."* — iPhone 16 Pro Max user
- *"I'm so happy true raw video is here… There are still occasional freezes when switching lenses after adjusting settings."* — iPhone 15 Pro Max user
- Earliest reviews (Dec 2025) requested histogram, white balance and AF-during-record. Histogram shipped in v1.1, WB in v1.7 with a direct developer reply. **AF during recording has not shipped and is architecturally hard.**
- One reviewer preferred Blackmagic Camera for predictability and efficiency, calling RAW Cam "promising" rather than ready.

**Log Cam — 4.0/5 from 40 US ratings.** More mixed, consistent with a two-month-old app.

- *"The app is actually really really really rough. The UI is a far cry from something like Mavis Camera. There's no exposure comp, audio meters, etc. And the cherry on top is that there's no autofocus during recording. But what you get in return is the cleanest open gate image you'll ever get on your iPhone… Developer, you're definitely a camera nerd and I salute you for doing something so audacious for iOS."*
- *"Now I can shoot Open Gate using Apple Log on the Air model, which isn't possible with the Blackmagic Camera app or the native Camera app."* — plus a request for **Tentacle Sync** support
- Crash report: false-color/zebra toggling during exposure adjustment crashing the app or killing preview until relaunch, on base iPhone 15
- iPhone 11 user reported the recurring "video processing error" **gone as of the July update**, and raised their rating

**Recurring feature requests:** autofocus during recording · exposure-compensation slider (partly delivered as the v1.4 EV slider) · metering modes · drop-frame / non-drop-frame selection at 24 and 30 fps · audio meters · Tentacle Sync timecode · oversampled HD output retaining open-gate coverage · anamorphic desqueeze (delivered v1.4).

---

## 13. Practical recommendations

**If you're evaluating these:**

1. **Start with Log Cam's free 10-day trial** — but only install when you can actually shoot with it, since the clock starts at download.
2. **Buy RAW Cam outright at $11.99** if you finish in Resolve. It's cheap enough that the evaluation cost is trivial, and it's the more mature of the two.
3. **Run your own thermal test first.** Take length varies enormously by device and ambient conditions. Record until it drops frames, in the conditions you'll actually shoot in, before committing to a job.
4. **Plan storage before you shoot RAW.** ~12 GB/min at 4K open gate. External SSD recording is close to mandatory for anything long.
5. **Install MotionCam Tools** if you use MCRAW — it removes the format's only real drawback.
6. **Never trust the preview for exposure.** It's tone-mapped. Use clipping indicators (RAW Cam) or false color / zebras (Log Cam).
7. **Lock focus before rolling.** Design your shots around this. It is not a bug you can wait out.
8. **Verify Apple Log 2 intercutting yourself** if mixing with a 17 Pro. The curve math can be exact; the upstream sensor characterization is unpublished.
9. **Shoot open gate when you'll stabilize** — the extra sensor area is what Gyroflow needs.
10. **Don't use these for run-and-gun.** Reach for Blackmagic Camera or Kino instead. Using the wrong tool here produces frustration, not footage.

---

## 14. Open questions / things I could not verify

- **Audio sync quality in RAW Cam.** The app records audio and supports external mics, but I found no detail on how audio is muxed with a DNG sequence or how tightly it stays in sync over long takes. srRAW explicitly advertises *synchronized* WAV; RAW Cam does not use that language.
- **Whether Log Cam writes timecode.** RAW Cam explicitly includes timecode in DNG; Log Cam's feature list doesn't mention it, and a user asked for Tentacle Sync support — suggesting it currently has none.
- **Exact open-gate pixel dimensions per device.** Not published; varies with sensor and lens.
- **Actual bit depth of the RAW capture.** srRAW advertises 14-bit CinemaDNG; Lead the way documents Log Cam's output as 10-bit HEVC but doesn't state the capture bit depth for RAW Cam.
- **Current ISO ceiling.** An early review cited a cap around 495; unclear whether that's been raised.
- **Sustained-recording benchmarks.** No controlled per-device data exists. The 4–5 min and 43 min figures come from different users on different hardware in different conditions.
- **Long-term support risk.** Solo developer, no company behind it. The cadence has been excellent, but that's a bet on one person.

---

## 15. Sources

**Primary**
- [RAW Cam + Log Cam official site — leadtheway.hr/rawcam](https://leadtheway.hr/rawcam/)
- [RAW Cam: Open Gate DNG Video — App Store](https://apps.apple.com/us/app/raw-cam-open-gate-dng-video/id6755047834)
- [Log Cam: Open Gate by RAW Cam — App Store](https://apps.apple.com/us/app/log-cam-open-gate-by-raw-cam/id6766185881)
- [Log Cam — Product Hunt](https://www.producthunt.com/products/log-cam-open-gate-by-raw-cam)
- App Store metadata and version histories retrieved via the iTunes Lookup API, 19 Aug 2026
- App Store customer reviews (US storefront), retrieved 19 Aug 2026

**Editorial**
- [Nino Leitner, "Log Cam and RAW Cam Bring Open Gate RAW and Log Video to Older iPhones – A Skeptical Look," CineD, 20 Jul 2026](https://www.cined.com/log-cam-and-raw-cam-bring-open-gate-raw-and-log-video-to-older-iphones-a-skeptical-look/)
- [Epic Tutorials, "Log Cam App Review: The iPhone Video App That Rewrites the Rules"](https://epictutorials.com/blogs/articles/log-cam-iphone-video-app-review)
- [Epic Tutorials, "How to Shoot Open-Gate RAW Video on Older iPhones (RAW Cam App)," 21 Dec 2025](https://epictutorials.com/blogs/articles/open-gate-raw-video-older-iphone-raw-cam)

**Referenced tooling & context**
- [MotionCam Tools](https://motioncamapp.com/tools) — MCRAW virtual CinemaDNG mounting
- [Gyroflow](https://gyroflow.xyz) — open-source gyro stabilization
- Apple Log Profile White Paper (Sept 2023) and Apple Log 2 White Paper (Sept 2025) — as analyzed by CineD
- [srRAW Cinema Camera — App Store](https://apps.apple.com/us/app/srraw-cinema-camera/id6590601552) (SWISS RIG FlexCo)
- [RawCam – Raw DNG Camera (unrelated app) — App Store](https://apps.apple.com/us/app/rawcam-raw-dng-camera/id6765531876)

---

*Note on sourcing: reviewer claims about comparative image quality (including the iPhone 13 Mini vs. iPhone 17 Pro blind test) are single subjective tests, not controlled measurements, and are reported here as such. Version numbers, prices and ratings are accurate as of 19 August 2026 and will drift.*
