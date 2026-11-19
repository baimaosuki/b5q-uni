# RAM-only b5q versus pinned sheng macOS configuration

Reference: UniXNU-sheng c8f92b208068eeaa4cd2b0f592671f04ee70076e.
Target: macos-27.3-26C5035r.

## Exact defconfig diff
```diff
--- reference/configs/sheng_macos_defconfig
+++ device/configs/b5q_macos_defconfig
@@ -1,22 +1,15 @@
+# Core build selection. No inherited sheng storage archive, UUID or power policy.
 CONFIG_XNU_BUILD_ARCHIVES=y
+# Use the selected macOS profile crypto bootstrap; do not override it here.
+# AES is started by the ABI-qualified late probe, not an early personality.
+CONFIG_XNU_NATIVE_AES=n
 CONFIG_XNU_CRYPTO_BOOTSTRAP="source"
 CONFIG_XNU_DT_PANIC_REGION=y
 CONFIG_XNU_ARMVIRT_PLATFORM=n
-CONFIG_XNU_EXTRA_LD_ARCHIVES="-Wl,-force_load,{tree}/build/sheng-source-storage/libShengSourceStorage.a"
 CONFIG_XNU_KERNEL_CHAINED_FIXUPS=y
-# The boot image carries the signed policy headers; their hash tables are userdata objects.
-CONFIG_XNU_SOURCE_STORAGE_TABLES="userdata"
-# Owner-verified UFS windows from the source storage archive authorize the mounted root.
-CONFIG_XNU_SOURCE_STORAGE=y
-CONFIG_XNU_OWNER_ROOT_AUDIT=y
-CONFIG_XNU_OWNER_ROOT_TRUST=y
-# SystemOS cryptex, boot manifest and the writable Data volume from the Data seed's RAM disk.
 CONFIG_XNU_NATIVE_RAM_BLOCK=y
-CONFIG_XNU_OWNER_CACHE_MOUNT=y
-CONFIG_XNU_OWNER_CACHE_STARTUP=y
-CONFIG_XNU_OWNER_BOOT_MANIFEST=y
-CONFIG_XNU_OWNER_DATA_MOUNT=y
-CONFIG_XNU_OWNER_UNION_SYSTEMOS=y
-CONFIG_XNU_OWNER_DATA_VOLUME_UUID="79157BD4-6A8C-45D6-A0EB-11FEA89BDE46"
 CONFIG_XNU_NATIVE_LEGACY_DISPLAY=y
 CONFIG_XNU_NATIVE_ADRENO=y
+# RAM-only source storage: the actual public base and RamBlock live in one archive.
+CONFIG_XNU_SOURCE_STORAGE=y
+CONFIG_XNU_EXTRA_LD_ARCHIVES="-Wl,-force_load,{tree}/build/ram-block/libRamBlock.a -Wl,-force_load,{tree}/build/software-aes/libSoftwareAES.a"
```

## Archive sequence

Reference:
- `build-corecrypto-14.py`
- `build-corecrypto-14.py --namespace`
- `component:ArmDTPlatform`
- `component:ArmCpu`
- `build-libpthread-kernel.py`
- `component:ShengUfs`
- `component:RamBlock`
- `component:Adreno740`
- `fetch-sheng-dts.py`
- `fetch-adreno-inputs.py`
- `prepare-sheng-gmu.py`
- `prepare-sheng-gpu-smmu.py`
- `prepare-sheng-gmu-votes.py`
- `build-adreno740-kits.py`
- `build-adreno740-accelerator.py`
- `component:SoftwareAES`
- `component:AppleKeyStoreState`
- `build-gop-legacy-display-27.py`

b5q:
- `build-corecrypto-14.py`
- `build-corecrypto-14.py --namespace`
- `component:ArmDTPlatform`
- `component:ArmCpu`
- `build-libpthread-kernel.py`
- `build-b5q-storage.py`
- `build-b5q-gop-27.py`
- `build-b5q-adreno.py`

## Implemented replacements

- Public IOStorageFamily is built from the same 337.100.1 pin and macOS TargetConditionals flags; only base + RamBlock + VerifiedRoot are linked, not NativeUfs/SourceRootPolicies/firmware/GPT/persistence.
- Retains the same OS-only display/AES authenticated-vtable fixtures. Excludes every sheng peripheral aggregation call.
- Compiles all NativeAdreno C++ units and generic PM4/HFI/SMMU C sources. Omits board-generated GMU command/register/vote C implementations instead of copying Xiaomi tables.
- AES is not removed: the real ABI-bound AES archive is force-linked and the late probe starts it, just as in the reference. Its early KernelConfigTables personality is off because it would register before the original family.
- Source crypto bootstrap now matches source-storage reference behavior, including the real native HMAC/POST and once-only original provider start. The temporary prelinked-hook workaround is no longer selected.
- UFS store/DPU and optional diagnostics use explicitly typed absent-provider stubs; no successful reads, writes, root authorization or MMIO are fabricated.

Runtime boot args, root deployment and memory differences are deliberately not copied. This is the requested RAM-only compile/link target, not a full macOS installation.
