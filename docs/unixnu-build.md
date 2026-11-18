# b5q UniXNU 界面构建

已编译 Galaxy Z Flip5 的 UniXNU UEFI 菜单固件，并生成 Android boot v4 镜像。
本阶段包含菜单与 DarwinBoot 加载器，没有打包 XNU 内核或 macOS 用户态。

## 构建

在仓库根目录运行：

```sh
python3 scripts/fetch-sources.py
python3 scripts/build-unixnu.py
python3 scripts/verify-unixnu.py
./scripts/test-unixnu-menu.sh
```

依赖 Python 3.11+、make、GCC/G++（构建 EDK BaseTools）、LLVM/LLD 17、dtc、mtools、dosfstools。
LLVM 路径默认 `/usr/lib/llvm-17/bin`，可用 `--clang-bin DIR` 更改；目录中必须有版本匹配的
clang、lld-link、llvm-lib、llvm-rc，以及打包使用的 llvm-objcopy、llvm-nm。
模拟器验证另需 qemu-system-aarch64 和 AAVMF；常规编译不依赖 QEMU。
ACPI 使用所锁定 Silicium-ACPI 子模块内的 AML，不要求本机安装 iasl。

`--firmware-only` 只编译并复制 FD 与 EFI；`--package-only` 使用已有构建结果重新打包。
修改 DSC/FDF 或模块源码后须运行完整构建。默认 DEBUG、12 个并行任务上限；可指定
`--target RELEASE`、`--jobs N`。

菜单构建参数保存在 `configs/unixnu-b5q.toml`。这是固件阶段配置，尚非完成的 XNU
设备仓库 `board.toml`，不会继承 sheng 的存储布局、面板或启动参数。

## 产物

目录：`artifacts/unixnu-b5q/`。

| 文件 | 用途 |
| --- | --- |
| `boot.img` | Flip5 启动镜像，内含 BootShim、b5q UEFI、三星 DTB、菜单 FAT 内存盘 |
| `unixnu-b5q-odin.tar` | 仅包含名为 `boot.img` 的同一镜像，用于 Odin AP 打包格式 |
| `SILICIUM_UEFI.fd` | 3 MiB UEFI 固件 |
| `UniXNU.efi` | AArch64 菜单程序 |
| `UniXNUDxe.efi` | FV 内菜单启动项注册驱动 |
| `UniXNURamDiskDxe.efi` | 将 FDT initrd 发布成只读块设备的驱动 |
| `DarwinBoot.efi` | XNU 加载器，已嵌入固件 |
| `HelloPayload.efi` | 验证菜单加载 EFI 程序并返回的上游测试程序 |
| `menu-payload.fat` | 16 MiB FAT16 内存盘，已放入 boot.img |
| `esp/` / `unixnu-b5q-esp.tar` | 同一组 EFI 文件与菜单配置，便于之后放入 ESP |
| `b5q.dtb` | 从 Mu-Silicium 的三星 b5q.dts 编译的固件设备树 |
| `boot.json`、`build-report.json`、`verification-report.json` | 镜像布局、源码版本、补丁、校验结果 |
| `menu-qemu.png`、`menu-qemu.log`、`payload-qemu.log` | 模拟器截图与两次功能检查日志 |
| `SHA256SUMS` | 发布文件校验值 |

脚本在本机构建、打包，不对手机执行写入。

## 已接入的内容

补丁 `patches/mu-silicium/0001-b5q-unixnu-interface.patch`：

- 在 b5q DSC/FDF 中嵌入 UniXNU、UniXNUDxe、UniXNURamDiskDxe、DarwinBoot。
- 映射 UniXNULib；沿用平台现有的 HobLib、FdtLib、DiskIo、PartitionDxe、FAT 和 UnicodeCollation。
- 编译 HelloPayload，放入 FAT 文件系统供交互测试。

保留 b5q 上游的 DisplayDxe、ButtonsDxe、UFSDxe 与 USB 驱动选择。固件基址
`0xA7100000`、大小 `0x300000`；BootShim 与 FD 使用 gzip 后追加 b5q DTB，Android
header version 为 4、对齐 4096 字节。UEFI Secure Boot 的构建开关设为 0，便于加载
本阶段未签名的 EFI 程序；这项设置不改变手机 BL 状态。

补丁 `0002-bootshim-describe-full-image-size.patch` 将 ARM64 Image 头中的 image_size
从仅 FD 大小改为 BootShim + FD 总长。本次 shim 为 112 字节；FD 长度和复制范围不变。
这样可通过 UniXNU 官方打包器的完整镜像尺寸检查。

菜单配置来自 `esp/EFI/UniXNU/unixnu.toml`。启动后有 EFI 加载测试、Tools、返回固件、
重启、关机五项；有输入设备时停留等待选择。Tools 子菜单由当前加载的菜单插件提供，
本次未接入 Advanced Logger，因此没有 QR 日志工具。EFI 加载测试停留约 15 秒后返回；
其 `PASS 0 passed 0 failed` 表示无额外注入断言的程序正常运行，不代表硬件测试通过。

本次 boot.img 自带菜单 FAT 内存盘，首次显示菜单不要求先创建 ESP。
之后改用实际 ESP 时，应重新打包以移除内存盘内的菜单配置，或同时更新它，避免多卷上
同名 `EFI/UniXNU/unixnu.toml` 的枚举顺序影响配置选择。`unixnu-b5q-esp.tar` 是目录内容
归档，不是分区格式化或分区表镜像。

这里的 `b5q.dtb` 是三星 Android/UEFI 固件入口使用的 DT，不是供 XNU 使用的 Apple DT。
后续 XNU 板级设备树和 macOS payload 仍需单独适配。

## 已验证的范围

- b5q DEBUG 固件完整编译成功，压缩 FV 约占 1.32 MiB，落在 3 MiB 布局内。
- 从最终 FD 解压 FV，确认四个 UniXNU/DarwinBoot 模块确实内嵌，逐字节匹配交付的
  AArch64 PE 文件；确认 DiskIo/FAT 驱动存在。
- 解包 boot.img，比对 gzip 固件、BootShim 长度和地址、追加 DTB、FAT ramdisk。
- `fsck.fat -n` 通过，逐个从 FAT 读回文件并比对，检查 Odin/ESP tar 内容。
- 使用本次构建的 EFI 程序在 QEMU/AAVMF 中以 1080×2640 GOP 运行，配置读取、五项
  竖屏菜单、EFI 加载与返回均通过，未出现 ASSERT。

QEMU 使用自己的 AAVMF 固件，只验证本次 EFI 程序和配置。尚未实机验证 b5q 的
Android 引导交接、面板、音量/电源按键、UFS 或 initrd 发布，也未验证 Odin 接受与启动。
交付物状态为实机测试用构建，不是已确认可在 Flip5 上启动 macOS 的镜像。
