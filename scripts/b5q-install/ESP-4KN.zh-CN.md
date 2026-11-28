# b5q 恢复原有 UniXNU payload 部署基线

v3 自行增加的延时复位选项和 v4 的中间内核替换都已撤回。
本包恢复之前 ESP v2 的全部文件字节，实体 FAT 容器保留本机需要的 4096 字节扇区。

## 本次恢复依据

锁定的 UniXNU 提交为 `563595abedfdfa413ad583b66b6176d82007e633`。
`docs/guide/debugging.md` 第202至230行说明：原有 `panic_screen=true` 会让 payload 步骤对内核副本执行 `--panic-screen --no-reset`，其中也包含蓝色入口条和品红色 MMU 前标记。
`docs/porting/bring-up.md` 要求保留上次镜像、一次隔离一个变化。

此前把 `panic_screen` 关闭并用中间 kernel 覆盖已处理部署副本，会让蓝/品红条消失，也同时撤掉原有 panic 显示；这不属于单纯的 4Kn 格式修复。
因此，上一版仅剩绿条不能单独证明执行比以前更早卡住。

## 文件恢复范围

- `board.toml` 恢复原来的 `panic_screen=true`，不设置 `entry_probe_reset_delay`。
- 原有设备脚本恢复到 v3/v4 之前的版本，撤销助手新增的复位模式。
- ESP 内的部署内核恢复为真实 CI 完成的 payload 成员，其 SHA256 为：
  `7ea22869a35061a45d00221d503442a3d58b6f845c6d1d7fbecd7f49ff18cacf`。
- 菜单、DarwinBoot、ADT、trust cache、Data seed 与 ESP v2 逐文件字节相同。
- 没有重编内核，没有重新执行探针补丁，没有增加复位测试项。
- 只将实体 ESP 格式保留为 `mkfs.fat -F32 -S4096 -s1`；boot 和 macosroot 沿用原文件。

包根目录 `kernel.macho` 是编译中间产物，记录原始构建来源。真正部署的 kernel 在 `esp-files/EFI/UniXNU/Payloads/kernel.macho`，已包含在 `esp.img`。不能再次用根目录中间产物覆盖 ESP 中的完成副本。

## 恢复安装

电脑上的目录已准备好。手机在 TWRP 后执行：

```sh
cd /home/baimao/zflip5/artifacts/b5q-esp-guide-restored-v5
sha256sum -c SHA256SUMS
python3 install-firstboot.py --esp
```

只替换并回读验证专用 800MiB ESP。它包含先前的完整 EFI 文件树，会覆盖该 ESP 中的其他文件。
本包不重刷 boot、不重刷 macosroot、不修改 GPT。

如果你已经将 ESP 格式化为 4096 字节并成功挂载，也可以按 `ESP-REPAIR.zh-CN.md` 的合并复制步骤，复制本包 `esp-files/EFI` 里的文件，最后复制 `unixnu.toml`。不要直接复制根目录的中间 `kernel.macho`。

恢复后菜单标题沿用 `b5q macOS - ESP v2`，不会再出现 CONTROL/MMU/ARM_INIT 自定义测试项。版本由包内 manifest 和文件 SHA256 识别，避免再改动配置来制造差异。

此包仅恢复此前已执行到品红条的部署文件与原有 panic 显示，不能把回到既有基线称为修复了更后面的 Samsung/XNU 启动停点。本次没有连接手机或触发 CI。
