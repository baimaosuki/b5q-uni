# b5q macOS 27.3 RAM-only build result — 2026-11-19

- CI: 44455422555 — completed SUCCESS
- Build source: `0b8712cdc3508099a276bdb57f842ae4ca8fbeba`
- Target: `macos-27.3-26C5035r`
- Final unresolved symbols: none; complete fileset mapping, allow_missing=false.
- Original source and retained-provider HMAC checks kept; entry and panic probes enabled.
- Downloaded 22 actual CI files through recipient-encrypted transport; file index/HMAC/SHA256 verification passed.

## Actual local outputs

### kernel.macho

- Path: `/home/baimao/zflip5/artifacts/b5q-macos-27.3-26C5035r-ram/kernel.macho`
- Size: 142966784 bytes
- SHA256: `cd0016c599a6cd2dcd6a739328aca02d8da3ff6eaa7926695dfb3c8554346636`

### package.manifest.json

- Path: `/home/baimao/zflip5/artifacts/b5q-macos-27.3-26C5035r-ram/package.manifest.json`
- Size: 18026 bytes
- SHA256: `43a56d348540be7b17ab47e5476297859f0786530c3863d87a601098843b9500`

### payload.img

- Path: `/home/baimao/zflip5/artifacts/b5q-macos-27.3-26C5035r-ram/payload.img`
- Size: 268435456 bytes
- SHA256: `d150627e7d2d22e1ba3d70f71af257602eee281ff71357601c22dcc6b36dda47`

## Add to the existing UniXNU menu

The FAT payload is not an Android boot image and must not be written over the boot partition.
Use the extracted and already verified deployment bundle:

`/home/baimao/zflip5/artifacts/b5q-macos-27.3-26C5035r-ram/menu-files/EFI/UniXNU/Payloads/b5q-26C5035r`

1. On the same EFI-readable volume as the existing `EFI/UniXNU/unixnu.toml`, copy this directory to `EFI/UniXNU/Payloads/b5q-26C5035r/`.
2. Append the following snippet from `/home/baimao/zflip5/artifacts/b5q-macos-27.3-26C5035r-ram/menu-entry.toml` to the existing configuration, without replacing the existing entries.
3. Keep `kernel.macho`, `kernel.macho.adt` and `scratch-data.img` together. The loader discovers the `.adt` sidecar beside the kernel.

```toml
[[entry]]
id = "b5q-27-3-26C5035r-ram"
title = "b5q macOS 27.3 26C5035r RAM bring-up"
type = "xnu"
path = "Payloads/b5q-26C5035r/kernel.macho"
initrd = "Payloads/b5q-26C5035r/scratch-data.img"
args = "-v debug=0x14e vc-text=1"
confirm = "Load b5q RAM-only kernel bring-up?"
enabled = true
```

The top-level compiled kernel and the deployment kernel intentionally have different hashes: the latter is taken from the FAT after guarded entry/panic probes and source POST resealing. Use the `menu-files` kernel for this entry.

## Verification

`/home/baimao/zflip5/artifacts/b5q-macos-27.3-26C5035r-ram/verification.json` records complete manifest and member checks.

```sh
cd /home/baimao/zflip5/artifacts/b5q-macos-27.3-26C5035r-ram
sha256sum -c SHA256SUMS
```

## Scope

These are real compiled/linked and verified RAM-only kernel/payload outputs. B5qUfs controller code is not enabled. The 512MiB logical APFS Data filesystem is fresh and volatile; it is not a full macOS Data template. No OS/SystemOS root installation, trust-cache/GPU-addon bundle, Metal desktop, or hardware boot qualification is claimed. No phone connection or recovery collection was required.
