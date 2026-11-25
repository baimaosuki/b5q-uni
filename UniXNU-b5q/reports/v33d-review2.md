# v33d 第二轮本地审查

状态：**LOCAL_REVIEW_READY / HOST_VERIFIED_PENDING_HARDWARE**。附件 9 组 P0、4 组 P1 拆为 52 行本地要求，逐项完成；下表的 LOCAL_DONE 只指本轮源码、Host 与目标对象验证。**未提交、未推送、未触发 CI、未生成部署 ESP/FD、未操作手机。**

## 审查入口

- `artifacts/b5q-v33d-review2/complete.diff`：对本轮修改前 554 文件快照的完整增量差异，包含新增文件。
- `artifacts/b5q-v33d-review2/cumulative.diff`：对先前交付提交与固件原始快照的累计差异，便于核查上一轮到本轮的全部实现。
- `artifacts/b5q-v33d-review2/full-test-output.txt`：完整 stdout/stderr，包含保留的首次失败和最终通过日志；以 `pre-ci-review2-final.log` / `v33d-local-gates.json` 为最终结果。
- `artifacts/b5q-v33d-review2/SHA256SUMS`：源码、报告与证据哈希。
- 同名 JSON：52 行映射、源码 SHA、原始输入、编译与 PAC 凭据。
- 本地复现：`B5Q_GATE_WORK=artifacts/b5q-v33d-review2 python3 scripts/b5q-install/pre-ci-v33d.py`。

普通 git diff 会漏掉主仓忽略/未跟踪的设备源码，因此 diff 使用真实 before 快照，不切分支、不改主仓索引。两份差异都在临时 Git 目录执行 apply --check、实际 apply 和逐文件字节比对。用户另有的 TWRP 修改保持原状。

## 明确纠正旧报告

上轮报告的 OSString 方案和约 828 CPI 结论不成立，本轮已修正。真实 macOS **26C5035r** kernelcache SHA256 为 `d1003b5143ffd88439b4d45b6017f587171cfe6855660bed05370a2ea5db9fe9`。

`IOUSBDeviceController::prepareDefaults` 经 GOT `0xfffffe00089aa230` 取 OSData::metaClass（`0xfffffe0007f2ca00` → gMetaClass `0xfffffe000c9f1cf0`），在 `0xfffffe000b1ade8c` safeMetaCast，`0xfffffe000b1adeb4` 经 slot0x198 调 OSData::getBytesNoCopy。因此 configuration-string 必须是含 NUL 的 OSData。原始反汇编与 personality 在本审查目录保留。

鼠标 PhysicalMin/Max 改为 ±10051 centi-inch（UnitExponent=-2）：`32767 / 100.51 = 326.007 CPI`，误差小于 2%，滚轮单位隔离保留。首次 event-driver 绑定发中性报告。

HALIOMMUDxe SHA256 为 `a6020ff87c4526baf9f8cb39870e618691a83cf5ecb8ae4cd1e9e1d42ed9c2ef`。本轮未改 0014 的 SCTLR=`0x00c01027`、TCR=`0x00803510`、TCR2=`0x0003c071`、MAIR0=`0x00ff0400`、USB=`0x748`、MSI=`0x740`。原始 HAL RVA0x2db0 机器码四个正反案例仍通过；这不等于实体 DMA 验收。

## 逐项修改与证据

| 要求 | 本地状态 | 修改 | 文件 | 验证日志/门禁 |
|---|---|---|---|---|
| P0-1/config-type | LOCAL_DONE | configuration-string 使用含 NUL 的 OSData；原版 OSData metaClass/GOT 与 getBytesNoCopy 实证纠正上轮 OSString 结论。 | `UniXNU-b5q/package/QcomDwc3.cpp` | `v33d-review2`, `original-binaries`, `target-compile` |
| P0-1/cleanup | LOCAL_DONE | 统一释放 zero/config/range/ranges/nub/controller/映射与锁；role worker 成功后才发布服务。 | `UniXNU-b5q/package/QcomDwc3.cpp` | `v33d-usb-device`, `v33d-review2`, `target-compile` |
| P0-2/1-static-map | LOCAL_DONE | GetMemoryMap 使用 32768 B、8 字节对齐静态缓冲；容量不足保留真实 EFI 错误；无瞬时池释放空洞。 | `uefi-b5q/Platforms/Samsung/b5qPkg/Drivers/B5qHandoffDxe/UsbDma.c` | `v33d-dma`, `v33d-review2`, `firmware-target`, `v33d-packaging` |
| P0-2/2-domain-lifetime | LOCAL_DONE | Delete 与 FreePages 均限制在 Attach==NOT_RUN 分支；可能已挂接的域/页表保持存活。 | `uefi-b5q/Platforms/Samsung/b5qPkg/Drivers/B5qHandoffDxe/UsbDma.c` | `v33d-dma`, `firmware-target` |
| P0-2/3-order | LOCAL_DONE | PCIe、Media、DP 及最终内存图缓冲准备在 GetUsbDmaResult 之前。 | `UniXNU/drivers/DarwinBoot/DarwinBootPkg/Driver/DarwinBoot.c` | `v33d-review2`, `firmware-target` |
| P0-2/4-input-retention | LOCAL_DONE | 有 USB handoff 属性时，最终 ExitBootServices 内存图不合成释放 input/payload 页，阻止未映射页进入 XNU 分配器。 | `UniXNU/drivers/DarwinBoot/DarwinBootPkg/Driver/DarwinBoot.c`<br>`UniXNU/drivers/DarwinBoot/DarwinBootPkg/Driver/LoaderInputs.h` | `v33d-review2`, `loader-inputs`, `v33d-dma`, `firmware-target` |
| P0-2/5-live-patches | LOCAL_DONE | 新增后继补丁并接入正确依赖顺序；16 份补丁从锁定提交重建，git apply + diff -ruN 零差异。 | `patches/uefi-b5q/0015-b5q-usb-map-lifetime.patch`<br>`patches/uefi-b5q/0016-darwinboot-dma-order-inputs.patch`<br>`scripts/b5q-install/check-stage-firmware-inputs.py`<br>`.github/workflows/b5q-p0-p5.yml` | `firmware-reconstruction` |
| P0-3/1-families | LOCAL_DONE | 加入 IOUSBDeviceFamily、AppleUSBDeviceMux；7 个 family 成功加载后显式匹配。 | `UniXNU-b5q/package/UsbProbe.cpp` | `families`, `target-compile` |
| P0-3/2-null-guards | LOCAL_DONE | startMatching 前同时检查 catalogue 和 symbol；覆盖各 family 失败及 null 情况。 | `UniXNU-b5q/package/UsbProbe.cpp` | `families`, `target-compile` |
| P0-4/1-cpi | LOCAL_DONE | PhysicalMin/Max=±10051 centi-inch、指数 -2，实际 326.007 CPI；Push/Pop 保持滚轮单位独立。 | `UniXNU-b5q/package/B5qMouseReport.h` | `v33d-review2`, `touch-p0`, `host-abi` |
| P0-4/2-first-wake | LOCAL_DONE | event driver 首次 nullptr→非空且 mouseEnabled 时发中性报告唤醒指针管线。 | `UniXNU-b5q/package/NativeHidInput.cpp` | `touch-p0`, `target-compile`, `hid-timer-workloop-PAC` |
| P0-5/1-identify | LOCAL_DONE | command(2) 忽略 unsolicited 0x10，等待并验证 0x01 identify payload，不遗留真正回复。 | `UniXNU-b5q/package/B5qTouch.cpp` | `v33d-review2`, `target-compile` |
| P0-5/2-share-retry | LOCAL_DONE | IRQ share NotReady 最多 240×250ms 重试，失败日志/退出保持有界。 | `UniXNU-b5q/package/B5qTouch.cpp` | `v33d-review2`, `target-compile`, `all-cross-object-PAC` |
| P0-5/3-producer-barrier | LOCAL_DONE | native_touch_seq 奇数递增后立即 dmb ish，再发布坐标与完成序列。 | `UniXNU-b5q/package/B5qTouch.cpp` | `v33d-review2`, `target-compile` |
| P0-5/4-reader-stop | LOCAL_DONE | seqlock 最多四次稳定读取；stop 先解绑 touch/button sinks 再同步 workloop 停止。 | `UniXNU-b5q/package/NativeHidInput.cpp` | `v33d-review2`, `target-compile`, `hid-timer-workloop-PAC` |
| P0-5/5-c1-eid | LOCAL_DONE | C1 非坐标 eid!=0 跳过，不清除活跃触点；实测生产解析器覆盖 eid1/2/3。 | `UniXNU-b5q/package/B5qTouchProtocol.h` | `v33d-review2`, `touch-p0` |
| P0-6/1-sleep-clock | LOCAL_DONE | APPS-owned PPID0ba/type/subtype 核验，PMK8550 GPIO3 五寄存器配置/回读/幂等；先于 radio-enable。 | `UniXNU-b5q/package/B5qWcnPower.cpp` | `v33d-wcn-init`, `wireless-all-callbacks` |
| P0-6/2-aoss-qmp | LOCAL_DONE | 复用 QcomQmp：AOSS0c300000/IPCC00408000；原厂 DT 的11条 wlan_pdc 字符串完全相符；模块锁、1s ACK 超时、不覆盖未确认邮箱。 | `UniXNU-b5q/package/B5qWcnPower.cpp`<br>`UniXNU-b5q/scripts/b5q_bluetooth.py` | `v33d-wcn-init`, `wireless-all-callbacks` |
| P0-6/3-bt-smpg2 | LOCAL_DONE | radio masks={0x1f,0x1f}，蓝牙同样投票 smpg2 1012mV；纠正不存在 PMK8550GPIO3 的旧注释。 | `UniXNU-b5q/package/B5qWcnPowerCore.h` | `host-wcn-power`, `v33d-wcn-init`, `wireless-all-callbacks` |
| P0-6/4-tcs | LOCAL_DONE | TCS0 状态空闲检查、清 stale IRQ 后才触发；超时直接返回且不 finish 活跃 TCS。 | `UniXNU-b5q/package/B5qWcnPower.cpp` | `v33d-wcn-init`, `wireless-all-callbacks` |
| P0-6/5-tlmm | LOCAL_DONE | GPIO80 on3c3/off201、81=201、204=200；CFG 后重新写 IN_OUT，保持原厂启停次序。 | `UniXNU-b5q/package/B5qWcnPower.cpp` | `host-wcn-power`, `v33d-wcn-init`, `wireless-all-callbacks` |
| P0-7/1-phy-order | LOCAL_DONE | 113 项 table + 2 项 startup；先切 PIPE，再写200=0/244=3并延时1ms；检查214bit6及branch halt；CFG清掩码371f。 | `UniXNU-b5q/package/B5qPcieInputs.h`<br>`UniXNU-b5q/package/B5qPcieCore.h` | `host-pcie-controller`, `pcie-link-timing`, `wireless-all-callbacks` |
| P0-7/2-bcm | LOCAL_DONE | 只对ARC slave3截断zero padding；BCM高16位零不截断，unit1000/width16保留完整4words。 | `UniXNU-b5q/package/QcomRpmh.c` | `v33d-review2`, `target-compile` |
| P0-7/3-config-teardown | LOCAL_DONE | 链路UP才清busmaster，先于PERST；cfgRead/write链路检查、原生1/2/4字节访问，避免32位RMW误清RW1C。 | `UniXNU-b5q/package/B5qWifiBoard.cpp` | `v33d-review2`, `wireless-all-callbacks` |
| P0-8/1-aes-return | LOCAL_DONE | 所有线程 fail 调用后显式 return，避免终止后继续使用失败资源。 | `UniXNU-b5q/package/SoftwareAesProbe.cpp` | `v33d-review2`, `target-compile` |
| P0-8/2-psci32 | LOCAL_DONE | SMC32 返回先转 uint32→int32→int64；00000000ffffffff 正确识别为 -1。 | `UniXNU-b5q/package/B5qPower.cpp` | `v33d-review2`, `target-compile`, `all-board-zero-EL1-SMMU` |
| P0-8/3-dpu-quiesce | LOCAL_DONE | 时序运行时清CTL并等待FLUSH锁存；再停INTF等待idle后恢复saved；因果模型只在时序运行时清FLUSH。 | `UniXNU-b5q/package/B5qDpDpu.h` | `dp-dpu`, `dp-target`, `hid-timer-workloop-PAC` |
| P0-8/4-thread-exit | LOCAL_DONE | 按钮等待锁/蓝牙初始化失败路径先 thread_terminate(current_thread()) 再 return。 | `UniXNU-b5q/package/ButtonProbe.cpp`<br>`UniXNU-b5q/package/B5qBluetooth.cpp` | `v33d-review2`, `target-compile`, `wireless-all-callbacks` |
| P0-9/1-reuse-uploads | LOCAL_DONE | 删除45047962341硬编码；分页选择最新成功/未过期且完整artifact；上传GPU/Data/addon/trust/UsbDma对象与来源哈希。 | `UniXNU-b5q/scripts/fetch-b5q-reuse.py`<br>`.github/workflows/b5q-p0-p5.yml` | `v33d-packaging` |
| P0-9/2-packed-payload | LOCAL_DONE | packed/decode 后提取Data/addon/trust；生产代码用真实UNXNFAT1编码解码的非文件系统小夹具验证，无部署ESP。 | `UniXNU-b5q/scripts/reuse-completed-build.py` | `v33d-packaging` |
| P0-9/3-returned-constants | LOCAL_DONE | 返回FD模块须等于上传EFI；从ARM64 COFF/PE/bitcode执行代码校验0014常量、USB静态缓冲及无AllocatePool；旧EFI与破坏常量对象必须拒绝。 | `UniXNU-b5q/scripts/b5q_smmu_binary.py`<br>`scripts/b5q-install/check-v33b-returned.py` | `v33d-packaging` |
| P0-9/4-paired-package | LOCAL_DONE | CI与非CI均保留并验证三份GPU固件；BOOTAA64及DarwinBoot均取自配对FD，拒绝不成对入口。 | `UniXNU-b5q/scripts/package-batch2-esp.py` | `v33d-packaging`, `gpu-adt-preservation` |
| P0-9/5-empty-gate-work | LOCAL_DONE | 尊重B5Q_GATE_WORK并创建目录；命中源码绑定基线时仍创建当前目录的日志/凭据；覆盖新空目录路径。 | `scripts/b5q-install/pre-ci-v33d.py` | `v33d-packaging` |
| P1-1/1-host-route | LOCAL_DONE | Host teardown先 route(nullptr) 排空，再 terminate/release。 | `UniXNU-b5q/package/QcomDwc3.cpp` | `irq`, `target-compile` |
| P1-1/2-irq-lifetime | LOCAL_DONE | IOSimpleLock保护路由/回调字段；ISR局部retain并计inFlight；解绑等待排空；失败/解绑释放owner。 | `UniXNU-b5q/package/QcomDwc3.cpp` | `irq`, `target-compile`, `all-cross-object-PAC` |
| P1-1/3-storm-window | LOCAL_DONE | limit65536/s，route屏蔽中断后清storm/window；保留有界风暴隔离。 | `UniXNU-b5q/package/B5qUsbIrq.h`<br>`UniXNU-b5q/package/QcomDwc3.cpp` | `irq`, `target-compile` |
| P1-1/4-reset-order | LOCAL_DONE | setCoreRole先禁止Device，forceReset覆盖QMP重置；先切UTMI再复位PHY，repeater成功才放行Device；pending标志跨orientation路径。 | `UniXNU-b5q/package/QcomDwc3.cpp` | `v33d-usb-device`, `host-usb-p1`, `target-compile` |
| P1-1/5-atomic-attach | LOCAL_DONE | 每次attach记录powerOn快照；ForceHost/RoleWanted/RoleApplied/DeviceAllowed/maximReady均acquire-release。 | `UniXNU-b5q/package/QcomDwc3.cpp`<br>`UniXNU-b5q/package/B5qUsbBoard.cpp` | `v33d-usb-device`, `causal`, `target-compile` |
| P1-2/1-geni-recovery | LOCAL_DONE | 错误锁存到DONE或超时取消；即使无rx_buffer也排空错误RX；RFR水位depth-2。 | `UniXNU-b5q/package/GeniI2c.c` | `v33d-review2`, `host-v26-geni`, `target-compile` |
| P1-2/2-se8-idle | LOCAL_DONE | read/readWord/write前有界等待M_ACTIVE清零，再清stale M IRQ。 | `UniXNU-b5q/package/B5qUsbBoard.cpp` | `causal`, `wireless-all-callbacks` |
| P1-2/3-otg-rollback | LOCAL_DONE | 回滚保留m==0?0:m==5?5:4，不把原先关闭状态误开。 | `UniXNU-b5q/package/B5qMax77705.h` | `causal`, `host-usb-p1` |
| P1-3/1-bt-fifo | LOCAL_DONE | 修正M错误掩码；循环排空硬件RX，硬件仍有数据时保留retry_at。 | `UniXNU-b5q/package/B5qBtFifo.c` | `bt-fifo`, `wireless-all-callbacks` |
| P1-3/2-bt-wake | LOCAL_DONE | RX wake极性bit1；disable写0；断电还原76..79默认；任何WiFi运行态等待；transmit错误进入qbt_fail。 | `UniXNU-b5q/package/B5qBluetooth.cpp` | `host-bt-wcn6855`, `bt-fifo`, `wireless-all-callbacks` |
| P1-3/3-ethernet-detach | LOCAL_DONE | 回调锁+原子发布/解绑排空；nw_wifi_stop前detach；link经commandgate；controlStart正errno转负。 | `UniXNU-b5q/package/B5qEthernet.cpp`<br>`UniXNU-b5q/package/B5qWifiBoard.cpp` | `host-ethernet-lifecycle`, `wireless-all-callbacks` |
| P1-4/1-backlight | LOCAL_DONE | 发送前/失败后按W1C清bit24并记录；原子请求代号在worker重置失败预算。 | `UniXNU-b5q/package/B5qPanelCommand.h`<br>`UniXNU-b5q/package/B5qBacklight.cpp` | `host-panel-lid`, `failure-gates` |
| P1-4/2-keystore-copy | LOCAL_DONE | head与row相同的有界两段复制，NUL后不读取未初始化内核栈。 | `UniXNU-b5q/package/KeyStoreProbe.cpp` | `v33d-review2`, `keyprobe-target`, `target-compile` |
| P1-4/3-thermal-weak | LOCAL_DONE | 日志中弱符号先检查地址，再读取值，缺失返回0。 | `UniXNU-b5q/package/ThermalLevel.cpp` | `v33d-review2`, `target-compile`, `all-cross-object-PAC` |
| P1-4/4-temperature | LOCAL_DONE | Temperature=deciC*10+27315，检查绝对零度下界。 | `UniXNU-b5q/package/B5qDaily.cpp` | `host-abi`, `production-target` |
| P1-4/5-gmu-align | LOCAL_DONE | 预检每块bytes与at四字节对齐，拒绝非字对齐固件访问。 | `UniXNU-b5q/package/B5qGmuLoad.h` | `host-shared-gpu`, `target-compile` |
| P1-4/6-gpu | LOCAL_DONE | cache attributes传pa>>14；恢复重建ring1，硬件锁序列化DCVS/heartbeat/restart；删除ADT重复定义并保留严格hash/conflict检查。 | `UniXNU-b5q/package/B5qGpu.cpp`<br>`UniXNU-b5q/scripts/b5q_gpu_adt.py` | `target-compile`, `all-cross-object-PAC`, `gpu-adt-preservation`, `failure-gates` |
| P1-4/7-audio | LOCAL_DONE | speaker初始化/读取用IOLock及原子发布；DMA清零后dsb sy。 | `UniXNU-b5q/package/B5qAudioBoard.cpp`<br>`UniXNU-b5q/package/B5qAudioDma.cpp` | `production-target`, `joint-symbol-vtable-zeroMMIO`, `all-callback-PAC` |
| P1-4/8-dp-loader | LOCAL_DONE | HasExclusions接口对齐；支持chosen feature-mask bit6、b5q-f及显式DP开关；仅修已有交接，不新增显示路径。 | `UniXNU/drivers/DarwinBoot/DarwinBootPkg/Driver/B5qDpDmaLoader.h`<br>`UniXNU/drivers/DarwinBoot/DarwinBootPkg/Driver/DarwinBoot.c` | `dp-loader`, `firmware-target` |

## 验证结果与范围

- 总门禁 19 项通过，其中包括源码哈希绑定的完整 P0–P4 基线（43 项 P0、10 项额外 P1；P2/P3 门禁 22 项、P4 门禁 24 项有嵌套，不重复相加）及 v33b 22 项门禁。
- 新增生产代码 Host 案例：BCM unit1000/高字零、GENI 错误等待 DONE/无 buffer 排空、TouchComm 0x10→0x01、C1 非坐标事件、PSCI32 符号扩展、PCI 配置原生宽度/断链拒绝、326 CPI；原有触控、15s OTG 闭环与并发 IRQ 排空回归保留。
- PMK GPIO3 真正生产 helper 的写入/读回/幂等/错误拒绝、共享 QMP 的 11 条原厂字符串、AOP 确认/未确认超时、TCS busy/stale IRQ/超时不 finish 均通过；测试不声称在实体 AOP 上执行。
- 12 个通用 arm64e 对象无缺失导入、无重复外部定义；PAC 参与对象与本次目标产物逐字节一致。其余蓝牙、Wi-Fi、音频、视频、DP 对象由对应完整本地门禁编译。
- 无线联合闭包 124 对象、69 项认证回调契约通过，未解析/重复定义为 0；USB→ArmCpu、6 项 GMU、9 项 Clock/Button/HID/Thermal 契约通过；118 项 timer/workloop 等回调契约通过。
- 31 个板级对象指令扫描零 EL1 apps_smmu；无线 124 对象另有零 apps_smmu 检查。软件扫描边界见脚本，未替代实体 XPU 验证。
- 16 份 firmware/loader 补丁在三套锁定来源重建，git apply 成功、diff -ruN 返回 0；7 个 EDK2 目标对象编译通过。只生成审计对象，不链接新 FD/boot/ESP。
- 返回门禁本地验证：3 个真实 COFF 对象常量通过；破坏 SCTLR 的 3 份对象和旧 EFI 被拒绝；packed 提取用真实编码/解码的非文件系统小夹具；artifact 发现用 mock gh，无网络和新 CI。

完整测试保留了首错，包含旧测试桩/断言因新接口产生的编译或匹配失败、补齐 QMP 编译依赖以及缺失的失败日志等；修复后最终总门禁全通过。未删除失败记录，也未把失败记录当作最终结果。

## 红线复核

- board.toml SHA256：`967683af4c48528096e46f3bc8402881cd0cfa735fb96b48ea80a222a127c02b`，与修改前逐字节相同；参数仍 1011 B，不刊出完整 bootargs，不追加 touch-mouse 或其他参数。
- 0014 SHA256：`8111a4c0639fb89c117cc10d63eb86584e0c63f015d692923f9389f3305075e9`，逐字节相同。
- `check-v33b-returned.py` 的 RunAtLoad/ready-path 断言 AST 与修改前相同；该脚本只新增返回固件常量和配对检查；`verify-p0-images.py` 全文件未改。
- 无新增 lid/cover-display 路径；只修已有 DP handoff、排空和 feature/exclusion 接口。
- porting.toml 新增 `v33d-review2-local-repairs`，纠正旧结论并记录本地证据；保留此前记录作为历史。

## 后续边界

本轮完成的是用户要求的**本地复审件**。完整原生内核/固件最终链接、CI 返回二进制、APFS/ESP 回读与实体 USB/触控/无线/音视频验证均未执行，不冒充通过。依据本次附件“全部修完并通过本地验证后停下来提交完整 diff + 单测输出等我复审”，当前停在此处，等待复审。
