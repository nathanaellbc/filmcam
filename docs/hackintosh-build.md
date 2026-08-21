# Hackintosh Build Guide — i5-13600K + UHD 770, macOS Tahoe 26

**Purpose:** a macOS machine to build and deploy FilmCam to the iPhone 15. The Mac is only
a compiler/deployer — the camera and Metal work happen on the phone — so an Intel
Hackintosh is sufficient for Stages M0, M1 and M2.

**Status:** Reference document, not yet executed.

---

## The one-paragraph truth

The 13600K (Raptor Lake) has no native macOS support, so OpenCore **spoofs it as Comet
Lake**. The RTX 3060 Ti has **zero** macOS drivers (Nvidia shipped nothing past High
Sierra), so it gets **disabled** and macOS runs on the **UHD 770 iGPU** via the
motherboard's HDMI/DP. None of this hurts FilmCam — Xcode compiles and the iPhone does the
GPU/camera work. Budget a weekend of careful guide-following.

**Tahoe (macOS 26) is the last macOS to support Intel.** This is a sunset platform: fine
for shipping one project, a dead end as a long-term machine. A used Mac Mini M1 (~$250) is
the zero-surgery alternative if the OpenCore work proves unappealing.

---

## Phase 0 — Before touching anything

- [ ] Confirm motherboard model + vendor (ASUS/MSI/Gigabyte/ASRock) and that it has an
      HDMI or DisplayPort out for the iGPU.
- [ ] 16 GB+ USB stick for the installer.
- [ ] Decide the **drive layout** (see "Dual-boot" below). A separate SSD/NVMe for macOS is
      recommended; partitioning the existing 1TB+ drive is also viable.
- [ ] iPhone 15 + USB cable, for deployment later.
- [ ] Download on Windows first: [ProperTree](https://github.com/corpnewt/ProperTree),
      [GenSMBIOS](https://github.com/corpnewt/GenSMBIOS), Python, and the
      [OpenCore release](https://github.com/acidanthera/OpenCorePkg/releases).

---

## Dual-boot: keeping Windows and macOS apart

You do **not** have to buy another drive — but a separate drive is the recommended path.
The deciding factor is the **EFI partition** (the small FAT32 partition holding the
bootloader): two drives each get their own, one drive forces them to share.

### Option A — separate drive for macOS (recommended)

Windows stays on the existing drive; macOS goes on a second drive. OpenCore lives on the
macOS drive's EFI partition (or a USB stick). Each OS's bootloader is invisible to the
other.

- **Pros:** cleanest and safest. Windows feature updates can't clobber OpenCore, because
  Windows can't see the macOS drive's EFI. Easiest to troubleshoot, and easiest to
  nuke-and-retry if the first install goes sideways.
- **Cons:** costs a drive (a cheap 250–500 GB NVMe is ~$30–50).

### Option B — one drive, two partitions (works, riskier)

Shrink the Windows partition, create a new APFS container for macOS, install there.
OpenCore shares the single EFI partition.

- **Pros:** no new hardware. A 1TB+ drive has plenty of room.
- **Cons:** Windows feature updates are notorious for rewriting the EFI boot order and can
  leave macOS unbootable until the boot entry is repaired. Partition resizing carries a
  small data-loss risk — **back up first**. Keep OpenCore on a **USB stick** as a rescue
  bootloader so a Windows update can't strand you.

### Picking an OS at startup (either option)

- OpenCore's boot picker lists all detected OSes (Windows, macOS, recovery); arrow-key to choose.
- Set a **default** (e.g. boot Windows after a timeout) and pick macOS only when working on
  FilmCam. Windows stays the daily driver.
- Or use the motherboard's one-time boot menu (F8/F11/F12) to pick per-boot.

**Recommendation:** Option A (a cheap dedicated SSD) for a first build — the safety net is
worth the ~$35. Option B is acceptable on a 1TB+ drive if you back up first and keep a USB
rescue bootloader handy.

## Phase 1 — BIOS settings (make-or-break)

| Setting | Value | Why |
|---|---|---|
| CSM | **OFF** | GPU errors / `gIO` stall if on. Non-negotiable. |
| Secure Boot | OFF | macOS won't boot with it. |
| Fast Boot | OFF | Skips devices OpenCore needs. |
| CFG Lock | **OFF** | Won't boot with it on. If hidden, use `AppleXcpmCfgLock` quirk. |
| VT-d | OFF (or ON + `DisableIoMapper=YES`) | Either path works. |
| VT-x | ON | Required. |
| Above 4G Decoding | ON | Required. |
| Resizable BAR | OFF (or ON + `ResizeAppleGpuBars=0`) | Pick one pairing; don't mix. |
| DVMT Pre-Allocated (iGPU Memory) | **64 MB** | Needed for the UHD 770 to drive a display. |
| Primary Display / Initial GPU | **IGFX / iGPU** (not PCIe) | Forces macOS onto the UHD 770. |
| SATA Mode | AHCI | |
| Intel SGX, Platform Trust, Thunderbolt | OFF | Avoid initial-install issues. |
| Hyper-Threading, Execute Disable Bit, XHCI Hand-off | ON | |

## Phase 2 — Build the EFI (on Windows)

Follow **Dortania OpenCore guide → Comet Lake config.plist** verbatim (the 13600K spoofs as
Comet Lake). Key parts for this build:

### Required SSDTs (compile via the Getting-Started-With-ACPI guide)
- [ ] `SSDT-PLUG` — CPU power management
- [ ] `SSDT-EC-USBX` — embedded controller + USB power
- [ ] `SSDT-AWAC` — required on 600/700-series boards to boot
- [ ] `SSDT-RHUB` — only for ASUS/MSI boards
- [ ] **`SSDT-SPOOF`** — disables the RTX 3060 Ti (see below)

### Disable the 3060 Ti — pick ONE method
> **Easiest: boot-arg `-wegnoegpu`** (WhateverGreen disables all GPUs except the iGPU).
> Cleaner per-slot alternative: the `SSDT-SPOOF` method, with the 3060 Ti's PCI path found
> via Windows Device Manager. (See Phase 3 for why the SSDT may be the safer choice on Tahoe.)

### DeviceProperties → iGPU (UHD 770 drives the display)

**The UHD 770 (Raptor Lake) is not natively supported — it must be spoofed as a UHD 630.**
This is the single most likely place to hit a black screen on first boot, so get it right
before the install. Under `PciRoot(0x0)/Pci(0x2,0x0)`:

```
AAPL,ig-platform-id      Data   07009B3E    (hex BwCbPg==; iGPU drives display)
device-id                Data   9B3E0000    (hex mz4AAA==; spoofs UHD 770 as UHD 630)
enable-metal             Data   01000000    (hex AQAAAA==; Metal 3 + acceleration)
framebuffer-patch-enable Data   01000000
framebuffer-stolenmem    Data   00003001
```

Notes:
- `07009B3E` is for the iGPU driving a display. If the first boot black-screens, swap
  `AAPL,ig-platform-id` to **`00009B3E`** (the headless variant) — this is the classic fix.
- The `device-id` spoof to UHD 630 is what makes Tahoe's Metal acceleration work on the
  UHD 770; without it you get the unaccelerated VESA fallback.
- BIOS must have the iGPU enabled and DVMT Pre-Allocated at 64 MB (Phase 1) for this to
  light up a display.

### Kexts (Lilu first; use ProperTree Cmd/Ctrl+Shift+R to order)
- [ ] `Lilu` → `VirtualSMC` → `WhateverGreen` → `AppleALC` → `IntelMausi` → `NVMeFix` →
      `USBToolBox` + `UTBMap`

### SMBIOS (PlatformInfo → Generic)
- [ ] GenSMBIOS → **`iMac20,1`**. Generate serial/MLB/UUID/ROM. Verify the serial is
      **invalid** on Apple's coverage checker ("unable to check coverage").

### Critical quirks
- **Booter:** `DevirtualiseMmio=YES`, `ProtectUefiServices=YES`, `RebuildAppleMemoryMap=YES`,
  `SetupVirtualMap=NO`, `SyncRuntimePermissions=YES`, `ResizeAppleGpuBars=0` (BAR on) else `-1`
- **Kernel:** `AppleXcpmCfgLock=YES` (only if CFG Lock stuck), `DisableIoMapper=YES` (if VT-d
  on), `PanicNoKextDump=YES`, `PowerTimeoutKernelPanic=YES`, `XhciPortLimit=YES` (temporary)
- **Misc→Security:** `SecureBootModel=Default`, `ScanPolicy=0`, `Vault=Optional`
- **NVRAM boot-args:** `-v debug=0x100 keepsyms=1 -wegnoegpu alcid=1`

## Phase 3 — Tahoe-specific gotchas (new in 26)

- [ ] **Analog audio is broken.** `AppleHDA.kext` is removed, so headphone jack / built-in
      speakers don't work via AppleALC. **Use HDMI/DP or USB audio.** (VoodooHDA with lowered
      SIP is the workaround if the jack is essential.)
- [ ] **WhateverGreen has AMD/Navi patching issues on Tahoe.** No AMD GPU here, so mostly
      irrelevant — but if a WEG-related panic appears, remove WhateverGreen and disable the
      Nvidia card via **SSDT-SPOOF** instead of `-wegnoegpu`. This is the one fragile spot in
      a Tahoe + disabled-Nvidia build.
- [ ] **OTA updates** need `RestrictEvents` + `revpatch=sbvmm` + `SecureBootModel=Disabled`.
      For a build machine, skip OTA: install once, freeze it.
- [ ] **Intel Bluetooth:** add boot-arg `-ibtcompatbeta` if used.

## Phase 4 — Install & verify for FilmCam

- [ ] Create the USB installer (Dortania "Making the installer in Windows").
- [ ] Boot USB → install Tahoe to the dedicated SSD → boot from it.
- [ ] Post-install: map USB (USBToolBox), verify Ethernet, confirm display is on the iGPU.
- [ ] **FilmCam acceptance test:**
  - [ ] Install Xcode from the App Store
  - [ ] Add a free Apple ID as a signing team (free account can deploy to your own device)
  - [ ] Plug in the iPhone 15, trust the computer, enable Developer Mode on the phone
  - [ ] Build a blank iOS app → deploy to the iPhone → it launches
  - [ ] Confirm `AVCaptureDevice` is visible (a one-line probe) — this is the M0 gate

## Effort & risk

| | |
|---|---|
| **Time** | 1–2 focused days for a first-timer following Dortania carefully |
| **Hardest part** | Getting config.plist exactly right (most boot failures are one wrong quirk) |
| **Biggest risk here** | WhateverGreen / Nvidia-disable interaction on Tahoe (Phase 3) |
| **Won't work** | Analog audio jack, anything needing the 3060 Ti, future macOS versions |
| **Will work** | Xcode, Swift compile, iPhone 15 deployment — everything M0/M1/M2 need |

---

## Next step once macOS is running

Write the **Stage M0 capability-probe plan** (spec §4) so it's ready to execute on day one:
a disposable `FilmCamProbe` target answering every question in spec §4.1 / Appendix B —
Bayer video formats, available bit depths, ProRes encode presence, sustained write rate,
Rice-coding throughput on the A16, thermal knee, and (newly relevant after the audio work)
whether iOS delivers audio on the same host clock as video PTS.

**References:**
- Dortania OpenCore Install Guide: https://dortania.github.io/OpenCore-Install-Guide/
- Comet Lake config: https://dortania.github.io/OpenCore-Install-Guide/config.plist/comet-lake.html
- macOS 26 Tahoe notes: https://dortania.github.io/OpenCore-Install-Guide/extras/tahoe.html
- Disabling the GPU: https://dortania.github.io/OpenCore-Install-Guide/extras/spoof.html
