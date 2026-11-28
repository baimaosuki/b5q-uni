# P0–P5 三套成品交付

## 0. 100% 完成度锁表

下表的 DONE 指实现、主机验证、实际 CI 编译和返回镜像验收完成。所有新增硬件功能均为 `HOST_VERIFIED_PENDING_HARDWARE`；本次没有连接或刷写手机，也没有把编译成功当作实机成功。

| 要求 | 状态 | 可复核证据 |
| --- | --- | --- |
| Wi-Fi 等待竞态 else/thread_block 与 Window 映射释放 | DONE | `p2-p3-final-images.json`；生产代码 ASan/UBSan IRQ 竞态回归 |
| USB 拔线 UTMI→热插 PIPE 与 QMP 映射释放 | DONE | 同上；CC1/CC2、6 类失败、映射配平回归 |
| 双指轻点 2→1→0 保留右键手势 | DONE | 同上；生产触控生命周期回归 |
| P5-一：真实 GOP/PrimaryEnd 校验、2 MiB 对齐、≥16 MiB 尾池、80 字节 ADT 状态与双缓冲容量过滤 | DONE | `p5-splash-tail-integration.json`、`p5-final-images.json`；实际 UEFI/loader 二进制与池边界用例 |
| P5-二：DisplayPort OSString 引用释放 | DONE | `B5qDpDisplay.cpp::string()` 局部引用释放；实际返回外屏对象 |
| P5-三.1：MAX77705 VDM/HPD/Pin→AUX/EDID/PLL/Clock/训练 | DONE | `B5qUsbBoard.cpp`、`QcomDwc3.cpp`、`B5qDpLink.cpp`；26 组 P5 回归 |
| P5-三.2：DPU 双缓冲→硬件 VSync→外接 IOMFB，拔线排空与重接 | DONE | `B5qDpPresentation.h`、`B5qDpIrq.cpp`、`B5qDpDisplay.cpp`；13 项原生管线场景与返回二进制验收 |
| P5-三.3：P4A 合盖联动、内屏背光与外屏在线状态 | DONE | `B5qDaily.cpp`、原生管线/合盖回归；实机行为待验收 |
| P5-三.4：仅 full 开 DP，其余三档 b5q-dp=0 | DONE | P5 两次实际 FAT 菜单/ADT 回读 |
| P5-四.1：独立 P5 commit、完整内核与 UEFI CI | DONE | `07806e9b9ede578837ca44c10a11d7e6d5eedbee`；45344176858 |
| P5-四.2：第三张 800 MiB 4Kn ESP 与配套 boot、二次回读 | DONE | `p5-final-images.json`、`artifacts/b5q-p5-work/handoff-recheck/` |
| P5-四.3：三套路径/大小/SHA、缺失固件说明、刷写与 P0–P5 验收说明 | DONE | 本报告第 3–7 项及三套 final-images.json |
| P5-四.4：实机未测项诚实保留 | DONE | 三套均为 `HOST_VERIFIED_PENDING_HARDWARE` |

## 1. 实证取证表

| 输入 | 精确位置与用途 | SHA256 |
| --- | --- | --- |
| b5q DTS（参考 DTS，非新增手机采集） | `/home/baimao/zflip5/uefi-b5q/Resources/DTBs/b5q.dts:435–437,35008–35014`：cont_splash `[0xb8000000,0xbab00000)`，SID1c00/mask2 earlymap；34863–34958：DP/AUX/Link/PHY 与板级 GPIO | `345420f6987a86bbaaa930c9b908668e172fdcfde44d57624679cd93c8cafb1f` |
| b5q MemoryMapLib | `/home/baimao/zflip5/uefi-b5q/Platforms/Samsung/b5qPkg/Library/MemoryMapLib/MemoryMapLib.c:32`：Display Reserved；真实 GOP 仍由运行时读取 | `8a18883b21362fd088b2c0c47b471ff6121a73764ca93df7b14036c1aef06bdb` |
| 原件 DisplayDxe | 选定 patched PE；实际 FV 内逐字节相等，无本轮 DisplayDxe 修改 | `51babf469c8a6753082b1a84c677a21ed4ddca64ac98ca939a3bb42a614e8070` |
| 原 msm_drm.ko | `.text+0x103a50` format、`+0x103e64` rect、`+0x104088` address、`+0x1043f4` secure、`+0xfcf84` CTL、`+0xfe6d8` blend；逐函数指令哈希在 scanout 证据 | `81248f938e3ff18c71335ea535f3f5a6868e66c6005f8520571422cbedb8945a` |
| 原 pdic_max77705.ko | `.text+0x116b8` 选 Pin、`+0xf204` Configure、`+0x11780` VDM 接收 | `f32bd8305382f6786daee68dbf584446033770cef9f4e7d0458496806ad0afca` |
| 真实 26C5035r KernelCache | IOAV 指令执行、外接 IOMFB 原始 483 槽 ABI | `d1003b5143ffd88439b4d45b6017f587171cfe6855660bed05370a2ea5db9fe9` |

输入来源、原固件提取与同源关系、逐文件/逐函数哈希分别保留在 `p5-source-inputs.json`、`p5-link-source.json`、`p5-scanout-source.json`、`p5-display-dma-inputs.json`。早期开发报告中的未完成结论由本次 final-images 与实际回读结果更新，不改写历史取证。

## 2. 精确改动清单

- `/home/baimao/zflip5/uefi-b5q/Platforms/Samsung/b5qPkg/Drivers/B5qHandoffDxe/DpDma.c::PrepareDp`：读真实 GOP 完整分配，验证 PrimaryEnd；按机主指定的原厂早映射尾池规则生成状态。原主屏域、bank、DisplayDxe 不变。
- `/home/baimao/zflip5/patches/uefi-b5q/0011-b5q-dp-splash-tail.patch` 与 `0012-darwinboot-b5q-dp-tail.patch`：可重现 producer/loader 修改；DarwinBoot 检验最终 EFI 保留内存、与 owned RAM 的隔离，再写 `/chosen`，失败不伪造 ready。
- `/home/baimao/zflip5/UniXNU-b5q/package/B5qDpLink.cpp::Owner`、`B5qDpModes.h::fitPool`：真实交接消费、EDID 池容量过滤、训练、独立 DPU 资源、双缓冲与 service 生命周期；移除 `scanout=unattached`。
- `B5qDpIrq.cpp::Irq`、`B5qDpPresentation.h::Presentation`、`B5qDpDisplay.cpp`：硬件 VSync、已锁存帧才完成通知、拔线排空；OSString 局部引用配平。
- `B5qUsbBoard.cpp`、`QcomDwc3.cpp`、`B5qDaily.cpp`：角色/HPD 到原生 owner，外屏在线时合盖联动。
- `board.toml`、`b5q_menu.py`、命令行原生边界补丁：full=DP1，daily/safe/RAM=DP0；1024 字节原生缓冲与最多 1023 字节正文。
- `porting.toml`：记录本次 CI、输出、二进制/ADT/APFS/PAC/原件保护与最终三包复核结果。

全部 P5 提交文件的完整绝对路径和 CI 输入哈希见 [p5-published-source-files.json](/home/baimao/zflip5/UniXNU-b5q/reports/p5-published-source-files.json)。没有手机操作、DisplayDxe 补丁、EL1 apps_smmu 映射或保护分区访问。

## 3. 未改组件与缓存复用核对

P5 按要求运行完整目标内核与 UEFI CI；匹配的 XNU 编译进度、GPU/Mesa/Cargo、无线目标对象与 Homebrew 下载缓存继续复用。未重新生成 4 GiB Data seed，也未把缓存命中当作新源码编译证据。实际返回对象另行复验。

4 GiB RAM 恢复 seed 的打包 SHA256：`d2e32a5f7dd37807a816d857d8b62eba41615c5da9ac335c2322e3c7a35ffc70`。缺省启动仍为已初始化的 userdata 持久 Data；本次未读取/改写该实体分区。原 GPU addon 条目保留；无线/音频扩展的实际签名、trustcache 和原厂固件哈希已从各 ESP 解出验证。

| 包 | 部署 kernel SHA256 | UEFI FD SHA256 |
| --- | --- | --- |
| P2+P3 | `d00e4b5c395b753d0ce44b1b110484d91bba2ea8bc235fb5e212f0cd26634748` | `42e828e89f99ab33e984bc3811c67f64ea2af78bc2d972217d604b8594614a60` |
| P4 | `5a4d8d945b09d8b1f00e59f921cd8435709bd2d2868c6416e9263493c5767dff` | `5c3a2522d193b2699bfc0fc922abfda027bc00d48cbe553db2c49c5188013f03` |
| P5 | `06b776e5c8d3f5f649ebcdcca0ea5ae20c04d3e9ea4666c3a6a0e6fbf3d1c039` | `e5f20f393295df7743cbbd3f3a9d0e1bef427ba5caf0f25e18b044998b74897b` |

P5 返回 FV 中 DisplayDxe/HALIOMMU/UFSDxe/CmdDbDxe/RpmhDxe 与选定原件逐字节相同，证据：`artifacts/b5q-p5-work/firmware-returned/preserved-original-modules.json`。

## 4. 本地硬验证结果

- P5：26 组生产主机回归，包含 13 项原生管线场景、11,029 项尾池/模式边界；真实 arm64e 编译、原始外屏 IOMFB 483 槽 ABI 与源选定 PAC 契约。
- 本次实际 CI 返回对象：P5 DP 验收、P4 媒体符号/虚表/PAC、P2/P3 无线 122 对象/62 PAC、平台/USB/存储回调与所有板级 `.o` 零 EL1 apps_smmu 物化检查全部通过。
- 最终 kernel 的 chained PAC 逐槽对照真实原 ABI；静态鉴权结果不等于在手机执行 PAC 的实机证明。
- P2/P3、P4 都已重新读完整 ESP 和 boot；P5 也执行完整第二次回读。报告保留实际命令、对象来源、SHA 与 disassembly。

关键命令：`check-dp-local.py`、`check-dp-target.py`、`check-dp-returned.py`、`check-media-callback-pac.py --dp --ci ...`、`check-stage-returned-objects.py`、`check-wireless-target-closure.py`、`check-media-target-closure.py`、`verify-p0-images.py --wireless --media --dp`。完整返回验收索引见 `p5-final-images.json`。

## 5. CI 产物与本地回读校验

| 包 | 内核 CI | 配套 UEFI CI | 本地证据 |
| --- | --- | --- | --- |
| P2+P3 | 45268304105 | 45229274907 | `p2-p3-final-images.json` |
| P4 | 45295645295 | 45296602477 | `p4-final-images.json` |
| P5 | 45344176858 | 45344176858 | `p5-final-images.json` |

三套为独立、累加功能的成品；选择一套 ESP 与它的 boot 配对使用，无需连续刷三遍。下列是最终实际文件字节与完整 SHA256：

| 包 | IMG 完整路径 | 字节数 | SHA256 |
| --- | --- | ---: | --- |
| P2+P3 | [esp.img](/home/baimao/zflip5/artifacts/b5q-esp-p2-p3/esp.img) | 838,860,800 | `a537450f18d2f809649b9fbbb22bd8bcc0cdafba25120d1fda5e83eb8815c146` |
| P2+P3 | [boot.img](/home/baimao/zflip5/artifacts/b5q-esp-p2-p3/boot.img) | 19,120,128 | `d8799ec099cb952b72d7768b46e57cbd94e25bd6a9a3f3f08e278b3410471abd` |
| P4（含 P2+P3） | [esp.img](/home/baimao/zflip5/artifacts/b5q-esp-p4/esp.img) | 838,860,800 | `fb874c56a44d2c8632609a2719ba2bc2c18d816ea263a14baf406db2676960ba` |
| P4（含 P2+P3） | [boot.img](/home/baimao/zflip5/artifacts/b5q-esp-p4/boot.img) | 19,120,128 | `32727e914f0b2741b2b5731ea4fa19c3b671973990bafc5dd0740b6f0dbe811f` |
| P5（含 P2+P3/P4） | [esp.img](/home/baimao/zflip5/artifacts/b5q-esp-p5/esp.img) | 838,860,800 | `b71e54f1c6567746442f88c05ff8d48ba7fed2870fbd335f825dbe56c60e136f` |
| P5（含 P2+P3/P4） | [boot.img](/home/baimao/zflip5/artifacts/b5q-esp-p5/boot.img) | 19,124,224 | `0b672d636330b13117563ae50ba3479853f1eb7366bed312379129dab0c83f40` |

三套 FAT32 均为 800 MiB、4096 字节/扇区、1 扇区/簇；双 FAT、成员、XNU2LOG 连续簇与 token/CRC 通过。所有配置无 offline-mobile-graphics-client，两条 BGRA fixup、8 个 CPU cluster 属性、SIP u64 `0200000000000000`、持久 Data 默认与 4 GiB RAM 回退均通过。

P2/P3 保留其原双菜单；P4/P5 为四档菜单。P5 正文 full=1009 字节、其他档=1017 字节，均连同 NUL 落在原生 1024 字节缓冲内；只有 full 开 DP。P5 静态 ADT 的 DP ready/state 初始为 0，由新 loader 运行时填真实状态，不预置成功。镜像中恢复 APFS seed 的 59/26 binary plist、root:wheel 权限属主、disabled.migrated、可信 absentd 与自动登录全部通过；这不是一次新的实体 userdata 回读。

## 6. 本次刷写命令与缺失固件

仅在 b5q 的 TWRP、单台 ADB 设备连接时手动执行。先选择一套路径，P5 为包含前两套功能的版本；替换为 `b5q-esp-p4` 或 `b5q-esp-p2-p3` 可使用相应独立包。

```bash
cd /home/baimao/zflip5
B5Q_PACKAGE=/home/baimao/zflip5/artifacts/b5q-esp-p5
adb shell -T 'test "$(id -u)" = 0 && test -n "$(getprop ro.twrp.version)"'
adb shell -T 'blockdev --getsize64 /dev/block/by-name/esp; blockdev --getss /dev/block/by-name/esp; blockdev --getsize64 /dev/block/by-name/boot'
# 以上必须依次为 838860800 / 4096 / 100663296；文件 SHA256 对照上表。
adb shell -T 'set -e; real=$(readlink -f /dev/block/by-name/esp); while read -r dev point type options dump pass; do if [ "$(readlink -f "$dev")" = "$real" ]; then umount "$point" || exit 1; fi; done < /proc/mounts'
adb shell -T 'dd of=/dev/block/by-name/esp bs=4096 conv=fsync' < "$B5Q_PACKAGE/esp.img"
adb shell -T 'dd of=/dev/block/by-name/boot bs=4096 conv=fsync' < "$B5Q_PACKAGE/boot.img"
B5Q_ESP_BYTES=$(stat -c %s "$B5Q_PACKAGE/esp.img")
B5Q_BOOT_BYTES=$(stat -c %s "$B5Q_PACKAGE/boot.img")
adb shell -T "set -o pipefail; head -c $B5Q_ESP_BYTES /dev/block/by-name/esp | sha256sum"
adb shell -T "set -o pipefail; head -c $B5Q_BOOT_BYTES /dev/block/by-name/boot | sha256sum"
# 回读 SHA256 必须分别等于所选包的 ESP/boot；确认后手动重启。
```

命令仅写 ESP、boot；不刷 userdata，不重初始化 APFS，不刷 macosroot，不改 GPT 或三星保护分区。三套 boot 都保留原始 16 MiB 裸 FAT16 bootstrap、Samsung DTB、112 字节 shim，并包含各自验证过的新 FD；ESP 中 DarwinBoot 与该 FD 逐字节一致。

无线内置的是原 F7310ZCS7EYF3 的 24 个 firmware 文件，准确清单/哈希在 `wcn-stock-firmware.json`。本地缺少按实际 QMI chip/board ID 请求的 `bdwlan.eXX` / `bdwlang.eXX` / `bdwlanHH.eLL`（可带天线后缀 1/2/10）；本机实际后缀目前为 unknown，不能拿 `.elf` 冒充校准文件。读取原机 vendor 文件的命令如下，不涉及保护分区：

```bash
# 将 FW 设为 B5qWifi 日志 firmware= 实际请求的完整 basename；不得猜 XX。
FW=bdwlan.eXX
mkdir -p /home/baimao/zflip5/artifacts/b5q-wifi-original
adb pull "/vendor/firmware/qca6490/$FW" "/home/baimao/zflip5/artifacts/b5q-wifi-original/$FW"
sha256sum "/home/baimao/zflip5/artifacts/b5q-wifi-original/$FW"
```

vendor 必须是本机匹配固件的只读视图；若该目录也没有目标文件，从同版本原厂 vendor/odm 固件提取同名原件，不能读取 efs/sec_efs/param。拿到正确原件后，在 macOS 终端把文件安装到现有 Data：

```bash
# FW 仍是硬件实际请求的 basename；原件已复制到当前目录。
sudo install -d -o root -g wheel -m 0755 /private/var/ngpu/firmware/ath11k/WCN6855/hw2.0
sudo install -o root -g wheel -m 0644 "$FW" "/private/var/ngpu/firmware/ath11k/WCN6855/hw2.0/$FW"
shasum -a 256 "/private/var/ngpu/firmware/ath11k/WCN6855/hw2.0/$FW"
```

驱动只接受其固件命名白名单，从该持久路径读取；重启后验证 firmware=result=0。该数据文件注入无需重编 core、改 ESP 或修改受信任可执行文件。

## 7. 实机 XNU2LOG.txt 验收对照表

| 项目 | 成功关键字/阈值 | 失败判据 |
| --- | --- | --- |
| 保留基线 | `outside adopted=`、`B5qData: mode=3 blocks=44188919`、GPU 帧计数增长、`B5qPower:`；日志 seq 持续递增 | panic/SEA、Data mount failed、日志停在 seq=1、帧计数不动 |
| P0 触控 | `B5qTouch: stage=ready`；坐标/HID 增长；单击、双击、2→1→0 右键与双指滚轮实测 | 重复卡键、恢复后不 release-all、右键过渡丢失 |
| P1 USB | `TI3e version=03`、QMP 就绪、DMA ready=1、Host/Device 实际枚举；拔线启动后热插 SuperSpeed 恢复 | storm 熔断持续、DMA/PHY 失败、永久仅 USB2、键鼠不枚举 |
| P2 蓝牙 | `B5qBluetooth: transport=FIFO`、power result=0、原固件加载、扫描/配对/输入 | prepare/firmware/串口错误、无控制器/扫描 |
| P3 Wi-Fi | `B5qWifi` firmware result=0、stage≥4、scans/frames 增长、真实关联与网络传输 | ENOENT/BDF 名不符、DMA/IRQ 错误、重复退出 |
| P4A | `B5qBattery:` 合理电量；GPIO107 合盖；`B5qBacklight:` completion=1 | 虚假固定电量、背光写入失败、误睡眠 |
| P4B | `B5qAudio: DMA ready=1`、原 ADSP/AudioReach 启动、amps prepare/start=1、系统输出并真实发声 | DSP/容器/队列失败或无实际声音 |
| P4C | `B5qVideo: DMA ready=1`、保留池与固件就绪，VideoToolbox 实际硬解 | 仅 service 注册无解码、固件/队列错误 |
| P5 DMA/模式 | `B5qDP: dma-ready=1`、prepare=0 retain=0、池≥16 MiB；`EDID pool-filter` fitting>0 | 任一区间/状态失败、池不足、越界候选未拒绝 |
| P5 链路/送显 | `stage=link discovered=1 trained=1`、`scanout=online`、`IOMFB attached`、VSync frame/tag 持续增长、外屏实显 | `scanout=unattached`、训练/scanout 失败、无硬件 VSync/帧呈现 |
| P5 热拔插/合盖 | 外屏在线 `clamshell-sleep-disabled=1`，合盖内屏黑、外屏继续；断链变 0，重接恢复 | 主屏/USB 卡死、stale callback/资源重复使用、断链仍禁用正常合盖 |

以上是验收标准，不是本次已取得的实机结果。新包的全部 P0–P5 实机资格维持 `HOST_VERIFIED_PENDING_HARDWARE`。
