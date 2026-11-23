# b5q P0–P5 goal delivery — work in progress

Goal source: `/home/baimao/.codex/attachments/b63b31b7-ea7d-4bba-a4ff-ef2ff8580b9d/goal-objective.md`; SHA256 `91a3d44e421a5f6ee73f5df857cdc2bf1c53b2b6246c8d9e6485936ffe5ebf14`. No stage is yet fully accepted. Existing desktop/Data/GPU/memory evidence is kept separate from new hardware qualification.

| Stage | Required final state | Current evidence/status |
| --- | --- | --- |
| P0 | Samsung touch lifecycle, verbatim sheng pointer, absolute HID fallback; tests, full kernel+UEFI images, independent commit | 43 host preflight groups and28 target objects/PAC/zeroapps_smmu pass; full builds/image/commit pending |
| P1 | CC1/CC2, powered Sink+DFP hub, four-byte bus-number, TI/QMP, firmware DMA | Implemented; targeted production host tests and2targetobject closure pass; joint gates/CI/images pending |
| P2 | WCN6855 FIFO Bluetooth, six rails/shared WCN power, Samsung firmware, native macOS addon | NOT_STARTED |
| P3 | QCA6490 ath11k/MHI/QMI/PCIe, shared power, firmware HAL DMA, wpa addon | NOT_STARTED |
| P4A | Samsung GPIO107 lid, MAX77705 battery, inner-panel DCS0x51 backlight | NOT_STARTED |
| P4B | Samsung ADSP/AudioReach/HAL, two TFA9878 amplifiers and HAL DMA | NOT_STARTED |
| P4C | Iris/VPU30 original firmware, UEFI SID1940/1947 mappings, VideoToolbox | NOT_STARTED |
| P5 | PD VDM, DP PHY/controller/clock/AUX/EDID/training, DPU INTF_DP and external IOMFB | NOT_STARTED |
| Final | All regressions, SHA256/ADT/args/fixups/APFS policy readback, boot/ESP/addon, four menu profiles, flashing/acceptance commands | NOT_STARTED |

Latest user steering: finish all P0+P1 local gates before one joint CI; do not trigger separate P0 retries. Initial P0 CI45162509107 kernel passed; firmware failed before compilation on missing0005/0006 input files, now source reconstruction verified.

Every stage requires original DT/module evidence, complete implementation, passing host tests, full kernel and UEFI builds, returned-image validation, and a separate commit before the next stage. Host tests never prove hardware behavior. Missing original firmware must be named exactly, with injection instructions, while work continues on all remaining requirements.

P0 source facts and input hashes: [p0-touch-source-audit.json](p0-touch-source-audit.json). The C2 module branch is raw coordinate data; the requested release-all policy is recorded explicitly instead of calling it a proven native reset semantic.

## Preserved hardware baseline

Input log `logs/b5q-xnu2log-data-mount-fix/XNU2LOG.txt` SHA256 `6b4624e6960f27c42bd1d018aacc82eb4b5dba0b0ba910f9b49cf76dea7b677a`. Preserve usable RAM7014903808 bytes, outside205811 adopted/0refused, writable FUA Data LUN0 [3406592,47595510]/44188919blocks, GPU/Metal, PSCI and Batch1 service policy. No device access or flashing is performed by this goal build workflow.
