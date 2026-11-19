# UniXNU b5q

Samsung Galaxy Z Flip5 / b5q / SM8550-AC; target `macos-27.3-26C5035r`, XNU `12377.121.6`.

This Format 2 device package selects the pinned UniXNU SM8550 common layer and
thirteen shared components. `scripts/package.sh` is the unchanged upstream
template. `porting.toml` records each subsystem's findings and evidence.

The user explicitly lifted the UFS development suspension on 2026-11-19.
`package/B5qUfs/` implements a Samsung stock-DT-backed, polling, read-only root
transport. It warm-adopts the powered UFS link, isolates only SID `0x60`, finds
one CRC-valid GPT `macosroot` matching the user-supplied bounds, authenticates
three signed root windows and verifies every returned block. Unit descriptors
exclude boot-LUN units before block reads. No SCSI writes or persistent Data
provider are enabled. Data uses the actual official template-derived RAM seed.

`package/B5qRootBinding.cpp` supplies the real owner-root media ancestry audit;
`package/B5qPmgr.cpp` binds the retained original PMGR base/nub without claiming
Samsung power-management support. OS-facing GOP/AES bindings are derived from
the exact pinned macOS collection. Xiaomi panel density, GPIO, DRAM, power votes,
Novatek touch, firmware and fastboot preflight policies are not selected.

The active build is `.github/workflows/b5q-stage123.yml`: make exact-UUID Data,
compile/link full XNU, emit the collection, apply guarded screen diagnostics,
seal source crypto and build FAT payload. Actual results and first failure logs
are returned encrypted to the local workspace. See
`reports/b5q-ufs-firstboot.json` and `porting.toml` for observed CI checkpoints.

```sh
scripts/package.sh --os macos-27.3-26C5035r --uefi ../uefi-b5q --check
```

Use the full profile name: `--os 27` selects iPadOS. Complete root-enabled host
builds are assembled locally with `../scripts/b5q-install/assemble-firstboot.py`.
The installer and Chinese firstboot/input guide are in
`../scripts/b5q-install/`; they write only explicitly selected `macosroot`/`boot`
and validate supplied partition byte offsets, capacities and readback digests.
The source package does not connect to a phone while compiling or assembling.

Samsung firmware inputs were independently extracted from F7310ZCS7EYF3. Four
original base DTBs agree on the UFS controller, apps SMMU and UFS stream ID.
See `reports/official-firmware-hardware.json`, `reports/samsung-gpu-inputs.json`
and `reports/b5q-ufs-firstboot.json`. Static `/memory/reg` is zero; actual RAM
window and scanout must come from EFI allocation/GOP rather than inferred board
constants.

Host tests cover real root-manifest/GPT parser rejection, the production SMMU
mapping algorithm, signed policy identity, original PMGR instruction fixtures,
source-contract checks and installer error paths. Hardware macOS boot, desktop,
Metal and input are not established by host compilation. The first UFS version
requires a powered/idle firmware handoff and a private available SMMU context;
it does not implement cold PHY/reset initialization. Data is volatile.
