# Flip5 板级源码索引

本记录描述已下载源码中的内容，不代表本机实测结果。

## Flip5 硬件与 UEFI

以下路径均相对工作区根目录。

| 文件 | 用途 |
| --- | --- |
| `sources/Mu-Silicium/Resources/DTBs/b5q.dts` | 已展开的三星 Linux 设备树，提取硬件资源与板级差异 |
| `sources/Mu-Silicium/Resources/DTBs/b5q.dtb` | 上游提供的二进制设备树 |
| `sources/Mu-Silicium/Resources/Configs/b5q.toml` | BootShim、FD 和 Android boot image 参数 |
| `sources/Mu-Silicium/Platforms/Samsung/b5qPkg/b5q.dsc` | 平台构建配置、framebuffer 参数和组件 |
| `sources/Mu-Silicium/Platforms/Samsung/b5qPkg/b5q.fdf` | 固件卷布局与模块打包 |
| `sources/Mu-Silicium/Platforms/Samsung/b5qPkg/Library/MemoryMapLib/MemoryMapLib.c` | UEFI 内存区域及保留区域 |
| `sources/Mu-Silicium/Platforms/Samsung/b5qPkg/Library/ConfigurationMapLib/ConfigurationMapLib.c` | UFS、显示等固件交接开关 |
| `sources/Mu-Silicium/Binaries/b5q/README.md` | 选定厂商二进制的版本与 patch 说明 |

已核对：

- DTS 根节点模型为 `Samsung B5Q PROJECT (board-id,11)`；DTS 和上游 DTB 一致。
- `b5q.toml` 使用 FD 基址 `0xA7100000`、长度 `0x300000`，Android boot header v4。
- DSC 的 framebuffer 参数为 1080×2640、32 位；运行时地址和 stride 仍要通过 GOP 交接。
- ConfigurationMap 已设置 `UEFIExitUfsSSURequired = 0` 和 `EnableDisplayThread = 0`。
- 厂商二进制来自公开的 SM-F731B/EUX `F731BXXS5FZA1`。这是上游材料版本，不推定用户手机的型号和版本。
- DTS 带有来源设备的 `/chosen`、动态内存等快照内容；建立 UniXNU 树时逐项筛选，不整份当作 XNU 硬件树。

## UniXNU 参考

| 文件或目录 | 用途 |
| --- | --- |
| `sources/UniXNU-sm8550-common/dts/sm8550.dtsi` | CPU、GIC、UFS、GPU/SMMU 等 SoC 公共描述 |
| `sources/UniXNU-sm8550-common/soc.toml` | 平台组件与公共构建配置 |
| `sources/UniXNU-sheng/dts/sheng.dts` | UniXNU 板级 DTS 的参考结构 |
| `sources/UniXNU-sheng/board.toml` | 配置格式参考；其中小米存储策略、显示、输入和固件设置需重新适配 |
| `sources/UniXNU-sheng/drivers/ShengUfs` | 存储控制器与板级策略参考 |
| `sources/UniXNU/drivers/DarwinBoot` | XNU 加载与启动参数交接 |
| `sources/UniXNU/drivers/ArmDTPlatform` | ARM 设备树平台支持 |
| `sources/UniXNU/drivers/GopFramebuffer` | GOP framebuffer 支持 |
| `sources/UniXNU/profiles/os/macos-27.3-26C5035r/profile.toml` | 当前锁定的 macOS 输入、XNU revision 和校验值 |

## 已做验证

1. `python3 scripts/fetch-sources.py --check`：顶层源码 revision 和关键文件检查。
2. `dtc -I dts -O dtb`：公开 b5q DTS 能编译；警告保存在 `logs/b5q-dtc.log`。
3. `fdtget ... / model`：重新编译结果与上游 DTB 的根模型相同。这不是全树等价验证。
4. IPSW kernelcache 按 profile 的 SHA-256 校验。

依赖解析暂时使用 `sheng_macos_defconfig`；它只是下载参考依赖，不是 b5q 实现或构建验收。
下一轮需要新建 b5q 自己的板级配置，再执行对应构建检查。
