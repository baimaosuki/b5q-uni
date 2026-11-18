# macOS 27.3 仓库与 Flip5 参考入口

核对日期：2026-11-18。通过 GitHub API、在线 board.toml、profile.toml、组件目录和 README 核对。
核对的主仓库提交为 `563595abedfdfa413ad583b66b6176d82007e633`，官方 sheng 提交为
`c8f92b208068eeaa4cd2b0f592671f04ee70076e`。本次调查的在线版本独立于工作区已锁定的构建版本。
机器可读记录见 `macos-27.3-repositories.json`。

## 目标版本

UniXNU 的目标标识为 `macos-27.3-26C5035r`，profile 选择 `Mac17,11`、arm64e、
XNU `12377.121.6`，XNU revision `ac9718fb1af618d5ce8678d0dc6e8a58f252216f`。

- [主线 OS profile](https://github.com/UniXNU/UniXNU/blob/main/profiles/os/macos-27.3-26C5035r/profile.toml)
- [macOS 移植文档](https://github.com/UniXNU/UniXNU/blob/main/docs/porting/macos.md)
- [组件目录](https://github.com/UniXNU/UniXNU/blob/main/components.toml)

## 有明确 27.3 配置的设备仓库

| 仓库 | 平台 | 实际配置与参考价值 |
| --- | --- | --- |
| [UniXNU/UniXNU-sheng](https://github.com/UniXNU/UniXNU-sheng) | 小米 Pad 6S Pro，SM8550 | `board.toml` 的 macOS 27.3 override、`configs/sheng_macos_defconfig`、macOS Data/安装/图形/存储脚本；Flip5 首选参考 |
| [lenzhang/UniXNU-xiaomipad8pro](https://github.com/lenzhang/UniXNU-xiaomipad8pro) | 小米 Pad 8 Pro，SM8750 | 默认 `board.os_profile` 指向 27.3；自有 `patches/k273`、k273 构建工具；README 记录原生启动与 GPU 桌面 |
| [code002-2/piano-macos-unixnu](https://github.com/code002-2/piano-macos-unixnu) | 小米 Pad 8 Pro，SM8750 | `os_overrides."macos-27.3-26C5035r"` 提供 macOS 配置；可研究 RAM 启动与系统打包 |
| [limingerf/UniXNU-tb710fu](https://github.com/limingerf/UniXNU-tb710fu) | 联想 TB710FU，SM8650Q-AB | 默认 profile 为 27.3；选择 ArmDTPlatform、ArmCpu、XnuPrelink、DarwinBoot 四个组件，适合研究内核起步配置 |

直接证据：

- [sheng board.toml](https://github.com/UniXNU/UniXNU-sheng/blob/main/board.toml)
- [sheng macOS defconfig](https://github.com/UniXNU/UniXNU-sheng/blob/main/configs/sheng_macos_defconfig)
- [sheng 内核基线记录](https://github.com/UniXNU/UniXNU-sheng/blob/main/reports/sheng-macos27-kernel-baseline.json)
- [sheng 源码构建记录](https://github.com/UniXNU/UniXNU-sheng/blob/main/reports/sheng-macos27-source-lab.json)
- [lenzhang board.toml](https://github.com/lenzhang/UniXNU-xiaomipad8pro/blob/main/board.toml)
- [code002 board.toml](https://github.com/code002-2/piano-macos-unixnu/blob/main/board.toml)
- [limingerf board.toml](https://github.com/limingerf/UniXNU-tb710fu/blob/main/board.toml)

## Flip5 优先参考的共享仓库

| 仓库 | 作用与 27.3 关联 |
| --- | --- |
| [UniXNU/UniXNU](https://github.com/UniXNU/UniXNU) | OS profile、XNU 补丁、prelink/payload/runtime 构建与 UEFI 菜单 |
| [UniXNU/UniXNU-sm8550-common](https://github.com/UniXNU/UniXNU-sm8550-common) | SM8550 DTSI、CPU/GIC、UFS、GMU、GPU SMMU、时钟和 DMA 公共支持；sheng 选择该 SoC 源 |
| [UniXNU/ArmDTPlatform](https://github.com/UniXNU/ArmDTPlatform) | ARM 设备树平台启动；在 sheng 27.3 的组件与内核 archives 中 |
| [UniXNU/ArmCpu](https://github.com/UniXNU/ArmCpu) | CPU 与 SMP；在 sheng 27.3 的组件与内核 archives 中 |
| [UniXNU/DarwinBoot](https://github.com/UniXNU/DarwinBoot) | UEFI 到 XNU 的加载器；由 sheng 27.3 选择 |
| [UniXNU/XnuPrelink](https://github.com/UniXNU/XnuPrelink) | 内核集合预链接及 ABI 分析；profile 指定 emit_prelink.py |
| [UniXNU/ShengUfs](https://github.com/UniXNU/ShengUfs) | SM8550 UFS 传输及 sheng 存储策略；组件目录明确列出 27.3 |
| [UniXNU/RamBlock](https://github.com/UniXNU/RamBlock) | RAM 块设备与 Data seed；在 sheng 27.3 的组件与内核 archives 中 |
| [UniXNU/GopFramebuffer](https://github.com/UniXNU/GopFramebuffer) | GOP/显示接口；由 sheng 27.3 选择并通过 build-gop-legacy-display-27.py 集成 |
| [UniXNU/Adreno740](https://github.com/UniXNU/Adreno740) | A740 GPU；在 sheng 27.3 内核 archives 中 |
| [UniXNU/AdrenoMetal](https://github.com/UniXNU/AdrenoMetal) | Metal 到 metal2vulkan/Turnip 的前端；组件目录明确列出 27.3 |
| [UniXNU/SoftwareAES](https://github.com/UniXNU/SoftwareAES) | IOAESAccelerator 软件 AES；由 sheng 27.3 archives 与专用 ABI 构建脚本使用 |
| [UniXNU/AppleKeyStoreState](https://github.com/UniXNU/AppleKeyStoreState) | KeyStore 状态接口；在 sheng 27.3 的组件与 archives 中 |
| [UniXNU/QcaBluetooth](https://github.com/UniXNU/QcaBluetooth) | 蓝牙/GENI UART；组件目录明确列出 27.3 |
| [UniXNU/QcomGeniSpi](https://github.com/UniXNU/QcomGeniSpi) | 共享 SPI 控制器接口；由 sheng 27.3 选择 |
| [UniXNU/ShengPreflight](https://github.com/UniXNU/ShengPreflight) | sheng 固件准备；由其 27.3 组件列表选择 |

上表的实际选用关系以 [sheng macOS override](https://github.com/UniXNU/UniXNU-sheng/blob/main/board.toml)
为依据，仓库功能可分别从组件目录与各自 README 核对。

## 图形依赖与补丁来源

- [Droid-VM/macOS-DroidVM](https://github.com/Droid-VM/macOS-DroidVM)：主线 README 明确说明
  macOS 27 内核补丁及 Data seed 账户设置参考此项目，AdrenoMetal README 还说明 macOS Metal
  插件入口、纹理格式和 WindowServer 节奏选项的参考关系。
- [steelbrain/metal2vulkan](https://github.com/steelbrain/metal2vulkan)：Metal 转 Vulkan。
- [Mesa / Turnip](https://gitlab.freedesktop.org/mesa/mesa)：Adreno Vulkan 实现。
- [The412Banner/Banners-Turnip](https://github.com/The412Banner/Banners-Turnip)：图形输入清单包含
  `patches/8g2_oneui.py`，是三星 One UI / 8 Gen 2 相关的参考入口。
- [ianchb/sm8550-mainline](https://github.com/ianchb/sm8550-mainline)：共享 SoC 仓库引用的硬件资源来源。

依赖锁定和作用见主仓库的
[gpu-metal-vulkan-inputs.json](https://github.com/UniXNU/UniXNU/blob/main/scripts/data/gpu-metal-vulkan-inputs.json)。

## 27.3 构建仓库

- [ppma/UniXNU-sheng-build](https://github.com/ppma/UniXNU-sheng-build)：README 标注 27.3 构建，目录以 Actions 为主。
- [gnimaijil11/UniXNU-sheng-build](https://github.com/gnimaijil11/UniXNU-sheng-build)：包含 sheng
  board.toml 的 27.3 override 与 package-macos 系列工作流。
- [yuchengl326-ship-it/UniXNU-sheng-build](https://github.com/yuchengl326-ship-it/UniXNU-sheng-build)：包含
  sheng board.toml 的 27.3 override 与打包工作流。

建议 b5q 的研究顺序为：主线 27.3 profile → 官方 sheng macOS override → SM8550 公共层
→ ArmCpu/ArmDTPlatform/DarwinBoot → UFS/RamBlock → GOP/Adreno740/AdrenoMetal
→ Flip5 外设；Pad 8 Pro 与 TB710FU 用于比较内核和打包方案。

本次是仓库与源码配置核对；上游 README 和运行报告中的成果属于其对应设备，不代表 Flip5
已实现同样功能。code002 默认 profile 仍为 iPadOS，27.3 在 override 中；lenzhang 仓库经
API 和 board.toml 确认为公开可读，主仓库索引仍标记 missing。部分组件目录的 os_abi 列表
未包含 27.3，因此上表以真实 macOS 组件选择和构建脚本交叉核对，不能只按 os_abi 筛选。
26.5 项目和单纯 CI 镜像不计作新增的 27.3 设备适配。本次没有更改源码版本锁、编译 XNU
或推送这份调查文档。
