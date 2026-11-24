# b5q P0–P5 goal delivery — work in progress

Goal source: `/home/baimao/.codex/attachments/b63b31b7-ea7d-4bba-a4ff-ef2ff8580b9d/goal-objective.md`; SHA256 `91a3d44e421a5f6ee73f5df857cdc2bf1c53b2b6246c8d9e6485936ffe5ebf14`. P0 and P1 host/build/image gates have passed; new hardware qualification is explicitly pending. Remaining stages are not complete. Existing desktop/Data/GPU/memory evidence is kept separate from new hardware qualification.

| Stage | Required final state | Current evidence/status |
| --- | --- | --- |
| P0 | Samsung touch lifecycle, verbatim sheng pointer, absolute HID fallback; tests, full kernel+UEFI images, independent commit | HOST_VERIFIED_PENDING_HARDWARE; source4108c9e, jointCI45167257160 andimageacceptance PASS |
| P1 | CC1/CC2, powered Sink+DFP hub, four-byte bus-number, TI/QMP, firmware DMA | HOST_VERIFIED_PENDING_HARDWARE; sourceb1e7ae4,53jointgroups/fullkernel+UEFI/actualimage&PAC PASS |
| P2 | WCN6855 FIFO Bluetooth, six rails/shared WCN power, Samsung firmware, native macOS addon | HOST_VERIFIED_PENDING_HARDWARE; joint CI45268304105 + actual image acceptance PASS |
| P3 | QCA6490 ath11k/MHI/QMI/PCIe, shared power, firmware HAL DMA, wpa addon | HOST_VERIFIED_PENDING_HARDWARE; CI45268304105 + paired PCIe firmware45229274907/actual122objects/62PAC PASS |
| P4A | Samsung GPIO107 lid, MAX77705 battery, inner-panel DCS0x51 backlight | HOST_VERIFIED_PENDING_HARDWARE; joint P4 CI and two actual-image readbacks PASS |
| P4B | Samsung ADSP/AudioReach/HAL, two TFA9878 amplifiers and HAL DMA | HOST_VERIFIED_PENDING_HARDWARE; actual HAL, retained DMA, target/PAC and joint image gates PASS |
| P4C | Iris/VPU30 original firmware, UEFI SID1940/1947 mappings, VideoToolbox | HOST_VERIFIED_PENDING_HARDWARE; actual full P4 kernel/HAL/firmware/ESP return gates PASS |
| P5 | PD VDM, DP PHY/controller/clock/AUX/EDID/training, DPU INTF_DP and external IOMFB | INCOMPLETE; 12 protocol groups and arm64e/ABI/PAC checks pass; independent DMA contract, native link owner and external IOMFB remain open |
| Final | All regressions, SHA256/ADT/args/fixups/APFS policy readback, boot/ESP/addon, four menu profiles, flashing/acceptance commands | NOT_STARTED |

Latest user steering: finish all P0+P1 local gates before one joint CI; do not trigger separate P0 retries. Initial P0 CI45162509107 kernel passed; firmware failed before compilation on missing0005/0006 input files, now source reconstruction verified.

Every stage requires original DT/module evidence, complete implementation, passing host tests, full kernel and UEFI builds, returned-image validation, and a separate commit before the next stage. Host tests never prove hardware behavior. Missing original firmware must be named exactly, with injection instructions, while work continues on all remaining requirements.

P0 source facts and input hashes: [p0-touch-source-audit.json](p0-touch-source-audit.json). The C2 module branch is raw coordinate data; the requested release-all policy is recorded explicitly instead of calling it a proven native reset semantic.

## Preserved hardware baseline

Input log `logs/b5q-xnu2log-data-mount-fix/XNU2LOG.txt` SHA256 `6b4624e6960f27c42bd1d018aacc82eb4b5dba0b0ba910f9b49cf76dea7b677a`. Preserve usable RAM7014903808 bytes, outside205811 adopted/0refused, writable FUA Data LUN0 [3406592,47595510]/44188919blocks, GPU/Metal, PSCI and Batch1 service policy. No device access or flashing is performed by this goal build workflow.

## P0+P1 accepted host/build artifacts

- Joint CI: https://github.com/baimaosuki/b5q-uni/actions/runs/45167257160 (`b1e7ae43fb01857d8d845fddeebe4bfdcec0cbfd`), both full kernel and UEFI SUCCESS.
- ESP: `artifacts/b5q-p1-work/ci45167257160/esp.img`,838860800bytes,SHA256`b07c600256dc392bbd6d752c7f6a7f10adb33aa5f3bfe3ac0abc474945d7b02b`.
- New firmware FD: `artifacts/b5q-p1-work/firmware/SILICIUM_UEFI.fd`,SHA256`b909347dd044341ff5e573f2be33154be27900f31b8753cb9f88101b60ece157`.
- Boot: `artifacts/b5q-p1-work/boot/boot.img`,SHA256`38cbf9eb34f942e4f6f816538c4b4b3071c89d2563f00901dd2826493da4a6fc`; original16MiBplainFAT16bootstrap/SamsungDTB/112Bshimretained.
- Deployed kernel SHA256`6996d91a3eaae44ac7e26416d68c98a6fb3fdd65c3ce2c25fbe7e70697746a50`; pre-seal buildmanifesthash3058f8f2 is separately recorded. ZIP transferpassedGitHubdigest; actualFATkernelmatchesdeploymentHMACmetadata and69POSTruntimepatchsites.
- RebuiltDarwinBootfromexactv30sources/compilerproducesSHA256`9e9118b624ab4f46ba80c728421fcfde2d5aa07dac847cad5ccba5055be4829f`; ESPexplicitdriverpairedtotheFD. All15otherFATmembersunchangedbythispairing.
- Actual image gates:981Bargs,SIPu64`0200000000000000`,twoBGRAfixups,E/P8nodes,6GiBspan/outsideadoptionpolicy,defaultpersistentDatawithoutinitrd,original4GiBRAMrecovery,59/26binaryplistsroot:wheel0644/disabled.migrated/absentdtrusted,authenticatedrootproviderhooks,GPUaddonunchanged.
- Actual binary gates:31returnedboardobjects/PAC/zeroEL1apps_smmu;1145USBHIDvirtualslots+326storagevirtualslots matchsourceandoriginalABI; allsource/corehelpersresolved. No newphoneaccessorflashperformed.

This is stage evidence retained for rollback. The final P0–P5 package, four-profile menu and complete final report are still outstanding; these stage images are not presented as the final goal delivery.

Latest user steering: P2 Bluetooth and P3 Wi-Fi must be delivered together. Complete both production implementations and local gates before joint CI and returned-image acceptance; no Bluetooth-only image handoff.

2026-11-24 delivery steering: combined P2+P3 ESP includes reviewed Wi-Fi wait/Window, USB UTMI-to-PIPE/map-release, and staggered two-finger right-click fixes. P4 and P5 each require a separate ESP and final recheck. No intermediate image is delivered.

P2+P3 accepted stage bytes are retained in `artifacts/b5q-esp-p2-p3/esp.img` (SHA256`a537450f18d2f809649b9fbbb22bd8bcc0cdafba25120d1fda5e83eb8815c146`) and paired `boot.img` (SHA256`d8799ec099cb952b72d7768b46e57cbd94e25bd6a9a3f3f08e278b3410471abd`). Full receipt: reports/p2-p3-final-images.json. P4/P5 and final three-image recheck remain incomplete; no final flash instructions are issued.


## Current three-image release gate (not a completed delivery)

| Requirement | Status | Actual evidence |
| --- | --- | --- |
| Wi-Fi clear_wait else/thread_block and Window ownership | DONE (source/host/build) | p2-p3-final-images.json; accepted source57058874; production IRQ race regression |
| USB unplugged UTMI -> hotplug PIPE and QMP release | DONE (source/host/build) | Same accepted P2/P3 image; CC1/CC2 and6fault regression |
| Two-finger tap 2->1->0 | DONE (source/host/build) | Same accepted image; production touch-p0 regression |
| Separate P2/P3 ESP and second readback | DONE (host/build) | CI45268304105; final-recheck/images.json; SHAa537450f18d2f809649b9fbbb22bd8bcc0cdafba25120d1fda5e83eb8815c146 |
| Separate complete P4A/B/C ESP and second readback | DONE (host/build) | CI45295645295+45296602477; p4-final-images.json; SHAfb874c56a44d2c8632609a2719ba2bc2c18d816ea263a14baf406db2676960ba |
| Complete P5 native external display and separate accepted ESP | NOT DONE | p5-link-source.json / p5-display-dma-inputs.json; actual2 unresolved link hooks, no P5 CI or image |
| Combined final three-image handoff | NOT DONE | No flashing commands issued; physical qualification remains pending |

P4 acceptance-only commit `c5c59d394c88864ba4e477f5ea02a8d6692acaf7` contains the actual returned-image receipt and repeatable verification changes. It includes no unfinished P5 source and touches no workflow-triggering build paths.

P5's completed local scopes are protocol helpers, register arithmetic and conservative DPU resource discovery: EDID/AUX/PDIC/port/PLL/training/clocks/TU/CTA/INTF/MSA/ownership, 12 ASan/UBSan groups. The actual target check compiles SE8 and QcomDwc3 plus helper instantiations, verifies original USB vtables, IRQ and GENI PAC, and zero EL1 apps_smmu constants. It explicitly reports `_b5q_dp_link_stop` and `_b5q_dp_link_update` unresolved. This does not constitute a complete native driver, original-family external IOMFB integration or an accepted image.

The Display DMA prerequisite is unresolved: selected DisplayDxe's actual caller reaches the success-return patch, not the orphan HAL setup body. The original IORT's secondary DISPLAY stream exists in metadata, but the original b5q MDP node supplies no sid_phys resource to route a plane onto it. The retained splash reservation is not evidence of an unused, mapped external scanout buffer. The exact facts/hashes are machine-checked by check-dp-display-dma-inputs.py. No primary Display bank/domain is modified and no EL1 SMMU access or phone operation is attempted.
