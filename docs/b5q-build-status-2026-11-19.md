# b5q macOS build checkpoint — 2026-11-19

Target: `macos-27.3-26C5035r`, Samsung SM-F7310 / b5q / SM8550-AC.
This is a build/evidence checkpoint, not a completed port or a flashing guide.

| Requested milestone | Actual result |
| --- | --- |
| 1. Inputs and build environment | Samsung package extracted; pinned macOS/Xcode and Ubuntu UEFI CI environments verified; unchanged official package template; 131 ordered patches apply. |
| 2. UEFI integration | Full FD builds in CI and locally. UniXNU/DarwinBoot/RAM handoff diagnostics compiled. Runtime memory-window, Samsung guard/watchdog and GOP qualification remain. |
| 3. Full-component XNU | Full component selection retained. GOP/KeyStore/AES ABI archive builder compiles. Final actual kernel link fails on the symbol set in `UniXNU-b5q/reports/xnu-unresolved-symbols.json`. A pure prelinked-crypto hook mismatch has a source fix and ordered-patch test, not yet a successful target link. |
| 4. RamBlock and B5qUfs roots | RamBlock + real RSA VerifiedRoot host CI pass. Generic UFS read/publication/command algorithms pass host tests. B5qUfs hardware transport, deployment extents and OS/SystemOS/App root mount are not implemented or qualified. UFS stays disabled. |

## Actual local binary

`/home/baimao/zflip5/artifacts/b5q-stage123/firmware/SILICIUM_UEFI.fd`

- Size: 3145728 bytes (3 MiB).
- SHA256: `f1fa4e0e4e4f42ce5f6acb03488735abfcddadc4ecb89c76a88fe704c0f598e0`.
- Pinned EDK II: `cfb93724a06ff86ff5ba971413368a7809ee42a5`.
- Local compiler: Clang 17. CI used Clang 18; its artifact is separate.
- This FD is **not** the requested macOS Android boot.img.

CI results:
- Full firmware: 44402720981 and 44408313388 success.
- RAM/VerifiedRoot host tests: 44409204189 success.
- Full kernel: 44408313251 final-link failure, not missing GOP archive anymore.
- Final-link-only diagnostics: 44412030927 success.

## Input boundary

The currently attached ADB recovery identifies as **nabu / Xiaomi Pad 5**,
not b5q. Its read-only hardware snapshot was quarantined and is not reused.
The Samsung original static DT has `/memory/reg = <0 0>`; its splash reservation
is not a live GOP address. No runtime DRAM bank, UH/RKP exclusion or framebuffer
address is inferred from it.

Connect the Flip5 recovery to this host. The narrow read-only collector is:

```sh
python3 /home/baimao/zflip5/UniXNU-b5q/scripts/collect-runtime-fdt.py \
  --output /home/baimao/zflip5/artifacts/b5q-stage123/b5q-runtime-memory.json
```

It rejects non-b5q devices before reading FDT, does not access partitions,
and outputs only hardware memory evidence, not chosen/bootargs/serial/seed.
EFI/GOP handoff still requires UEFI runtime observations.

Source integration errors (storage ABI and GPU glue) remain engineering work,
not files the user is expected to invent. Deployment extent/seed and true b5q
runtime observations are separate external inputs. No macOS kernel.macho,
payload.img, boot.img or package.manifest.json success is recorded here.
