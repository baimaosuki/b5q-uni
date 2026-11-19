# b5q fresh IPSW and installation inputs — 2026-11-19

Status: exact source extraction, verified root image and true macOS Data seed complete; complete bootable flash package remains unfinished.

Dedicated directory: `/home/baimao/zflip5/artifacts/b5q-full-27.3-26C5035r`. Only the original IPSW archive path was read from nabu_macos; no decoded assets, root images or Data state were reused.

## Verified outputs

- Raw OS, SystemOS and App SHA256 equal all three selected official profile pins.
- Official kernelcache independently extracted/decompressed; hash equals d1003b5143ffd88439b4d45b6017f587171cfe6855660bed05370a2ea5db9fe9.
- Three new owner RSA3072 root policies, all 4263936 blocks verified by actual C provider.
- `delivery/macosroot.img`: 17603493888 bytes, SHA256 35b1c581c7074c626b4b3750af93901a988425e42671f1aaeafd7fd6e13de199.
- `delivery/runtime/data.dbr`: 21581984 encoded bytes, 29GiB logical, SHA256 93f9b069dbd573f1f9af39949a23fc8cda36cd8122626eb1931460e9d1b98a03. Created by official macOS tool in CI 44482188463; template owners preserved.
- New Data volume UUID: 1552CFEE-78FF-48D8-8A6C-694B867D61AC. No account was invented or password recorded.

## Supplied GPT

- LBA size: 4096 bytes; consistent with exact listed partition sizes.
- ESP: 3162880..3367679, 838860800 bytes.
- macosroot: 49692663..62275574, 51539607552 bytes.
- Android userdata remains separate; 8589934592-byte gap before macosroot.
- The listing does not identify a UFS LUN. No disk read or write was performed.

## Remaining implementation

- `UniXNU-b5q/package/B5qAbsentBoard.cpp:15`: root acceptance stays zero.
- `UniXNU-b5q/package/B5qAbsentBoard.cpp:16`: root mount device stays NODEV.
- `UniXNU-b5q/package/B5qAbsentBoard.cpp:18`: persistent store open returns failure.
- `UniXNU-b5q/package/B5qAbsentBoard.cpp:23`: persistent read returns failure.
- `UniXNU-b5q/scripts/build-b5q-storage.py:26`: no root UFS provider or SourceRootPolicies adapter is compiled.
- `UniXNU-b5q/dts/b5q.dts:56`: UFS disabled.
- New owner anchor and actual Data volume UUID are not bound into a rebuilt kernel/payload.

The installation staging archive is explicitly not a complete flashable boot package. Its status and manifest use false readiness values. The generated user-run macosroot writer refuses before ADB under this status; its guard was verified locally. A complete package requires the actual b5q root transport and coherent policy/Data/kernel/payload integration, not another round of IPSW extraction.

See `delivery/刷入指南.md` for file placement, exact target geometry, input/account workflow and current dependencies.
