# b5q macOS 27.3：ESP-v2 菜单交付修复

## 这版修什么

上一版只安装 `macosroot` 和 `boot`，没有把新菜单树安装到实体 ESP。这是交付缺口。你回读哈希相同证明写入一致，不证明菜单扫描到了新文件。

本版不重新编译 XNU，不启动 CI：

- 将相同的新内核、ADT、trust cache、Data seed、UniXNU、DarwinBoot 和新菜单放入 **800 MiB 的 `esp.img`**。
- 菜单显式加入 `[[driver]] path = "Drivers/DarwinBoot.efi"`；仅把 EFI 文件放入 Drivers 文件夹并不会自动加载它。
- 新菜单标题为 **`b5q macOS - ESP v2`**，XNU 项为 **`b5q macOS 27.3 - ESP v2`**，默认项为 xnu，不含 HelloPayload。
- `boot.img` 沿用相同的 kernel/固件/DTB 传输字节，但 ramdisk 改成 **裸 FAT16**，不再使用 UNXNFAT1。
- 小 RAM FAT 只有菜单入口，没有 `unixnu.toml`，避免 RAM 盘上的旧 hello 配置盖过实体 ESP 的配置。UniXNU 必须继续扫描物理 ESP，读取新文件。
- `macosroot.img` 与上一版完全一致，不必重复写入。

从真实 boot 提取的 UniXNURamDiskDxe 含 `UNXNFAT1` 支持，因此“固件只会识别裸 FAT”不是已证实结论；不过这版完全不依赖压缩 RAM FAT 能否正确传递和挂载。

## 你已经刷过 macosroot：只修 ESP 和 boot

手机在 TWRP，电脑进入 **ESP-v2 包目录**后运行：

```bash
python3 install-firstboot.py --repair
```

脚本先校验镜像和分区，卸载已挂载的 ESP，然后依次写入并回读验证 ESP、boot。它不会重写 macosroot，不会改变 GPT，不会改 userdata，也不会自动重启。最后显示 `INSTALL PASS` 再从 TWRP 重启 System。

## 完整首次安装

```bash
sha256sum -c SHA256SUMS
python3 install-firstboot.py --check
python3 install-firstboot.py --all
```

`--all` 顺序为 macosroot → esp → boot，每项写完核对读回 SHA256。脚本验证的是：

| 分区 | GPT 起点（4096字节LBA） | 容量 |
| --- | ---: | ---: |
| macosroot | 49692663 | 51539607552 字节 |
| esp | 3162880 | 838860800 字节 |
| boot | 152448 | 100663296 字节 |

Linux sysfs start/size 以512字节为单位，脚本会换算。多个设备连接时加 `--serial 设备序列号`。

## 手动用 TWRP 刷镜像

- `esp.img` → **ESP**，800 MiB。不能刷到 boot、super 或 userdata。
- `boot.img` → **Boot**。
- 根镜像已经回读一致就不必重复刷。

某些 TWRP 的“刷入镜像”列表不显示 ESP，这时用电脑上的 `--repair`，不要选择别的分区替代。`boot-b5q-esp-v2.tar` 仅含 boot，**单刷 TAR 不会更新 ESP**。

## 不想替换整个 ESP：复制新菜单文件

将 ESP 挂载到 `/tmp/b5q-esp` 后，可以合并复制本包的 EFI 树。不要把目录多套一层变成 `EFI/EFI/UniXNU`。

```bash
adb shell 'mkdir -p /tmp/b5q-esp && mount -t vfat /dev/block/by-name/esp /tmp/b5q-esp'
adb shell 'mkdir -p /tmp/b5q-esp/EFI/UniXNU/Drivers /tmp/b5q-esp/EFI/UniXNU/Payloads /tmp/b5q-esp/EFI/BOOT'
adb push esp-files/EFI/UniXNU/Drivers/. /tmp/b5q-esp/EFI/UniXNU/Drivers/
adb push esp-files/EFI/UniXNU/Payloads/. /tmp/b5q-esp/EFI/UniXNU/Payloads/
adb push esp-files/EFI/BOOT/BOOTAA64.EFI /tmp/b5q-esp/EFI/BOOT/BOOTAA64.EFI
adb push esp-files/EFI/UniXNU/unixnu.toml /tmp/b5q-esp/EFI/UniXNU/unixnu.toml
adb shell 'sync; cat /tmp/b5q-esp/EFI/UniXNU/unixnu.toml; umount /tmp/b5q-esp'
```

这样保留 ESP 中其他文件。只要现在的固件确实已经从实体 ESP 读取 hello 配置，更新实体 ESP 文件就是可独立采用的菜单修复，不要求再次刷 macosroot。配套的新 boot 用于去掉 RAM 压缩/旧配置路径的不确定性。

## 启动与输入

应看到标题 `b5q macOS - ESP v2`，默认启动 `b5q macOS 27.3 - ESP v2`。看见 HelloPayload、旧 test 或 `RESULT PASS 0 passed 0 failed` 仍是旧配置，并非 XNU 启动。菜单用上/下、Enter；串口会显示配置载入、DarwinBoot 驱动和 `boot: entry 'xnu'`。已内置 loader 的固件对显式驱动可能返回 `Already Started`，此状态与缺失 loader 不同；已有协议仍可使用。

本地 QEMU 回归仅验证真实菜单程序从另一个磁盘的 ESP 找到配置、显式加载 DarwinBoot 并进入 XNU 文件读取，不验证 SM8550 上启动内核。内核仍是原先的只读系统根、RAM Data 首版；没有预置用户名/密码。RAM Data 重启丢失；Metal、输入、UFS 交接和真正桌面启动尚无实机成功证据。`--repair`/`--all` 中的 ESP 写入会替换整个专用 ESP，原有其他引导文件也会被替换；如需保留它们，使用上方合并复制法。本次构建没有连接或写入手机。
