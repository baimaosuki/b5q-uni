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

<!-- BEGIN batch2 exact memory tables -->

以下区间均为半开区间 `[base,end)`；FDT 声明、静态 UEFI 保留和实时空闲 RAM 分开列示。同源文件不计作独立实机佐证。

**8 GiB DRAM 地址包络（分类，非可分配页证明）**

| 名称/来源 | base | end（不含） | 字节 |
|---|---|---|---:|
| physical_dram_envelopes[0] | `0x80000000` | `0x100000000` | 2147483648 |
| physical_dram_envelopes[1] | `0x880000000` | `0xa00000000` | 6442450944 |

**实机 FDT /memory reg 全部分段**

| 名称/来源 | base | end（不含） | 字节 |
|---|---|---|---:|
| linux_memory_fragments[0] | `0x80000000` | `0x80e00000` | 14680064 |
| linux_memory_fragments[1] | `0x811d0000` | `0xd8000000` | 1457717248 |
| linux_memory_fragments[2] | `0xd8140000` | `0xd8160000` | 131072 |
| linux_memory_fragments[3] | `0xdf7f0000` | `0x100000000` | 545325056 |
| linux_memory_fragments[4] | `0x880000000` | `0x8b9a00000` | 966787072 |
| linux_memory_fragments[5] | `0x8c0000000` | `0xa00000000` | 5368709120 |
| linux_memory_fragments[6] | `0x8b9c00000` | `0x8bba00000` | 31457280 |

**实机 FDT /reserved-memory 全部非零分段**

| 名称/来源 | base | end（不含） | 字节 |
|---|---|---|---:|
| /reserved-memory/kaslr_region | `0xb01ff000` | `0xb0200000` | 4096 |
| /reserved-memory/uh_guest_region | `0xb1000000` | `0xb4000000` | 50331648 |
| /reserved-memory/uh_heap_region | `0xb0200000` | `0xb0240000` | 262144 |
| /reserved-memory/gunyah_hyp_region@80000000 | `0x80000000` | `0x80a00000` | 10485760 |
| /reserved-memory/cpusys_vm_region@80a00000 | `0x80a00000` | `0x80e00000` | 4194304 |
| /reserved-memory/xbl_dt_log_merged@81a00000 | `0x81a00000` | `0x81c60000` | 2490368 |
| /reserved-memory/aop_cmd_db_region@81c60000 | `0x81c60000` | `0x81c80000` | 131072 |
| /reserved-memory/aop_config_merged_region@81c80000 | `0x81c80000` | `0x81cf4000` | 475136 |
| /reserved-memory/chipinfo_region@81cf4000 | `0x81cf4000` | `0x81cf5000` | 4096 |
| /reserved-memory/smem_region@81d00000 | `0x81d00000` | `0x81f00000` | 2097152 |
| /reserved-memory/adsp_mhi_region@81f00000 | `0x81f00000` | `0x81f20000` | 131072 |
| /reserved-memory/global_sync_region@82600000 | `0x82600000` | `0x82700000` | 1048576 |
| /reserved-memory/tz_stat_region@82700000 | `0x82700000` | `0x82800000` | 1048576 |
| /reserved-memory/mpss_region@89800000 | `0x8a800000` | `0x9b000000` | 276824064 |
| /reserved-memory/q6_mpss_dtb_region@9b000000 | `0x9b000000` | `0x9b080000` | 524288 |
| /reserved-memory/ipa_fw_region@9b080000 | `0x9b080000` | `0x9b090000` | 65536 |
| /reserved-memory/ipa_gsi_region@9b090000 | `0x9b090000` | `0x9b09a000` | 40960 |
| /reserved-memory/gpu_micro_code_region@9b09a000 | `0x9b09a000` | `0x9b09c000` | 8192 |
| /reserved-memory/spss_region_region@9b100000 | `0x9b100000` | `0x9b280000` | 1572864 |
| /reserved-memory/spu_tz_shared_mem@9b280000 | `0x9b280000` | `0x9b2e0000` | 393216 |
| /reserved-memory/spu_modem_shared_mem@9b2e0000 | `0x9b2e0000` | `0x9b300000` | 131072 |
| /reserved-memory/camera_region@9b300000 | `0x9b300000` | `0x9bb00000` | 8388608 |
| /reserved-memory/video_region@9bb00000 | `0x9bb00000` | `0x9c200000` | 7340032 |
| /reserved-memory/cvp_region@9c200000 | `0x9c200000` | `0x9c900000` | 7340032 |
| /reserved-memory/cdsp_region@9c900000 | `0x9c900000` | `0x9e900000` | 33554432 |
| /reserved-memory/q6_cdsp_dtb_region@9e900000 | `0x9e900000` | `0x9e980000` | 524288 |
| /reserved-memory/q6_adsp_dtb_region@9e980000 | `0x9e980000` | `0x9ea00000` | 524288 |
| /reserved-memory/adspslpi_region@9ea00000 | `0x9ea00000` | `0xa43b4000` | 94060544 |
| /reserved-memory/mpss_dsm_region@d4d00000 | `0xd4d00000` | `0xd8000000` | 53477376 |
| /reserved-memory/xbl_sc_region@d8100000 | `0xd8100000` | `0xd8140000` | 262144 |
| /reserved-memory/cpucp_fw_region@d8140000 | `0xd8140000` | `0xd8300000` | 1835008 |
| /reserved-memory/qtee_region@d8300000 | `0xd8300000` | `0xd8800000` | 5242880 |
| /reserved-memory/hwfence-shmem | `0xe6440000` | `0xe671d000` | 3002368 |
| /reserved-memory/trust_ui_vm_region@f3800000 | `0xf3800000` | `0xf78ee000` | 68083712 |
| /reserved-memory/trust_ui_vm_dump@0xf78ee000 | `0xf78ee000` | `0xf78ef000` | 4096 |
| /reserved-memory/trust_ui_vm_qrtr@0xf78ef000 | `0xf78ef000` | `0xf78f8000` | 36864 |
| /reserved-memory/trust_ui_vm_vblk0_ring@0xf78f8000 | `0xf78f8000` | `0xf78fc000` | 16384 |
| /reserved-memory/trust_ui_vm_vblk1_ring@0xf78fc000 | `0xf78fc000` | `0xf7900000` | 16384 |
| /reserved-memory/trust_ui_vm_swiotlb@0xf7900000 | `0xf7900000` | `0xf7a00000` | 1048576 |
| /reserved-memory/llcc_lpi_region@ff800000 | `0xff800000` | `0xffe00000` | 6291456 |
| /reserved-memory/splash_region | `0xb8000000` | `0xbab00000` | 45088768 |
| /reserved-memory/sec_xbl_ramdump@A7D00000 | `0xa7d00000` | `0xa8000000` | 3145728 |
| /reserved-memory/sec_debug_region_pool@880100000 | `0x880100000` | `0x8801ff000` | 1044480 |
| /reserved-memory/sec_rst_ex_info_region@8801FF000 | `0x8801ff000` | `0x880200000` | 4096 |
| /reserved-memory/sec_log_buf_region@880200000 | `0x880200000` | `0x880400000` | 2097152 |
| /reserved-memory/sec_debug_bl_region@880400000 | `0x880400000` | `0x880900000` | 5242880 |
| /reserved-memory/sec_pmsg_region@880900000 | `0x880900000` | `0x880b00000` | 2097152 |
| /reserved-memory/google_debug_kinfo_region@880B00000 | `0x880b00000` | `0x880b01000` | 4096 |
| /reserved-memory/sec_qcom_rdx_bootdev_region@880C00000 | `0x880c00000` | `0x88b900000` | 181403648 |
| /reserved-memory/hdm_region@880B01000 | `0x880b01000` | `0x880b02000` | 4096 |

**UEFI MemoryMapLib 静态保留表（含 high reserved0..3）**

| 名称/来源 | base | end（不含） | 字节 |
|---|---|---|---:|
| HYP | `0x80000000` | `0x80a00000` | 10485760 |
| CPUSYS VM | `0x80a00000` | `0x80e00000` | 4194304 |
| XBL DT | `0x81a00000` | `0x81a40000` | 262144 |
| XBL Ramdump | `0x81a40000` | `0x81c00000` | 1835008 |
| AOP | `0x81c00000` | `0x81cf4000` | 999424 |
| Chip Info | `0x81cf4000` | `0x81cf5000` | 4096 |
| SMEM | `0x81d00000` | `0x81f00000` | 2097152 |
| ADSP MHI | `0x81f00000` | `0x81f20000` | 131072 |
| TZ STATS | `0x82700000` | `0x82800000` | 1048576 |
| PIL Reserved | `0x8a800000` | `0xa2a80000` | 405274624 |
| Display Demura | `0xa2a80000` | `0xa5580000` | 45088768 |
| DBI Dump | `0xa6100000` | `0xa7000000` | 15728640 |
| FD Reserved | `0xa7000000` | `0xa7100000` | 1048576 |
| UEFI FD | `0xa7100000` | `0xa7400000` | 3145728 |
| UEFI FD Reserved | `0xa7400000` | `0xa7600000` | 2097152 |
| Info Blk | `0xa7601000` | `0xa7602000` | 4096 |
| MMU PageTables | `0xa7602000` | `0xa7605000` | 12288 |
| Log Buffer | `0xa7605000` | `0xa760d000` | 32768 |
| UEFI Stack | `0xa760d000` | `0xa764d000` | 262144 |
| SEC Heap | `0xa764d000` | `0xa76d9000` | 573440 |
| Sched Heap | `0xa76d9000` | `0xa7ad9000` | 4194304 |
| FV Region | `0xa7ad9000` | `0xa7ed9000` | 4194304 |
| Kernel | `0xa8000000` | `0xb8000000` | 268435456 |
| Display Reserved | `0xb8000000` | `0xbab00000` | 45088768 |
| DXE Heap | `0xbab00000` | `0xc7cc0000` | 219938816 |
| CPUCP FW | `0xd8140000` | `0xd8300000` | 1835008 |
| QTEE | `0xd8300000` | `0xd8800000` | 5242880 |
| TZApps Reserved | `0xd8800000` | `0xdfc00000` | 121634816 |
| b5q high reserved 0 | `0x880100000` | `0x880b02000` | 10493952 |
| b5q high reserved 1 | `0x880c00000` | `0x88b900000` | 181403648 |
| b5q high reserved 2 | `0x8b9a00000` | `0x8b9c00000` | 2097152 |
| b5q high reserved 3 | `0x8bba00000` | `0x8c0000000` | 73400320 |

**静态相减后的候选空闲段（实际 EFI 分配前上界）**

| 名称/来源 | base | end（不含） | 字节 |
|---|---|---|---:|
| candidate_safe_fragments_before_runtime_EFI_allocations[0] | `0x811d0000` | `0x81a00000` | 8585216 |
| candidate_safe_fragments_before_runtime_EFI_allocations[1] | `0x81cf5000` | `0x81d00000` | 45056 |
| candidate_safe_fragments_before_runtime_EFI_allocations[2] | `0x81f20000` | `0x82600000` | 7208960 |
| candidate_safe_fragments_before_runtime_EFI_allocations[3] | `0x82800000` | `0x8a800000` | 134217728 |
| candidate_safe_fragments_before_runtime_EFI_allocations[4] | `0xa5580000` | `0xa6100000` | 12058624 |
| candidate_safe_fragments_before_runtime_EFI_allocations[5] | `0xa7600000` | `0xa7601000` | 4096 |
| candidate_safe_fragments_before_runtime_EFI_allocations[6] | `0xc7cc0000` | `0xd4d00000` | 218365952 |
| candidate_safe_fragments_before_runtime_EFI_allocations[7] | `0xdfc00000` | `0xe6440000` | 109314048 |
| candidate_safe_fragments_before_runtime_EFI_allocations[8] | `0xe671d000` | `0xf3800000` | 219033600 |
| candidate_safe_fragments_before_runtime_EFI_allocations[9] | `0xf7a00000` | `0xff800000` | 132120576 |
| candidate_safe_fragments_before_runtime_EFI_allocations[10] | `0xffe00000` | `0x100000000` | 2097152 |
| candidate_safe_fragments_before_runtime_EFI_allocations[11] | `0x880000000` | `0x880100000` | 1048576 |
| candidate_safe_fragments_before_runtime_EFI_allocations[12] | `0x880b02000` | `0x880c00000` | 1040384 |
| candidate_safe_fragments_before_runtime_EFI_allocations[13] | `0x88b900000` | `0x8b9a00000` | 772800512 |
| candidate_safe_fragments_before_runtime_EFI_allocations[14] | `0x8b9c00000` | `0x8bba00000` | 31457280 |
| candidate_safe_fragments_before_runtime_EFI_allocations[15] | `0x8c0000000` | `0xa00000000` | 5368709120 |

已捕获旧配置 owned=`0x8c0004000+0x100000000`，新配置由 DarwinBoot 实际 EFI 分配器选择 6 GiB span。实际连续安全高段上限5GiB；跨洞 exclusions + low outside adoption 的生产函数模型为6.533126831GiB，不能把它当作实际 max_mem。用户后续明确要求最低4.5GiB硬门槛，代码维持6GiB目标；没有把正常入口改成4.5GiB窗口。

USB/GPU 动态内存：USB retained页表由固件 `EfiReservedMemoryType` 动态分配，排除窗口由真实 EFI descriptor 决定；无最终 live descriptor 时物理地址为 `unknown`。GPU/GMU DMA页由既有分配器动态获取，本地不臆造固定保留段。固件映射对本次loader传入span取值，并按2GiB..64GiB窗口检查；36-bit范围与FDT候选页模型核验通过。

Future `macosdata`：用户明确创建独立分区后，installer使用 `--partition macosdata`，内核对应 `b5q-data-partition=macosdata`；APFS镜像必须先按该分区的精确块数扩容。当前交付默认仅为已授权尾区。13个实际Python/C++生产函数配对用例已核对两种模式、显式选择优先、UUID别名、名称重复、root/ESP重叠、元数据/容量越界、envelope和FUA/LBA边界；不执行分区或设备操作。

<!-- END batch2 exact memory tables -->

## 2. 精确改动清单

以下源文件均位于 /home/baimao/zflip5/；最终完整输入哈希见 /home/baimao/zflip5/UniXNU-b5q/reports/batch2-validation.json。

- /home/baimao/zflip5/UniXNU-b5q/board.toml：6GiB owned span、128 exclusions、16 outside slots、显式保留洞、persistent Data/PSCI；保留 SIP2、输入调度参数及两条 BGRA fixup。
- /home/baimao/zflip5/UniXNU-b5q/package/B5qRamStorage.cpp:50：最低 usable 改4.5GiB，6GiB只是目标；打印实际 max_mem/adopted/refused；持久入口拒绝意外 RAM seed。
- /home/baimao/zflip5/UniXNU-b5q/package/B5qUfs/B5qDataFormat.h:58、B5qDataBlock.h:12：独立tag1/UCD/DMA，队列共享互斥，溢出安全LBA窗口，WRITE10 FUA、SYNC10；root/logger继续tag0。
- /home/baimao/zflip5/UniXNU-b5q/package/B5qUfs/B5qDataBlock.h:78：无 dataClosing 提前拒写；晚到写仍FUA并使旧flush标志失效；driver shutdown停journal并最终SYNC。
- /home/baimao/zflip5/UniXNU-b5q/package/B5qPower.cpp:18：仅正常最终关机且flush成功才PSCI；panic通知不做块I/O；平台hook的PAC IA0ba5匹配真实core调用者。
- /home/baimao/zflip5/UniXNU-b5q/package/B5qUfs/B5qUfs.cpp、B5qLogUfs.h：Data绑定/启动、停journal；UFS仅复用固件映射，无EL1 apps_smmu路径。B5qVmAlloc.h保留原root-hash分配的精确XNU ABI。
- /home/baimao/zflip5/UniXNU-b5q/package/B5qMouseReport.h、B5qTouchPointer.h、NativeHidInput.cpp、HidInputProbe.cpp：relative mouse避免digitizer属性覆写、刷新event driver、上报计数，单击/双击拖拽/按住/双指右击与XY滚动，恢复/抬指释放。
- /home/baimao/zflip5/UniXNU-b5q/package/B5qProcTop.c、B5qProcTopFormat.h：30秒TOP10分行，每行<200B，固定内存不加堆锁。
- /home/baimao/zflip5/UniXNU-b5q/scripts/relink-b5q-peripherals.py、b5q_peripherals.py、build-b5q-storage.py：六对象增量recipe及storage late ctor；无核心源码变化。
- /home/baimao/zflip5/UniXNU-b5q/scripts/package-batch2-esp.py：正常无initrd；原4GiB RAM独立ADT/菜单；v30 loader原字节。回退路径需要同内核副本来选择不同 .adt，这是实际loader接口要求。
- /home/baimao/zflip5/scripts/b5q-install/build-persistent-data.py、b5q_data_format.py、install-data-ufs.py：扩容既有seed、绑定UUID、ownership/remount、GPT/CRC/guard/首装锁与全盘回读后最后commit envelope。
- /home/baimao/zflip5/scripts/b5q-install/install-firstboot.py：持久包仅允许ESP/check，拒绝root/boot/repair/all。
- /home/baimao/zflip5/.github/workflows/b5q-new-batch2.yml、reuse-batch2-native.py：原生编译缓存、失败保留产物、普通Actions artifact；无加密回传。
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

- python3 scripts/b5q-install/pre-ci-batch2.py：23组PASS（原22组+13个双模式GPT配对用例）。
- test-data-queue.py：实际生产dataIo、8000并发队列迭代、6000Data提交；范围/方向/timeout/OCS/tag/SCSI/late-write/flush拒绝路径；ASan/UBSan。
- test-data-installer.py：Python/C++ envelope互认、GPT CRC/identity/guard；真实installer.main的check-only、write顺序与14类拒绝/失败，回读失败不commit。
- test-data-partition.py：13个Python/C++生产GPT配对用例通过，覆盖未来独立macosdata与当前尾区；ASan/UBSan。
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

完成审计补充：新检查只增加测试和文档；没有修改CI45108577992的二进制输入或重建镜像。最终实际ADTu64 darwinboot-memory-size正常=0x180000000、回退=0x100000000，原镜像SHA再次核验一致。
