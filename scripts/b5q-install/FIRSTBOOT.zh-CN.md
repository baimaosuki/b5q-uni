# Z Flip5 b5q：macOS 27.3 首版启动候选包

目标为 `macos-27.3-26C5035r`，XNU `12377.121.6`。系统根来自本工作区重新解析的原始 IPSW；B5qUfs 从 `macosroot` 提供经过签名及逐块校验的 OS、SystemOS、App；Data 使用与内核 UUID 一致的 RAM 镜像。

## 1. 文件与布局

- `boot.img`：沿用现有 b5q 启动传输代码，装入新内核、ADT、原始 trust caches 和 Data seed 的 FAT 负载。
- `kernel.macho`：完整链接的原始构建输出。
- `payload.img`：包含入口探针及 panic 屏幕补丁后的部署内核，以及对应 ADT、trust cache、Data seed 的 FAT 文件系统。
- `macosroot.img`：SHNGROOT v2 原始镜像，包含三个系统卷及三份逐块哈希表。
- `esp-files/EFI/`：与 payload 相同的一组可复制到现有 ESP 的文件。
- `package.manifest.json`、`BUILD-STATUS.json`、`SHA256SUMS`：实际来源、哈希、大小和验证范围。
- `install-firstboot.py`：由你执行的刷入工具，需要电脑 Python 3 和 ADB。

采用你提供的 4096 字节 LBA 布局：

| 分区 | 起始 LBA | 末尾 LBA | 容量 |
| --- | ---: | ---: | ---: |
| boot | 152448 | 177023 | 100663296 字节（96 MiB） |
| esp | 3162880 | 3367679 | 838860800 字节（800 MiB） |
| macosroot | 49692663 | 62275574 | 51539607552 字节（48 GiB） |

## 2. 在 TWRP 中安装

将整个包解压到电脑，保留 `macosroot.img` 和脚本的相对路径。手机已经进入 TWRP 后，在包目录运行：

```bash
sha256sum -c SHA256SUMS
python3 install-firstboot.py --check
python3 install-firstboot.py --all
```

`--all` 首先校验两个本地镜像及设备布局，再写入并读回验证 `macosroot`，然后写入并读回验证 `boot`。镜像直接从电脑流式传输，无需先把 17.6 GB 文件放到手机。每一步须看到 `PASS`，最后显示 `INSTALL PASS`。脚本保留 `macosroot` 未使用的尾部，系统 Data 仍在 RAM；不需要格式化这块分区。

只更新单个镜像时：

```bash
python3 install-firstboot.py --root
python3 install-firstboot.py --boot
```

连接多个 ADB 设备时，在上述命令添加 `--serial 你的设备序列号`。Linux sysfs 的 `start`、`size` 始终以 512 字节为单位，脚本会换算为字节再匹配你给出的 4096 字节 GPT LBA，避免单位混淆。

完成后，在 TWRP 选择重启到 System。启动镜像的 RAM 负载已经带有 UniXNU 菜单和 DarwinBoot 文件，采用这条路径时无需修改 ESP。

## 3. 放入已有 UEFI 菜单

若你继续用已有的 UEFI 启动镜像，可以把 `esp-files/EFI/UniXNU/` 中的 `Payloads/`、`Drivers/` 和 `unixnu.toml` 合并到该菜单**实际读取的 FAT 卷**的 `EFI/UniXNU/` 下。整组文件必须来自同一包；部署内核是 `esp-files/EFI/UniXNU/Payloads/kernel.macho`，它已经带入口诊断补丁，和包根目录的原始链接内核哈希不同。

你已将 ESP 格式化为 FAT 且希望通过 TWRP 复制时，可执行：

```bash
adb shell 'mkdir -p /tmp/b5q-esp && mount -t vfat /dev/block/by-name/esp /tmp/b5q-esp'
adb push esp-files/EFI /tmp/b5q-esp/
adb shell 'sync && umount /tmp/b5q-esp'
```

挂载失败就停止这条复制路径，使用第 2 节的 `boot.img` 路径。上述命令没有格式化步骤。若菜单仍显示旧的 `UEFI payload test`，说明它读取了另一个卷的旧配置；新 `boot.img` 内已包含同组配置与文件。

## 4. 启动与输入

新配置的 XNU 项为 `UniXNU b5q macOS 27.3`。具体默认项、倒计时和内核参数见包内 `esp-files/EFI/UniXNU/unixnu.toml`。UniXNU 官方菜单使用上/下选择、Enter 启动、任意键停止倒计时；USB 键盘需固件实际枚举成功后才能使用。

DarwinBoot 的顶部绿带表示已走到跳转内核之前；入口探针继续显示阶段条。进入存储路径后，目标日志是三次 `B5qUfs: authenticated ... volume ... ready`，分别对应 SystemOS、App、OS；这比仅显示菜单更接近真正系统启动。panic 文字直接显示在主屏。

Data 由原始 `Templates/Data` 创建，保留原有所有权，没有预设账户、密码、自动登录或跳过设置向导。macOS 内部的触控、键鼠以及 Setup Assistant 可操作性需要对应硬件路径实际启动，菜单键盘工作本身不能证明这些路径可用。

## 5. 当前验证范围

这是供首次上机验证的启动候选包。构建、完整符号映射、根策略绑定、文件校验和压缩负载回解已在主机完成；实际 macOS 桌面、Metal、三星输入及 UFS 交接尚无本机启动结果。UFS 首版依赖固件保留已上电链路，并只接受专用可用 SMMU 上下文；不含冷启动 PHY/复位适配。Data 修改会在重启后消失。B5qUfs 没有持久块写命令，安装脚本只向显式选择的 `boot`/`macosroot` 写入，不改 GPT、userdata 或三星受保护分区。沿用的固件自带 UFS DXE，其完整内部访问行为不由本次 XNU 驱动的只读约束证明。
