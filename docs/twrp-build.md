# b5q TWRP build

Target: `twrp_b5q-eng`, `recoveryimage`.

Source setup: `scripts/prepare-twrp.sh`.
Build and package: `scripts/build-twrp.sh`.
Device and common tree pins: `manifests/twrp-b5q.xml`.

The device tree supplies a prebuilt DTB, recovery DTBO, vendor kernel modules and
Synaptics firmware. The common tree supplies its prebuilt 5.15.184 kernel.
Some vendor modules report 5.15.123. The supplied kernel has
`CONFIG_MODVERSIONS=y`; the upstream module loader ignores the leading release
string for modules with CRC metadata. This does not establish symbol ABI
compatibility. Symbol CRCs and runtime module loading must still be verified on
hardware. No force-loading changes are applied.

Kernel config extraction confirmed built-in FAT/VFAT, ext4 and F2FS.
Upstream TWRP includes mkfs.fat, fsck.fat, toybox and ADB recovery services.
Android userdata decryption is disabled by the upstream common configuration.

The image package does not create, format or write an ESP. Its partition name
and actual block path must be selected when the recovery runs on the phone.

The workspace pins Repo v2.54. A newer Repo revision treated interrupted initial
fetches as complete repositories and retried without shallow depth. Repo and all
Android sources stay inside the workspace; no system Git settings are changed.

Expected output directory: `artifacts/twrp-b5q/`:

- `recovery.img`
- `twrp-b5q-odin.tar` containing only `recovery.img`
- `SHA256SUMS`
- `build-report.json`
- `source-manifest.xml`

The build completed successfully. `recovery.img` is 109,576,192 bytes (104.5 MiB),
including AVB padding. Image header and ramdisk checks passed. The Odin archive
contains only `recovery.img`, byte-for-byte identical to the standalone image.
Source kernel, DTB and recovery DTBO match the unpacked image. Runtime boot,
USB and touch operation have not been tested on a phone.

See `docs/twrp-build-result.json` for the output checksums and
`artifacts/twrp-b5q/ramdisk-report.json` for included tools.

## Build compatibility patch

`patches/twrp-soong/0001-handle-missing-robolectric-runtime.patch` handles an
absent Java test runtime under `ALLOW_MISSING_DEPENDENCIES`. The minimal manifest
removes Robolectric but retains framework test declarations. Soong otherwise
panics on a nil type assertion while generating the recovery build graph. The
patch records the dependency as missing; it does not add test runtimes or change
the recovery binary. The build script applies it idempotently.

## Ramdisk verification

`scripts/verify-twrp-ramdisk.py` decompresses the image ramdisk and parses its CPIO
archive without extracting files. It checks for `recovery`, `adbd`, `sh`,
`toybox`, `mkfs.fat`, `fsck.fat` and `sgdisk` under binary directories. The report
and complete file inventory are saved next to the packaged image.
