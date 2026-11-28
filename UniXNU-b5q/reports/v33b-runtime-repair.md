# v33b runtime repair: final delivery

0. **100% 完成度锁表**

| 编号 | 要求 | 结果 | 实证 |
|---|---|---|---|
| Runtime-1 | 系统图标与已有 Data 策略幂等修复 | DONE | B5qLaunchdPolicy / APFS readback |
| Runtime-2 | USB 自供 VBUS / DP generation 稳定与 DMA 诊断 | DONE | causal / target PAC / zero MMIO |
| Runtime-3 | 手机尺度单击、双击、拖拽与右键 | DONE | causal human data / actual HID timer |
| Runtime-4 | 保留 RAM Normal WB 与 MMIO Inhibit | DONE | returned NormalWB.json / one GMU member proof |
| Runtime-5 | PCIe RCG 自清零与 Wi-Fi 就绪启动 | DONE | GCC causal / actual addon plist |
| Runtime-6 | Bluetooth/wlan ADT 与失败日志 | DONE | actual DTB / ADT / callback ABI |
| Runtime-7 | host ABI / VSync / thermal / owned AKS | DONE | host-abi / target / actual kernel |
| Extra-1 | PARF BDF→SID 原厂与 Linux 编码核对 | DONE | RID0100 / offset1 / NEXT0 = SID1401 |
| Extra-2 | UEFI no-map 与 DMA 分配/USB 映射边界 | DONE | 50 fixed ranges / 190 low checks / actual guarded FD |
| Extra-3 | dyld 多页 UPL 错误与链解析器返回传播 | DONE | 56 failure cases / native core |
| Extra-4 | 复用 addon 显式刷新 supplicant plist | DONE | addon-add-dir / immutable returned assertion |
| Extra-5 | 策略错误与 GPU 启动隔离、uid501 迁移 | DONE | policy migration / actual kern_exec call site |
| Gate-1 | physical_cause_models | DONE | source-bound local receipt + returned acceptance |
| Gate-2 | memory_ABI_real_DTB_ADT | DONE | source-bound local receipt + returned acceptance |
| Gate-3 | sheng_macos_diff_accounted | DONE | source-bound local receipt + returned acceptance |
| Gate-4 | silent_failure_inventory | DONE | source-bound local receipt + returned acceptance |
| Gate-5 | existing_Data_idempotent_migration | DONE | source-bound local receipt + returned acceptance |

全部 DONE 指源码、主机、原生编译和返回镜像验收完成；硅片结果统一为 `HOST_VERIFIED_PENDING_HARDWARE`。没有连接或刷写手机。

1. **实证取证表**

- 原始 XNU2LOG BIN：`dd8acfb9f130bdb1899d76c53990fb4e04cd64fc91687208c4ecaaf2c2908410`；seq137、双槽有效、零丢失。L405/418 对齐异常，L446 PCIe -12，L927 count104，L1423 起 OTG 自激。
- 原厂 b5q.dts：`345420f6987a86bbaaa930c9b908668e172fdcfde44d57624679cd93c8cafb1f`；50 个固定保留范围，官方 5 份合并树 190 次 low no-map 边界核对无遗漏。
- Linux v6.12 pcie-qcom.c L1113：BDF[31:16]、SID offset[15:8]、NEXT[7:0]；`0x01000100` 正确映射 SID1401，`0x01000001` 会误写 NEXT。原厂 iommu-map 同样指定 RID0100→SID1401。
- 逐文件 SHA、符号与证据行号：[source-evidence.json](/home/baimao/zflip5/artifacts/b5q-v33b-fix-work/source-evidence.json)；新增五项：[v33b-additional-five.json](/home/baimao/zflip5/UniXNU-b5q/reports/v33b-additional-five.json)。

2. **精确改动清单**

- [完整文件/哈希清单](/home/baimao/zflip5/artifacts/b5q-v33b-fix-work/delivered-source-files.json)；来源提交 `269d3288db88751eee512d5af5029d8e53ef1bd8`。
- B5qPcieCore 显式编码 SID；MemoryMapLib 补 HOB no-map，PCIe/media/USB 在清零/映射前拒绝原厂保留区。
- dyld 使用 page_kr、首错即停并传播链解析器返回值；失败整批 abort，不提交 CS_VALIDATED 页面。
- reuse-addon 通过 addon-add-dir 刷新唯一 Wi-Fi plist，原返回断言保留；策略迁移用独立 policy_error，不污染挂载/GPU 错误。
- 完整七组运行修复、物理因果模型与全部静态/二进制验收脚本见清单。porting.toml 同步记录来源、验证与硬件待测状态。

3. **缓存与未改组件**

- XNU core 因 kern_exec/host/IOUserClient/dyld 的真实改动原生增量编译；同架构/Xcode/补丁身份验证缓存，仅保留字节相同文件的编译进度。
- GPU 归档 51 个成员中仅 NativeAdrenoGmuService.o 重编为显式 MMIO Inhibit，其余 50 个成员 SHA 完全不变；Mesa/Turnip 与 GPU 用户态执行文件复用。
- 复用原 4 GiB APFS 容器，仅更新 58 system / 25 GUI 策略；没有重建或覆盖实体 168.5 GiB Data。
- UEFI 因保留区漏洞必须更新，新 boot 保留 v8 裸 FAT16、112 字节 shim 与原 Samsung DTB。实际 FD SHA：`d747566ea07fbbde9b552a7bf698c2b221811ad69d13308f867e10418a67f818`。

4. **本地硬验证**

- `python3 scripts/b5q-install/pre-ci-p4.py` 保留全量 P0–P4 回归；`python3 scripts/b5q-install/pre-ci-v33b.py` 18 个验收组、371 个来源文件绑定、五门禁 PASS。
- 真实 GCC CMD_UPDATE 自清零；15 秒 OTG 反馈闭环含 PD 超时且零 teardown；9 组手机触控脏数据、32ms 保持、双击拖动、抬指/stop 串行；ASan/UBSan PASS。
- dyld 8 页/16KiB，56 peek/parser 故障整批中止；真实 POSIX 策略迁移、错误 UID/软硬链接/写入失败、已有文件尾部截断与 GPU 启动隔离 PASS。
- 真实 arm64e 回调 PAC、对象符号闭包、零 EL1 apps_smmu、MMIO/Normal WB 机器码和完整 native display ABI 由 [返回二进制门禁](/home/baimao/zflip5/artifacts/b5q-v33b-fix-work/returned-final/package-ready.json)逐项记录。

5. **CI 与二次回读**

- CI [45426905030](https://github.com/baimaosuki/b5q-uni/actions/runs/45426905030)：kernel/payload 和 UEFI 同提交成功；普通 Actions artifact SHA 与每个成员 hash 校验通过。

| 镜像 | 字节 | SHA256 |
|---|---:|---|
| [esp.img](/home/baimao/zflip5/artifacts/b5q-esp-v33b-repair/esp.img) | 838,860,800 | `6686c339a0f8ea6647ceaae0e381d2ee369889a1caf3319d45214cc8c97f6b63` |
| [boot.img](/home/baimao/zflip5/artifacts/b5q-esp-v33b-repair/boot.img) | 19,124,224 | `0c9f83986eae0f239f9e5a7f6fc81ee98ea56bf865fdb84b6f596c9566de3bc6` |

- 800 MiB、FAT32 4096-byte 扇区；四档菜单、lp-sip0=`0200000000000000`、8 个 E/P 属性、2 个 BGRA fixup、真实 wlan/bluetooth ADT、APFS 策略 uid/mode、签名/trustcache、固件/loader 匹配均二次回读 PASS。
- Wi-Fi 镜像内实测：RunAtLoad=false；KeepAlive.PathState=/private/var/run/b5q-wifi-ready；ThrottleInterval=60。仅该 plist 与已验收无线 addon 不同。
- 首次与第二次独立回读：[readback1](/home/baimao/zflip5/artifacts/b5q-v33b-fix-work/final-readback-1/images.json)、[readback2](/home/baimao/zflip5/artifacts/b5q-v33b-fix-work/final-readback-2/images.json)。

6. **刷写命令**

本次必须配对更新 ESP 和 boot；不动 userdata、macosroot、GPT 或受保护分区。以下仅供机主在 TWRP 手动执行，本轮未执行。

```bash
set -euo pipefail
B5Q_PACKAGE=/home/baimao/zflip5/artifacts/b5q-esp-v33b-repair
adb shell -T 'test "$(id -u)" = 0 && test -n "$(getprop ro.twrp.version)" && test "$(blockdev --getsize64 /dev/block/by-name/esp)" = 838860800 && test "$(blockdev --getss /dev/block/by-name/esp)" = 4096 && test "$(blockdev --getsize64 /dev/block/by-name/boot)" = 100663296'
adb shell -T 'set -e; real=$(readlink -f /dev/block/by-name/esp); while read -r dev point type options dump pass; do if [ "$(readlink -f "$dev")" = "$real" ]; then umount "$point"; fi; done < /proc/mounts'
adb shell -T 'dd of=/dev/block/by-name/esp bs=4096 conv=fsync' < "$B5Q_PACKAGE/esp.img"
adb shell -T 'dd of=/dev/block/by-name/boot bs=4096 conv=fsync' < "$B5Q_PACKAGE/boot.img"
B5Q_BOOT_BYTES=$(stat -c %s "$B5Q_PACKAGE/boot.img")
adb shell -T 'set -o pipefail; head -c 838860800 /dev/block/by-name/esp | sha256sum'
adb shell -T "set -o pipefail; head -c $B5Q_BOOT_BYTES /dev/block/by-name/boot | sha256sum"
# 两项回读 SHA 必须分别与上表一致，再手动重启。
```

7. **实机验收对照**

| 项 | 成功 / 失败判据 |
|---|---|
| 图标/策略 | iconservices=enabled；首次 updated，后续 current；迁移出错也有 boot-continues=1 |
| USB | 稳定鼠标连接 OTG=1，不随 BC80/CC1=9 出现周期 leaveRole；host DMA64/IRQ/ring 计数用于定位；EINT08 不是 HSE04 |
| 触控 | 单击/双击/双击拖拽、2→1→0 右键和滚轮正常；HID 发送成功计数递增、无粘键 |
| 内存/无线 | 无 ESR96000061；RCG 不因成功自清零报 -12；Wi-Fi 未就绪不反复启动 supplicant；蓝牙任何退出有 stage/error |
| 系统 | 不再报 sysmond count104 警告；5 个 Apple platform 服务的 owned AKS 许可，普通 MACF 仍保留；VSync 有客户端时观察投递 |
| 热控 | 保留原厂 90/95/110°C 分级；78°C level0 本身符合阈值，不能据此宣称温控失效 |

真实 USB 枚举、射频连接、音视频和外屏功能仍为 HOST_VERIFIED_PENDING_HARDWARE；本地结果不冒充实机通过。
