# review7 联合修复

构建提交 `37493ec8e4895f71e6e3ff7ac941e3b9a8b3d6e2`，联合 CI `45618191537`。验证脚本另有纯验证提交 `09e7203cb25f8c70af7c984dd12767532ea22e50`；运行时代码与构建提交逐字节一致。

| 项目 | 本地结果 | 实机边界 |
|---|---|---|
| PCIe DMA 64 MiB | 生产端、DarwinBoot、内核接收及 Arena 上限一致；逐页映射、低地址、保留区和 MSI 不相交检查通过。回传 PcieDma IR 和 loader PE 已证明 64 MiB；旧 32 MiB loader 负例拒绝。 | 本轮新镜像尚未刷机；review6 的 MISSION MODE 只作为旧版证据。 |
| 触控 | mode=11 全量优先，C1 回退，kind=1 过滤；5/2 增益、326 CPI、220/115 slop、±64 限幅；480/260 或 80ms 跳点重锚定。单击 32ms 保持、双指右键、帧原子替换和位移回归通过。 | 新版触感仍待实机；不把主机测试写成实机成功。 |
| 蓝牙 | 修复 pending TX 无重试期限，以及 qbt_boot 等待忽略 FIFO 期限。生产代码经 3.2Mbps 配置、64 连续分片、CTS 暂停、丢水印通知及部分 RX 回复测试。失败时输出 TLV/线路/FIFO 状态。 | 旧日志缺少实际失败分片与 FIFO 现场，不能声称已经在手机上证明该次 -60 消失。固件文件哈希不变。 |
| USB Host | Core reset 后恢复 GCTL.DSBLCLKGTNG；可选 usb-utmi=1 默认关闭；QMP/mux/GCTL 诊断。READ64/WRITE64/电源回调提前检查 HSE，环指针诊断请求现有日志线程同步提交。硬中断只请求，不执行 UFS I/O。 | Device 模式基线保留；新 Host 枚举与 HSE 结果待实机。CCstat=0/DFP 仅限频诊断，不猜测插入状态。 |

TCR2 保留 `0x0003c071`，PASIZE=36bit 覆盖当前 64GiB 映射上限及日志所见 `0x88ba04000` 地址。原有 HAL 配置、flush、页表属性、2048 页 USB 表池及零 EL1 apps_smmu 检查保留；未因 sheng 使用 40bit 就盲改已验证 Device 配置。

固件 FD 已下载并校验 SHA256：`a98a68dbe8921e578cb54a27ea7a592414015846897ada7af0b97d8de1765c37`。最终 CI、返回门禁及配对 IMG 的精确结果记录在同目录 `review7-release.json`，只有该文件中的实际完成状态才代表交付完成。
