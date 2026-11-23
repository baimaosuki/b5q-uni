# New Batch 2 交付报告（已封板）

## 0. 完成度锁表

本报告只对应 New Batch 2。真实手机的内存可用量、持久化重启和触控行为必须依据后续 XNU2LOG 验收；本地完成度不冒充实机成功。

| 要求 | 状态 | 证据 |
|---|---|---|
| Req-1 内存/保留洞/只读根/Data 尾区取证 | DONE | batch2-inputs.json、batch2-validation.json |
| Req-2 独立 tag/DMA 的持久 Data 与干净关机 | DONE | B5qDataBlock.h、B5qDataFormat.h、B5qPower.cpp；8000 并发迭代 |
| Req-3 默认取消 RAM Data、分段扩内存、保留 RAM 回退 | DONE | package-batch2-esp.py、最终两套 ADT 回读 |
| Req-4 右键/XY 滚轮/HID/ProcTop/linkd | DONE | mouse descriptor、gesture ASan/UBSan、分行统计、linkd 原 plist |
| Req-5 主机/目标/PAC/最终镜像全部验证 | DONE | 22 组 pre-ci、返回 Xcode 对象、images.json |
| Req-6 安全首次灌入工具、记录与交付 | DONE | install-data-ufs.py；真实 main 14 个拒绝/失败测试 |

## 1. 实证取证表

| 来源 | 精确位置/内容 | SHA256/结果 |
|---|---|---|
| 实机 FDT | batch2-inputs.json 逐项 memory/reserved tuples | 74aaf1524d9aca9b8e01c1854fbfcdaf6060f189f3f37db00196d866e3d57be6 |
| 已安装 SHNGROOT v2 | 只读根镜像首 4096B；total=17603493888B；末 LBA=53990390 | d93a00b589d64b7e0757aa40288aaa927a5364382ec5a0dd08faa3629d9a7d8b |
| XNU kern_shutdown.c | 223/266 通知；286/301 两次 vfs_unmountall；355 host_reboot | da2bd5c24e0729eca4663870ed0af4c5ff048961011c2aadecf5e1d44f827127 |
| IOPMrootDomain.cpp | 1053 ProcessExit->PagingOff；6123 非 PagingOff 才 notifySystemShutdown；10705 调真实 driver override | f4db151b8a4c67a79e845d9df02018e62f608486ab4dfbe52eb18d8fe1c8c7a0 |
| IOPlatformExpert.cpp | 998..1110，driver shutdown 后才平台 haltRestart | 2dff047ecfb18cdedcdc6f9f97c8fa6f730e088176598865c586b91545f74a56 |
| DarwinBoot.c | 813 CommandLine[1024]；844..850 拒绝 >=1024B 或非 ASCII；不是静默截断 | 1d19ca1091962bd48b4154e3aae3d0ad80699f6c892a5a407dd3de0d62907fd9 |
| XNU arm64/boot.h | BOOT_LINE_LENGTH=1024；官方 payload.check_args 工程门槛=1000 | 当前 981 ASCII B，通过 1000/1001、1023/1024 边界测试 |
| v33 linkd | XNU2LOG.txt:2037..2061；PID401；com.apple.linkd.plist；IOUserClient.cpp:4563 | MACF 拒绝 KeyStore 打开返回 NotPermitted；不是内核 panic/重拉证据。不放开 MACF、不修改既有59/26策略 |

尾区绝对 LBA=54411255..62275574，前 256 块（1MiB）为不可变 envelope，APFS=54411511..62275574，7864064 块。只读根之后实际 guard=1723858944B，大于256MiB。GPT、只读根、ESP/FAT 与受保护分区均不进入 Data 写允许区。

## 2. 精确改动清单

以下路径均以 /home/baimao/zflip5/ 为根；最终完整输入哈希见 batch2-validation.json。

- UniXNU-b5q/board.toml：6GiB owned span、128 exclusions、16 outside slots、显式保留洞、persistent Data/PSCI；保留 SIP2、输入调度参数及两条 BGRA fixup。
- UniXNU-b5q/package/B5qRamStorage.cpp:50：最低 usable 改4.5GiB，6GiB只是目标；打印实际 max_mem/adopted/refused；持久入口拒绝意外 RAM seed。
- UniXNU-b5q/package/B5qUfs/B5qDataFormat.h:58、B5qDataBlock.h:12：独立tag1/UCD/DMA，队列共享互斥，溢出安全LBA窗口，WRITE10 FUA、SYNC10；root/logger继续tag0。
- UniXNU-b5q/package/B5qUfs/B5qDataBlock.h:78：无 dataClosing 提前拒写；晚到写仍FUA并使旧flush标志失效；driver shutdown停journal并最终SYNC。
- UniXNU-b5q/package/B5qPower.cpp:18：仅正常最终关机且flush成功才PSCI；panic通知不做块I/O；平台hook的PAC IA0ba5匹配真实core调用者。
- UniXNU-b5q/package/B5qUfs/B5qUfs.cpp、B5qLogUfs.h：Data绑定/启动、停journal；UFS仅复用固件映射，无EL1 apps_smmu路径。B5qVmAlloc.h保留原root-hash分配的精确XNU ABI。
- UniXNU-b5q/package/B5qMouseReport.h、B5qTouchPointer.h、NativeHidInput.cpp、HidInputProbe.cpp：relative mouse避免digitizer属性覆写、刷新event driver、上报计数，单击/双击拖拽/按住/双指右击与XY滚动，恢复/抬指释放。
- UniXNU-b5q/package/B5qProcTop.c、B5qProcTopFormat.h：30秒TOP10分行，每行<200B，固定内存不加堆锁。
- UniXNU-b5q/scripts/relink-b5q-peripherals.py、b5q_peripherals.py、build-b5q-storage.py：六对象增量recipe及storage late ctor；无核心源码变化。
- UniXNU-b5q/scripts/package-batch2-esp.py：正常无initrd；原4GiB RAM独立ADT/菜单；v30 loader原字节。回退路径需要同内核副本来选择不同 .adt，这是实际loader接口要求。
- scripts/b5q-install/build-persistent-data.py、b5q_data_format.py、install-data-ufs.py：扩容既有seed、绑定UUID、ownership/remount、GPT/CRC/guard/首装锁与全盘回读后最后commit envelope。
- scripts/b5q-install/install-firstboot.py：持久包仅允许ESP/check，拒绝root/boot/repair/all。
- .github/workflows/b5q-new-batch2.yml、reuse-batch2-native.py：原生编译缓存、失败保留产物、普通Actions artifact；无加密回传。
- 配套tests/check/pre-ci/verifier与UniXNU-b5q/porting.toml、reports：同批闭环。白名单外固件/DTS/核心/GPU源码未更改；主工作区原有无关改动保留。

## 3. 未改组件与缓存复用

| 输入 | SHA256 |
|---|---|
| v24 core archive | 88703fdc7eb18011294b5fe634d23b085496732f1e8bd4dd04e47f82dbe6ec2b |
| GPU addon | b68e1164f7dd0ff822f20e116e97adc4606926a4204fc25eaa5241c2a966d82d |
| Batch1-final 4GiB seed | d2e32a5f7dd37807a816d857d8b62eba41615c5da9ac335c2322e3c7a35ffc70 |
| v30 UEFI FD | df26529ae53be872b6c3856ab1f4fadb3c994fca8a8199c219112438783ea983 |
| v30 DarwinBoot | 100080919035179c86c1f4b1eee16e6a8a46166beee95234dc2c842995009cde |

六个板级对象在CI45105913288完成；最终CI45108577992匹配全部源码/recipe/archive/prelink SHA后复用，新增编译0。core/GPU/Mesa/UEFI始终未重编。Data是同UUID/同账户/同策略卷扩容，并非重新生成账户或4GiB seed。

## 4. 本地硬验证

- python3 scripts/b5q-install/pre-ci-batch2.py：22组PASS。
- test-data-queue.py：实际生产dataIo、8000并发队列迭代、6000Data提交；范围/方向/timeout/OCS/tag/SCSI/late-write/flush拒绝路径；ASan/UBSan。
- test-data-installer.py：Python/C++ envelope互认、GPT CRC/identity/guard；真实installer.main的check-only、write顺序与14类拒绝/失败，回读失败不commit。
- test-data-grow.py：7类真实helper挂载/ownership/UUID/path正反回归。
- test-pointer-batch2.cpp：73字节descriptor、8字节report、边缘/单击/双击拖拽/长按/双指右击/XY滚动/partial lift/recovery/极值；ProcTop每行<200B。test-proctop.cpp含160000并发事件。
- 真实macOS27.3 launchd 89指令用例、真实libxpc3事务用例、absentd21生产ASan/UBSan用例继续PASS。
- 6个arm64e对象符号闭包，无未定义/重复定义；最终prelink missing={}、stubbed={}、allow_missing=false。
- 实际返回Xcode .o：326storage虚表槽、completion IAe90c、platform IA0ba5、fork/exit/startup/thread PAC，USB/GMU/clock/buttons/HID/Thermal全跨对象检查PASS。
- 每个修改.o用objdump与指令立即数追踪复核，apps_smmu地址物化/旧allocator符号=0；最终返回对象与已验证对象逐字节相同。
- 无QEMU；POST仅运行已有短leaf Unicorn回归，并独立重算HMAC及69个static-if点。

## 5. CI与最终回读

[CI45108577992](https://github.com/baimaosuki/b5q-uni/actions/runs/45108577992) SUCCESS；提交e66beea40e2a887e177c762804206d21ba983ef2。

| 最终文件 | 字节数 | SHA256 |
|---|---:|---|
| /home/baimao/zflip5/artifacts/b5q-esp-new-batch2/esp.img | 838860800 | c97e09e6993f3df6ccccc075db69adc5154ecf8c1593bee2aed82a78284f3047 |
| /home/baimao/zflip5/artifacts/b5q-esp-new-batch2/data-ufs.img | 32211206144 | 0af5262d519d0dd8a4a86da7cc5e4c0b10470b51a272591b0d8b52e6df34da96 |

默认ADT没有RAMDisk/PackedRAMDisk、没有initrd；回退独立ADT带4GiB seed。两条BGRA、8个E/P、981B参数、u64 lp-sip0=0200000000000000均从最终ESP读取。Data volume UUID=1552CFEE-78FF-48D8-8A6C-694B867D61AC；两份plist均bplist00、uid/gid=0、mode=0100644、59/26全true；marker为0B root0644。账户/密码/自动登录/absentd签名+trust已回读验证。

普通artifact传输ZIP SHA256=43bfbfb4e143c365fe8159604ba81f0cf8372cec5b8e618b1bc700c205bc2e99，ZIP CRC与最终IMG SHA均通过。Data以sparse保留，本地两个IMG实际占盘约393MiB；交付逻辑大小保持原样。
完整报告为 artifacts/b5q-batch2-work/final-verification/images.json，所有实际binary plist内容在disabled-plists-readback.json。

## 6. 首装与以后更新

首次进入TWRP后，在Linux电脑运行（脚本会先验证机型、LUN0、GPT/CRC、只读根hash、Data空窗口及镜像SHA；任何不符停止）：

```bash
python3 /home/baimao/zflip5/scripts/b5q-install/install-data-ufs.py --image /home/baimao/zflip5/artifacts/b5q-esp-new-batch2/data-ufs.img --apply
python3 /home/baimao/zflip5/scripts/b5q-install/install-firstboot.py --directory /home/baimao/zflip5/artifacts/b5q-esp-new-batch2 --esp
```

去掉第一行的`--apply`只检查不写。已初始化Data必拒绝重灌；以后只运行第二行`--esp`，不要使用`--repair/--root/--all`。此次不刷boot，不替换只读根，不更改GPT。未连接、未访问、未刷写手机。

## 7. 实机验收对照

| 日志/动作 | 成功阈值 | 失败判据 |
|---|---|---|
| B5qMemory physical-bytes / adopted / refused | actual>=4831838208；目标>=6442450944但不伪造实际 | <4.5GiB受保护停止；记录refused |
| 正常入口memory-map | 无PackedRAMDisk/RAMDisk | 正常入口误载4GiB seed |
| B5qData window/tag/FUA | window=54411511..62275574、blocks=7864064、tag1、FUA1 | identity/CRC/GPT/range拒绝、poison |
| 保存文件/密码后苹果菜单重启 | 文件与设置保留；flush=0、data-flush=1后PSCI | 任何flush错误/PSCI返回；不得强称干净关机 |
| RAM回退菜单 | 原4GiB volatile Data可选；data-ufs0 | 正常入口默默回退或覆盖持久Data |
| HID | 无mouse被改TouchScreen；hid第3计数递增；单击/双击拖拽、双指右键与XY滚轮 | 粘键、无release、driver反复重建 |
| ProcTop/Batch1 | 每30秒TOP1..TOP10+overflow完整；absentd零重拉 | 截断/PID持续风暴 |

静态内存模型上限6.5331268GiB，真实UEFI占用和XPU refused会降低它；本地验证不承诺真机必有6GiB。持久化、PSCI和手势物理结果仍以新日志/实际操作验收。

封板证据：/home/baimao/zflip5/UniXNU-b5q/reports/batch2-validation.json；实际完整plist内容：/home/baimao/zflip5/artifacts/b5q-batch2-work/final-verification/disabled-plists-readback.json。首轮缺头文件和后续原生APFS挂载/ownership首错均保留；最终交付只取成功CI45108577992的真实产物。
