# Galaxy Z Flip5 / b5q 的 UniXNU macOS 移植计划

日期：2026-11-19。目标：`SM-F7310 / b5q / SM8550-AC`，`macos-27.3-26C5035r`（XNU `12377.121.6`，arm64e）。
本次范围：从用户给定原厂包提取输入、核对证据、制定实现与验收顺序；不新增驱动，不执行手机刷写。

## 1. 本次已经完成的工作

原包目录：`/home/baimao/zflip5/F7310ZCS7EYF3等6个文件/F7310ZCS7EYF3`。
`FirmwareInfo.txt` 标注 SM-F7310、CHC、Android 15、F7310ZCS7EYF3，发布日期字段为 `20250623153614`。
不能把此前 SM-F731B 的 TWRP 配置当成此包的 SKU 证据。

提取根目录：`/home/baimao/zflip5/artifacts/firmware-b5q/F7310ZCS7EYF3`。
只提取 AP 的 boot、vendor_boot、recovery、dtbo、super 和 BL 的 NON-HLOS；没有提取受保护的引导链镜像。

| 输入 | 提取结果 | 在移植中的用途 |
| --- | --- | --- |
| boot.img | 96 MiB；内核 45,550,080 字节，boot ramdisk 为 0 | 原厂启动格式/内核输入对照 |
| vendor_boot.img | 96 MiB；DTB bundle 1,803,659 字节 | 原厂 SoC 硬件描述与 vendor ramdisk |
| recovery.img | 109,576,192 字节 | DTB/DTBO 来源一致性对照，不是 macOS 镜像 |
| dtbo.img | 16 MiB，DTBO 表有效长度 4,246,336 字节 | B5Q 五个板级 revision 的 overlay |
| super → vendor | sparse 解码、逻辑分区解包及 EROFS 提取完成 | 三星 GPU 固件和触控候选固件 |
| NON-HLOS.bin | 117,862,912 字节，FAT；未找到本次所需 A740 文件 | 已核对，GPU 输入实际来自 vendor/firmware |

可复现脚本：
- `/home/baimao/zflip5/scripts/extract-b5q-samsung-inputs.py`
- `/home/baimao/zflip5/scripts/inventory-b5q-official-dt.py`
- `/home/baimao/zflip5/scripts/inventory-b5q-gpu-inputs.py`

输入证据：
- `artifacts/firmware-b5q/F7310ZCS7EYF3/extraction-manifest.json`：归档成员、偏移、大小、SHA256、解包组件。
- `UniXNU-b5q/reports/official-firmware-hardware.json`：四个 base、五个 overlay、五个离线合并候选及硬件属性。
- `UniXNU-b5q/reports/samsung-gpu-inputs.json`：原始 GPU 文件、容器与工具哈希、MBN/分段一致性。
以上相对路径均相对于 `/home/baimao/zflip5`。

### GPU 输入已经齐备

集中目录：`/home/baimao/zflip5/artifacts/firmware-b5q/F7310ZCS7EYF3/gpu`。

| 文件 | 字节数 | 核对结果 / 后续策略 |
| --- | ---: | --- |
| a740_zap.mbn | 12,088 | 三星原始完整容器；不同于 sheng 输入，建立 b5q 专用输入配方 |
| a740_zap.elf | 5,168 | 与 MBN 不同，不能因扩展名是 ELF 就互换加载 |
| a740_zap.mdt | 4,044 | 与 MBN 头及哈希段一致 |
| a740_zap.b00 / b01 / b02 | 148 / 1,072 / 3,896 | 三段分别与 MBN 对应段逐字节一致 |
| gmu_gen70200.bin | 66,844 | SHA256 与已锁定的上游 GMU 输入相同 |
| a740_sqe.fw | 76,724 | 与上游 75,380 字节版本不同；必须审计加载器和指令输入约束 |

`a740_zap.mbn` SHA256：`824c864310b0c3a90bd14225a46177d4d4cd0ebca4c712eeb00aa7d82b0e6c1e`。
`gmu_gen70200.bin` SHA256：`1a2a419c39046d3141fc5fed5aa7f971de2db40cc7a1d89693c3e26fad64dd98`。
`a740_sqe.fw` SHA256：`96fee336424b139100fc60b5b45a907360e4b3936d7e1d00406b9bd80ca48473`。

已设置被 Git 忽略的 `UniXNU-b5q/local.toml`，指向上述本地目录。原厂包与大体积提取产物不纳入源码仓。
固件输入存在性检查现在仅报平台 seed 未配置；它只检查部分 ZAP 文件，完整八文件证据以上述 GPU 清单为准。

## 2. 原厂 DT 与参考平台的差异和确定性

原厂 vendor_boot 包含 Kalama v2/v1、KalamaP v2/v1 四个 base；DTBO 的 B5Q board-id revision 为 **04 / 05 / 07 / 09 / 11**。
本次成功合并的是 **base0 × 五个 overlay**，不是全部 20 种组合，也不代表手机已选定 base0。
vendor_boot/recovery 的 DTB bundle 相同；recovery_dtbo 与 AP DTBO 表的有效前缀相同。这是包内一致性，不是两个独立硬件样本。

| 项目 | 原厂离线 DT 证据 | 与 Mu/TWRP/旧记录的区分及实施方式 |
| --- | --- | --- |
| DRAM banks | 五个已合并候选 `/memory/reg` 均是 `<0 0>` 占位 | 旧参考树的八段 memory 不能标成此机运行时结果；从传入 UEFI 的已修补 FDT 与 EFI memory map 获取 |
| GICD / GICR | `0x17100000 + 0x10000` / `0x17180000 + 0x200000` | 样本合并树可核对共享 SM8550 层，继续验证实际中断/CPU 路由 |
| UFS / ICE | `0x1d84000 + 0x3000` / `0x1d88000 + 0x8000` | 基址不等于驱动适配完成，仍需 PHY、时钟、SMMU、LUN 与根窗口配方 |
| GPU / GPU SMMU | `0x3d00000 + 0x40000` / `0x3da0000 + 0x40000` | 使用三星 ZAP/SQE；频率 bin 与电源投票需依实际 revision 校准 |
| Gunyah HYP | `0x80000000 + 0xa00000` | 原厂静态保留区；运行时映射仍需合并核对 |
| TZ-stat / QTEE | `0x82700000 + 0x100000` / `0xd8300000 + 0x500000` | 只是命名保留区，不代表全部 TZ 内存 |
| UH / RKP | 已解析原厂候选未给出可直接采用的独立 UH/RKP 命名区间 | 旧参考记录的 UH guest/heap 不升级为本机实测；保留 unknown，核对运行时 FDT/内存图和 Samsung SEC 路径 |
| 主屏 / 背屏 | 有 `1080×2640` / `720×748` panel timing | 主屏作为 GOP/XNU 显示目标；背屏策略独立验证，不从 TWRP 编号推导 UEFI 面板选择 |
| 帧缓冲 | splash 预留 `0xb8000000 + 0x2b00000`；没有 simple-framebuffer 节点 | 该保留区不是已测 scanout 指针；从 GOP 获取 base、stride、format、size；不硬填 width×4 |
| 触控 | I2C Synaptics/Goodix 与 SPI Synaptics 候选 | 已有 s3916a_b5 / s3908_b5 / s3908_b5_old 固件；选中传感器/总线依板 revision 和运行态确定，不能复用 Novatek |

保留区和控制器完整列表见 JSON，不把本表的少数区间当成完整可分配 RAM 排除表。

## 3. 源码与目录职责

锁定基线，不直接更新 main 后混入不明变化：

| 来源 | 提交 / 作用 |
| --- | --- |
| UniXNU | `563595abedfdfa413ad583b66b6176d82007e633`：Format 2、OS profile、构建工具及补丁 |
| UniXNU-sm8550-common | `2dc650ca76ae38715cd0712e60a44b14fe251745`：经三星证据核对后的 SoC 公共层 |
| UniXNU-sheng | `c8f92b208068eeaa4cd2b0f592671f04ee70076e`：接口/构建配方参考，不复制板级硬件值 |
| uefi-b5q 当前基线 | `b303410c8e401fc9419ae65a024356ed09a438ef`：独立 checkout，目前尚未完成 b5q 集成 |
| Mu-Silicium 参考 | `50a0ef121fe633fed786ff14e293f9d6e2da229d`，保留现有本地改动：b5qPkg 平台来源 |

设备侧 `/home/baimao/zflip5/UniXNU-b5q`：
- `board.toml / feeds.toml / configs/`：SoC、macOS profile、组件、ABI 与构建选择。
- `dts/b5q.dts`：仅加入 b5q 已核对硬件与 `unixnu,adt-name`；平台身份由 OS profile 提供。
- `scripts/package.sh`：保持官方模板；板级配方与固件清单另行实现，不把三星输入改成上游小米文件名后蒙混检查。
- `package/`、固件提取配方及未来 `Binaries/b5q` 输入清单：只绑定三星原始输入，不修改签名容器内容。
- `porting.toml / reports/`：每次变更同步 findings/evidence；区分源码、主机测试、实机验证。

固件侧 `/home/baimao/zflip5/uefi-b5q`：
- `Platforms/Samsung/b5qPkg/`：DSC/FDF、内存策略、GOP/显示、三星安全固件交接。
- 共享模块来自 UniXNU：UniXNU、UniXNUDxe、DarwinBoot、UniXNURamDiskDxe，以及 DiskIo/FAT 所需集成。
- 板级连续内存窗口与 SEC/watchdog 策略必须改成 b5q 实现，不直接沿用 ShengBootMemoryDxe 的值。

## 4. 连续实施顺序与验收条件

以下是技术依赖顺序，不设置额外的人工阶段确认点；实际需要的外部输入或硬件执行结果单独记录。

### A. 锁定输入与构建环境

1. 保持上述原始文件和 SHA256，完善 b5q 固件提取/校验配方，审计 MBN 与分段加载接口。
2. 补齐已锁定 Linux XNU 工具链，修复当前 `/opt/unixnu-linux/llvm/bin/clang` 缺失；分别检查 LLVM/LLD、Mach-O 工具和 EDK2 工具要求，不把两套 clang 混为一谈。
3. 按官方 macOS 指南准备 **Mac + Xcode** 执行 Data seed、macOS SDK 和 Metal/addon 相关构建；Linux 内核交叉编译工具链不能代替这些环节。
4. 在本地配置平台 seed，按官方规则绑定，不抄 NABU seed、不取 IMEI/efs。账户凭据交互输入或本地保密配置，不写入报告。
5. 继续使用已存在的 `/home/baimao/nabu_macos/out/downloads/UniversalMac_27.3_26C5035r_Restore.ipsw`，核对目标 profile 的 kernelcache 与 trust-cache pins；不要求重复下载。

验收：host/input preflight 各自通过；保存工具版本和输入哈希。`--check` 仅证明配置/补丁清单可解析，不充当真实编译验收。

### B. 完成 uefi-b5q 与运行时硬件交接

1. 合入 Mu 的 b5qPkg 平台及 UniXNU 的必需 DXE/FAT/RAM payload 集成。
2. 从进入 UEFI 的 FDT 记录实际 SoC/base/board revision、非身份硬件属性、运行时 banks 和 reserved-memory；与 EFI map 求交核对，排除 payload、固件、DMA、TZ/HYP/UH 等占用。
3. 依据这些结果实现 b5q 连续内存窗口，检查 XNU、ADT、prelink、payload、显示缓冲间无重叠；完成 Samsung SEC/UH/RKP 与 Gunyah watchdog handoff 审计。
4. GOP 验证展开态主屏：真实 framebuffer base/format/stride/size、连续重绘与背屏策略。无串口日志用主屏、内存日志及可用的导出路径，不默认依赖 UFS 日志。
5. 在 RamBlock 验证前不调度 UEFI 厂商 UFS 驱动，也不让所谓 preflight 初始化控制器。

验收：菜单能发现 RAM payload、DarwinBoot 正常打开输入，输出完整非敏感内存/GOP交接证据；这一步的菜单镜像不命名为 macOS 成品。

### C. 全组件内核、ADT 与诊断闭环

保持当前 13 项全目标选择及 17 项依赖闭包：ArmDTPlatform、ArmCpu、DarwinBoot、XnuPrelink、SoftwareAES、AppleKeyStoreState、GopFramebuffer、Adreno740、AdrenoMetal、QcomDwc3、QcomGeniSpi、RamBlock、VerifiedRoot。

1. 补齐真正的 board DTS 与 archive/build recipes，而不只在 include 列表里添加名字。
2. 按锁定 XNU 12377 的系列顺序应用补丁；核对 ArmCpu SMP/GIC、实际计时器频率、内存/ADT 映射。
3. 把 `patch-xnu-entry-probe.py`、`xnu-panic-screen.c`、`build-gop-legacy-display-27.py` 接到 b5q 实际显示交接与编译路径，审计其中的板级假设。
4. 验证 SoftwareAES、AKS、prelink 符号与 ABI。每次失败保存首错日志，修正同一层问题后重跑，不以跳过 archive 或验证器代替修复。

验收：真实 `kernel.macho`、ADT、prelink/archives 构建成功；进入 XNU 的实机结果另记。此依赖顺序不要求退回四组件目标。

### D. RamBlock 先验证，再提供系统根读取路径

**重要纠正：`--data-ramdisk` 提供的是可写 Data seed，不会自动把 OS、SystemOS、App 三个系统根窗口也变成 RAM 根。**

1. 在不访问 UFS 控制器的配置中验证 RamBlock 基础 I/O、种子绑定与边界；未通过前不启用 UFS 初始化/MMIO/DMA。
2. 通过后，再开发独立可选的 B5qUfs 根读取路径：b5q PHY/时钟/reset、SMMU/DMA、LUN 与窗口映射，区分控制器命令写入与持久化块写入。
3. 第一版根存储只暴露规划好的 macOS 区域，默认拒绝持久化写；RAM Data 保持独立。受保护分区不提供端点，不读取其内容，名称黑名单不能代替 LBA/窗口边界检查。
4. 为 OS、SystemOS、App 生成并校验 VerifiedRoot policies、UUID、摘要与 hash tables；单独构建 userdata 根窗口容器。
5. 部署区域的实际容量与偏移尚未指定；构建 dry-run 和区间检查完成前不擅自选择 Android userdata，不生成猜测的 dd/刷写命令。

验收：RamBlock 测试通过后才启用 UFS；三根窗口读取/校验成功，Data 来自 RAM，所有 I/O 保持在授权 macOS 窗口。默认第一版桌面前必须具备可用的系统根读取路径。

### E. macOS Data、显示/输入与用户态

1. 按官方指南制作 b5q 安装使用的 Data seed，配置用户、`--skip-setup` 等；已有 NABU `data.dbr` 只作候选，先校验版本、UUID、账户和绑定再决定是否可复用。
2. 配对 framebuffer/HID 的 displayUUID；确认正确触控候选的协议、坐标和固件，再实现三星对应路径。QcomGeniSpi 本身不是完整触控驱动。USB HID 也必须先验证 QcomDwc3/USB host 路径，不能假定可用。
3. 核对 APFS/firmlinks、AKS/AES、TimeSync/计时器、网络 `en0` 身份和 WindowServer 启动依赖；这些可能影响会话建立，不等同于完整 Wi-Fi 适配。

验收：Data 可挂载，启动服务有可追踪日志，输入事件和主屏更新正常，loginwindow/WindowServer 能建立会话。

### F. 三星 Adreno 740 与 Metal

1. 建立三星 ZAP 装载配方，保持原始签名字节；接入实际 GMU/SQE，尤其审计不同大小 SQE 的兼容性，不直接替换上游 pins。
2. 从 b5q 原厂 DT 与运行时 bin 核对 GPU reserved-memory、SMMU stream、时钟/电源投票和中断。719 MHz 不能当成所有芯片都可用的统一 OPP；CPU 高频同样依硬件 LUT/bin。
3. 把 Banners-Turnip `patches/8g2_oneui.py` 纳入 Mesa/Turnip 可复现补丁链，验证 `enable_tp_ubwc_flag_hint` 实际进入生成的 A740 描述，记录来源提交和补丁哈希。
4. 分别验证固件装载、GMU 启动、提交/fence、用户态 Vulkan、Metal addon ABI、present 与 WindowServer，检查像素布局/UBWC 和显示 buffer 交接。

验收：GPU/Metal 基础测试与桌面合成有实机证据。编出 AdrenoMetal 或预设跳过向导都不等于已进入 Metal 桌面。

### G. 完整打包与后续持久化

配置/结构检查入口（已通过一次）：

```sh
cd /home/baimao/zflip5/UniXNU-b5q
scripts/package.sh --os macos-27.3-26C5035r --uefi ../uefi-b5q --check
```

完成前述实现与输入后，使用同一入口执行真实构建：

```sh
cd /home/baimao/zflip5/UniXNU-b5q
scripts/package.sh --os macos-27.3-26C5035r --uefi ../uefi-b5q \
  --data-ramdisk /absolute/path/to/b5q/runtime/data.dbr
```

根存储是独立步骤；官方 package 脚本不代替 userdata 构建。最终容量/布局配置完成后：

```sh
cd /home/baimao/zflip5/UniXNU
./unixnu build userdata --device ../UniXNU-b5q --os macos-27.3-26C5035r --dry-run
./unixnu build userdata --device ../UniXNU-b5q --os macos-27.3-26C5035r
```

最终交付包含实际输出目录中的：
- `kernel/kernel.macho` 与 ADT / prelink 构建证据；
- `payload/payload.img`、`boot/boot.img`；
- 三个根窗口的 userdata 容器、布局/VerifiedRoot 报告；
- 官方流程生成的 `package.manifest.json`、产物 SHA256 和源码/工具锁定信息。

真实产物生成后才报告路径与适配三星布局的部署命令；不会用小米 fastboot 流程代替三星部署。分享 manifest 时检查并脱敏其中的完整 bootargs 和身份信息。
桌面验证后再增加持久化 Data：仅明确划定的 macOS 数据区可写，并补齐掉电恢复、flush/barrier 与受保护区越界拒绝测试。
Wi-Fi/蓝牙、音频、折叠/休眠/关机等作为各自 porting area 的后续验收，不能因桌面点亮一并标成可用。

## 5. 当前进度与下一项工作

| 工作项 | 当前状态 |
| --- | --- |
| 原厂输入提取、GPU 八文件、DT 候选及来源链 | 已完成离线提取/核对 |
| Format 2、SoC/OS 锁定、13 组件选择 | 已配置，依赖闭包 17 项 |
| 官方 package --check | 通过：列出 130 个补丁；未应用/编译这些补丁 |
| 输入 presence preflight | GPU ZAP 已找到；尚缺本地平台 seed |
| 完整内核构建 | 旧真实尝试止于 `/opt/unixnu-linux/llvm/bin/clang` 缺失；本次未开始新的全量编译 |
| UEFI 三星交接、运行时内存/GOP、XNU DTS/板级配方 | 待实现与实机采证 |
| A740/Turnip/Metal、B5qUfs、系统根与 Data | 输入已部分齐备，功能尚待实现/验证 |
| macOS kernel/payload/boot/manifest | 尚未产出；旧菜单 boot.img 不计入 |

本次验证：三份提取/清单脚本 `py_compile` 通过；八个 GPU 文件及 ZAP 分段一致性复核通过；四 base、五 overlay、五个输入哈希绑定的缓存合并及 DT 交叉核对通过；`porting-record.py check` 通过 14 个 area。输入 preflight 的预期返回为 blocked（仅缺平台 seed），不记为全量 preflight 成功。

直接下一步是补齐工具链/macOS 构建环境并实现 b5q UEFI 的运行时 FDT/GOP 采证及安全内存交接；无需再要求用户另找 ZAP/GMU/SQE 或静态 DTB/DTBO。
尚需在执行时落实的外部项是平台 seed、本机运行时采证、macOS/Xcode 执行环境以及最终 macOS 部署区间；不是再次索要完整原厂包。

## 6. 对照的锁定上游指南

- `/home/baimao/zflip5/docs/macos-27.3-repositories.md` 与 `.json`
- `/home/baimao/zflip5/UniXNU/docs/porting/device-repository.md`
- `/home/baimao/zflip5/UniXNU/docs/porting/records.md`
- `/home/baimao/zflip5/UniXNU/docs/porting/device-tree.md`
- `/home/baimao/zflip5/UniXNU/docs/porting/uefi-firmware.md`
- `/home/baimao/zflip5/UniXNU/docs/porting/macos.md`
- `/home/baimao/zflip5/UniXNU/docs/porting/userdata.md`
- `/home/baimao/zflip5/UniXNU/drivers/RamBlock/README.md`

本次没有刷写或访问手机分区，也没有对三星签名证书链或 GPU 执行作成功声明；原包静态 DT 不能替代运行时内存/GOP 证据。上述状态是输入与计划的完成度，不是 macOS 全量移植成功或可刷镜像承诺。
