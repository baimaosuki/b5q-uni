# v33d release：CI 与最终镜像交付

状态：**DELIVERED_OFFLINE_VERIFIED_AWAITING_FLASH_CONFIRMATION**。本地检查、原生 CI、回传门禁和最终镜像回读通过。没有连接或刷写手机；实机状态仍为 HOST_VERIFIED_PENDING_HARDWARE。

| 项目 | 结果 |
|---|---|
| 最终源码 | `f6f2119d95134d9ca977bcbaa8c581fba90c1147`，基于已审查 `5c5e1c01f12980d4f9e096d6a11fb5a8df2ad574` 的CI头文件路径修复 |
| 内核/payload CI | [45540221549](https://github.com/baimaosuki/b5q-uni/actions/runs/45540221549)，SUCCESS |
| UEFI CI | [45537636188](https://github.com/baimaosuki/b5q-uni/actions/runs/45537636188)，firmware job SUCCESS；补丁/pin/config/job逐字节相同，可复用 |
| ESP | `artifacts/b5q-esp-v33d/esp.img`，838860800 B，800 MiB 4Kn FAT |
| ESP SHA256 | `bf64ec69be5187261f86c2102e20da3204494814d30e1ba6ee8ba11a4d754892` |
| 配套 boot | `artifacts/b5q-esp-v33d/boot.img`，19124224 B |
| boot SHA256 | `623979acff78a52ecd94a0822e061ce39600d3b4bcd26acb841c037b377419eb` |
| 原始新 FD | `/home/baimao/zflip5/artifacts/b5q-v33d-release/ci45537636188-firmware/b5q-uni/b5q-uni/uefi-b5q/Build/b5qPkg/DEBUG_CLANGPDB/FV/SILICIUM_UEFI.fd`，3145728 B，SHA `f432336002c93740746a682f1a61d821463c91dc6e9ab0efbe2282f7717902c2` |

## 放行项

1. Ethernet disable先发setLinkStatus(down)，再enabled=false；生产Host测试含禁用顺序，实际arm64e目标编译和完整22项本地总门禁通过。
2. 仅b5q相关87文件提交，另一次CI目录布局修复8文件；主工作区index和五个TWRP改动逐字节不变，不提交artifacts。16固件/loader补丁重建零漂移；4个LinuxIris源文件及来源manifest已在Git中。
3. 完整下载build647文件与固件8文件，均通过GitHub artifact digest与逐文件SHA。新build保留30天，已经包含未来复用所需全部输入，不再依赖旧artifact存活。
4. check-v33b-returned.py全部通过：0014执行常量、实际FD/EFI相等、UsbDma.obj静态mUsbMapBuf且无AllocatePool、ActualAdreno归档两个成员、WiFi readiness plist、APFS账户/策略/watchdogd/absentd、缓存属性、实际新core回调/PAC、无线/媒体/DP闭包均PASS。
5. 实际GPU归档51member，恰好B5qGpu.o与NativeAdrenoGmuService.o改变，其他49个SHA完全相同。GPU PAC端点从实际上传归档提取，未用旧对象充数。无线+ADSP回传联合156对象/79认证契约通过，无未解析/重复符号且零EL1apps_smmu。
6. 最终ESP实际回读：FAT/日志连续分配、四档菜单1011/1019B以内、8个CPUcluster属性、lp-sip0八字节2、两条BGRAfixup、完整输入/USB/调度参数、GPU三固件、4GiBRAMfallbackData、持久Data入口、POST/HMAC、linkedPAC全部PASS；不访问物理Data。
7. boot保留v8原始16MiB裸FAT16bootstrap、bootshim及三星DTB，替换新FD，与ESP的DarwinBoot完全相同；不依赖UNXNFAT1启动。固件修复需要配套boot，不能只刷ESP沿用旧固件。

## 首错保留

第一轮45537636188内核失败是生产脚本从QcaBluetooth父目录推导sheng/package，而CI使用平铺缓存目录，导致QcomQmp.h缺失。已改为显式传锁定reference，增加同布局生产回归，重新本地检查后重试成功。第一轮完整日志与SHA保留于 `artifacts/b5q-v33d-release/ci45537636188-kernel-first-failure.log`。成功固件没有重编或丢弃，未削弱任何returned断言。

## 证据

- `artifacts/b5q-v33d-release/returned-first.log` / `returned/package-ready.json`
- `artifacts/b5q-v33d-release/final-readback-first.log` / `final-readback/images.json`
- `artifacts/b5q-v33d-release/returned-wireless-ADSP.log`
- `artifacts/b5q-v33d-release/pre-ci-header-fix.log`
- `artifacts/b5q-esp-v33d/SHA256SUMS`

停在刷机确认点，不自动执行手机操作；userdata、macosroot及所有三星保护分区均未访问。
