# b5q UniXNU

Samsung Galaxy Z Flip5 (`b5q`, SM8550) 的 UniXNU/macOS 移植工作区。

已编译 b5q TWRP recovery，以及内嵌 UniXNU 菜单和 DarwinBoot 的 b5q UEFI/boot.img。
UniXNU 菜单已通过模拟器显示与 EFI 加载检查；Flip5 实机和 macOS 启动尚未验证。

## UniXNU 界面构建

```sh
python3 scripts/build-unixnu.py
python3 scripts/verify-unixnu.py
./scripts/test-unixnu-menu.sh
```

产物位于 `artifacts/unixnu-b5q/`：`boot.img`、`unixnu-b5q-odin.tar`、
`UniXNU.efi`、`SILICIUM_UEFI.fd` 和 ESP 文件归档。boot.img 内置菜单 FAT 内存盘，
首次测试界面不需要预先准备 ESP。完整说明见 `docs/unixnu-build.md`。
这阶段交付菜单与加载器；XNU 内核和 macOS 用户态仍待适配。

## TWRP 构建

b5q TWRP 已构建，供后续通过恢复环境操作 ESP。

```sh
./scripts/prepare-twrp.sh
./scripts/build-twrp.sh
```

设备树版本、构建补丁和说明见 `docs/twrp-build.md`、`docs/twrp-sources.json`。
默认产物目录为 `artifacts/twrp-b5q/`；实际成功状态以该目录中的构建与 ramdisk
校验报告为准。构建脚本不操作手机。

## 已获取的输入

| 本地目录 | 内容 |
| --- | --- |
| `sources/UniXNU` | UniXNU 构建工具、UEFI 模块、公共驱动及 macOS profile |
| `sources/UniXNU-sm8550-common` | SM8550 公共设备树及平台组件 |
| `sources/UniXNU-sheng` | 同平台参考移植及 UFS、USB、GPU 等参考驱动 |
| `sources/Mu-Silicium` | Flip5 的 `b5qPkg`、原始设备树、BootShim 和 UEFI 依赖 |
| `sources/Device-Binaries/b5q` | 与 Mu-Silicium gitlink 匹配的 Flip5 厂商 DXE 与资源 |
| `sources/lzfse` | Linux 上解压 kernelcache 使用的 LZFSE 工具源码 |
| `sources/UniXNU/out/feeds` | 由官方 fetch 解析并锁定的 XNU、EDK II、Apple 库源码 |
| `sources/UniXNU/out/ipsw/26C5035r` | profile 选定的解压 kernelcache、Apple DeviceTree 和 trust caches |

`sheng` 仅用于解析上游依赖和参考代码，不作为 Flip5 的设备配置或刷机镜像。
厂商二进制、Apple 输入和依赖 checkout 保留在本地忽略目录，根仓库保存版本锁和获取脚本。

## 获取与检查

```sh
# 下载锁定版本及嵌套依赖，不构建、不刷写。
python3 scripts/fetch-sources.py

# 加上 profile 选定的 IPSW 组件；本地编译 LZFSE 后按需提取。
python3 scripts/fetch-sources.py --with-ipsw-inputs

# 离线核对顶层源码版本和关键板级文件。
python3 scripts/fetch-sources.py --check
```

需要 Python 3.11+、Git、CMake 和 C 编译器。设备树检查使用 `dtc`。
这些要求用于材料获取，不代表完整 XNU 编译工具链已安装。

完整版本见 `sources.lock.json`，设备树对照入口见 `docs/source-map.md`。

## 下一步

1. 从三星 `b5q.dts`、UEFI 内存图和 `sm8550.dtsi` 建立 b5q 板级差异。
2. 在本仓库建立 `board.toml`、`dts/b5q.dts`、defconfig 和移植记录。
3. 实机验证已集成的 b5q UniXNU 菜单、显示、输入和 FAT 内存盘。
4. 按内核启动、存储、macOS 用户态、显示和输入顺序实机验证。
