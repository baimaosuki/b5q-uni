# v33d 三项 P0：本地审查交付

当前状态：**LOCAL_REVIEW_READY / HOST_VERIFIED_PENDING_HARDWARE**。三项本地修复与验证已完成；按本次附件要求停在审查环节。未推送、未触发 CI、未生成 ESP、未连接或刷写手机，未重编 XNU core/GPU，未修改现有 Data。

## 差异与测试入口

- 完整可应用 diff：`artifacts/b5q-v33d-p0-review/complete.diff`。
- 所有本次修改文件及 SHA：本报告同名 `.json` 的 `changed_files` / `source_sha256`；另含两份未改动验收脚本的 SHA。
- 单测/目标编译完整输出：`artifacts/b5q-v33d-p0-review/full-test-output.txt`，各项原始日志仍分别保留。
- 可复现入口：`python3 scripts/b5q-install/pre-ci-v33d.py`。该入口仅执行本地检查。
- 原始二进制证据：`26C5035r-USB-original.disasm.txt`、`26C5035r-USB-personalities.plist`、`HAL-domain-configure-original.disasm.txt`、`original-binaries.json`（均在上述审查目录）。

主仓 b5q 文件尚未纳入当前索引，普通 `git diff` 会漏文件。因此完整差异使用已交付元数据提交 `bbefab15224eb4d0ba65938bc76cfc8e5477b8b1` 为基线，固件文件使用修改前快照；在临时 Git 目录验证整份 patch 能应用且逐文件与现有源码相同。没有切分支、改主仓索引或动用户的 TWRP 修改。

## P0-1：DMA 权限和遍历属性

| 项目 | 最终值 / 验证 |
|---|---|
| USB/共享正常 RAM 叶子 | `((3ULL << 53) | 0x748ULL)`，AP01、Attr2、SH3、AF1 |
| PCIe MSI Device 页 | `0x740ULL`，保留 Attr0 Device，补 AP01 |
| USB / PCIe / Audio / Video SCTLR | `0x00c01027`，CFCFG/CFIE=0，ASIDPNE=1 |
| TCR | `0x00803510`，4K / L0 / WB-IS |
| 表页生命周期 | 原有 EfiReserved、保留区排除、独立域、Cache Clean + dsb 均保留 |
| 生产函数测试 | `BuildUsbTables` + 原始 `DarwinOutsideRanges`；walk `0xcb14d000`、`0x9838b1000`，全部低段候选页及 6GiB owned 中允许分配页逐 4K 核验 |

原厂 reserved/no-map 洞仍拒绝映射。单测用输入 EFI 内存图验证生产函数，未把模拟内存图称为新实机内存图。新增可复现补丁 `0014-b5q-dma-unprivileged-wbis.patch` 同步进入固件工作树、补丁重建检查和原有工作流的补丁应用清单。

HAL 原始文件 SHA256：`a6020ff87c4526baf9f8cb39870e618691a83cf5ecb8ae4cd1e9e1d42ed9c2ef`。

- RVA `0x2cd0` 是默认配置生成器，不是强制配置约束。
- RVA `0x2db0` 的 domain_configure 在 `0x2dcc..0x2e08` 检查指针与 VMSA；`0x2e10..0x2e7c` 原样复制配置字段；`0x2e94` 更新已挂接银行。
- 在 Unicorn 执行未修改机器码：新建且尚未 attach 的 domain 接受 48 字节新配置，返回 0 且字段完全相同；空 domain/config 返回 3，VMSA=1 返回 21。没有用替代 HAL 函数返回假成功。
- 软件执行验证 ABI/接受行为，未验证实体 SMMU 或外设执行。

## P0-2：USB Device 配置、电源重试与 QMP

初始 `gDeviceStackAllowed=true`；provider 使用真实 `standardBringup` OSString，controller 完成 start 后 `registerService()`，让原生配置器匹配。周期 worker 重试未初始化的 cable 请求，成功 ACK 或 powerOn 后停止；拔线、Host、转换期间及无 DMA 授权均禁止旧 Device 请求。roleThread 成功初始化 QMP 后同步 orientation，避免 followOrientation 立即再重置。Host 日志新增 PORTSC1/2、ERDP、GSBUSCFG0。

原始 **macOS 26C5035r** kernelcache SHA256：`d1003b5143ffd88439b4d45b6017f587171cfe6855660bed05370a2ea5db9fe9`。

| 原始地址 | 实证 |
|---|---|
| `0xfffffe000b1cb0e8` / `...b1cb128` | AppleUSBXDCI::start；通过 GOT `0xfffffe00089ac550` 和原始 superclass 表 +0x600 调用 IOUSBDeviceController::start `...b1ae86c` |
| `...b1aea5c` → `...b1acec8` | Controller::start 调用 prepareDefaults；`...b1ade74` 读取 configuration-string / ConfigurationType |
| `...b1c47a4` / `...b1c4844` | IOUSBDeviceConfigurator::start 调 createUSBDevice `...b1bcdf4` |
| `...b1bf0d8` / `...b1babd8` | 原始虚表调用 startUSBStack（slot0xa40）及 joinPowerPlane（slot0xa48） |
| `...b1b1578` / `...b1b15b8` / `...b1b1608` | PMinit、joinPMtree、registerPowerDriver（5 个电源状态）；原始 IOService vtable 逐项解析 |
| `...c3564b8` → `...c3565fc` | initialized bit0 为 0 时返回 8；与 cable-result=8 对应 |

原始 prelink personality 确有 `Configuration-standardBringup`，匹配 IOUSBDeviceController 的 ConfigurationType，配置器为 IOUSBDeviceConfigurator；不存在 standardMuxOnly personality。oneplus13t 指南是背景参考，没有借用其其他系统版本 ABI。

ASan/UBSan 执行生产 cable / retry / roleThread / followOrientation：`8→8→0` 后不再重试；断线/Host/无 DMA 不重试；正反方向 QMP 各只初始化一次。原有 15×1s OTG→BC80/CC1=09 闭环（含 3s 非 DP 超时、0 次 leaveRole/断电/代际抖动）继续通过。

## P0-3：手机触控单击

- B5qTouchMouse 唯一持有 held；所有 0x1a 包使用该状态，无 wn8030 buttons/click 依赖。
- HID X/Y 恢复上游物理分辨率，Push/Pop 隔离滚轮单位；Pop 后明确恢复 Generic Desktop Usage Page，解析测试验证滚轮/横滚没有遗留物理单位。
- 输入转换回 0..4095，X /5、Y /2 带余数；180X/90Y/300ms 点击候选严格冻结指针及双指滚动；越界/超时以当前点重新设锚，不发送跳变。
- 轻点抬手后保持 32ms，再由原 workloop clickTimer 释放；排队脉冲保留至少 8ms up；关闭双击拖拽；支持双指自然 2→1→0 右键。
- 诊断输出 clicks_left/right、taps_cancelled_slop/time、lifts_seen；首次 8 次事件记录，其后最多每秒一次（无堆分配、无新线程）。event-driver 变化取消旧手势/定时器，保留累计计数。

四项指定测试全部通过：100/-40 抖动与80ms抬手全程无移动且32ms按压；间隔120ms两次完整单击；超死区无跳变且物理近似1mm输出X=12/Y=13、抬手不误点；完成释放后新触点没有多余 btn0。还覆盖正负余数、静止180ms、身份变化、3..10指恢复、两种右键抬手次序、滚动死区、异常释放、队列及 uint32 毫秒回绕。

旧回归中“第二次轻点应拖拽”和旧指针内部字段断言已按本次明确的新行为替换；保留其他触控协议、身份/边界/恢复断言。Wi-Fi/镜像回读两份验收脚本未改。

## 本地结果与边界

- 本地总入口 12 组全部 PASS，含完整保留 P0–P4 回归和 v33b 22 组检查；详见 JSON 和原始输出。
- QcomDwc3 / NativeHidInput / B5qTouch：实际 arm64e 对象编译通过，未解析符号和重复外部定义均为 0。
- EDK2 目标编译通过：UsbDma、PcieDma、MediaDma、B5qHandoffDxe、DpDma、DarwinBoot、MemoryMapLib；补丁重建 14 项与当前文件逐字节一致。
- USB→ArmCpu、6 项 GMU、9 项 Clock/Button/HID/Thermal 及触控 IRQ PAC 通过；118 项 timer/workloop/其他回调签名通过。30 个板级对象零 EL1 apps_smmu 引用检查通过。
- 原生完整 kernel/固件最终链接、CI 返回二进制及实体枚举不属于本地检查已证明结果，等本次审查批准后执行。

v33d 实机日志本地独立解码：两槽 CRC 有效，最高 seq156，共1765行，lock-lost=61；没有将其描述为零丢失。只摘取必要硬件证据，没有发布完整 bootargs 或设备身份。

Wi-Fi 顺带核查只报告事实：三星 gcc-kalama 定义 6b070[1:0] 的0=PHY PIPE、2=XO，branch enable=52008bit4、halt=6b048；当前时序已有 XO→PIPE 与 bit4 使能。因此 pipe=0 是选择值，不能证明停钟；没有猜测性修改 PCIe 时序，实际 L0 超时仍待实机证据。

**等待用户审查；未推送、未触发 CI、未生成 ESP。**
