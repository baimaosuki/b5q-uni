# v33d 两份日志：四项定点修复本地复审

状态：**LOCAL_REVIEW_READY / HOST_VERIFIED_PENDING_HARDWARE**。四项本地修改及完整门禁已通过；本轮未提交、未推送、未触发CI、未生成ESP或新部署FD、未操作手机。

## 审查入口

- `artifacts/b5q-v33d-review4/complete.diff`：相对本轮修改前快照的完整增量diff，含必要新增单测与记录。
- `artifacts/b5q-v33d-review4/full-test-output.txt`：完整stdout/stderr，包括首次失败及最终通过日志；最终凭据为`pre-ci-final.log`/`v33d-local-gates.json`。
- `artifacts/b5q-v33d-review4/SHA256SUMS`：源码、报告与证据SHA。
- 本报告同名JSON：输入身份、逐文件SHA、每项要求到测试的映射、编译/PAC与零漂移凭据。
- 复现：`B5Q_GATE_WORK=artifacts/b5q-v33d-review4 python3 scripts/b5q-install/pre-ci-v33d.py`。

## 实机证据与修改表

两份BIN已独立重验配置和槽位CRC，最新有效payload与提供的TXT逐字节相同。第一份seq104、1518行，第二份seq370、2025行；二者lost/ring-overwrite均为0。只提取必要外设诊断，不发布bootargs或设备身份。

| 要求 | 本地状态 | 修改 | 验证 |
|---|---|---|---|
| Fix-1 | LOCAL_DONE | CMD02接受01或10且payload长>1、mode==1；worker发命令前最多排空8个ATTN包；保留其他命令协议逻辑。 | 真实生产command与worker片段覆盖10/mode1/24B成功、10/mode2失败、01/mode1成功、短包拒绝；8包上限及packet失败有界。 |
| Fix-2 | LOCAL_DONE | openMaxim等待600×10ms、失败state回0；ensureMaximReady成功快返，失败1秒节流、busstate2立即重试；cable/OTG调用helper恢复。 | 生产helper+并发Busowner：1.2秒完成等待成功；6秒超时后late completion，cable与OTG均恢复；failed-open清理、1秒节流及重试；原16线程共享SE8与快照一致性回归保留。 |
| Fix-3 | LOCAL_DONE | DiscoverModes31字节read/event32；新增modePosition、modesRequested，reset通过默认成员值复位；非FF01只请求一次FF01并等待；遍历所有ModeVDO，所选position贯穿Enter/Configure；失败打印前16reply字节。 | 196个PDIC案例+100000随机输入，2个ModeVDO且仅第2个可用；vendor SVID重复只query一次；modePosition2 Enter/Configure完整走通，错误position拒绝；20个board poll案例覆盖真实event长度与多SVID/多Mode串联。 |
| Fix-4 | LOCAL_DONE | 映射BootServicesCode/Data与owned外普通LoaderCode/Data；保持aperture/no-map/self/OwnsHead/Retained约束与静态map；USBpool256→2048pages并编译期证明上界；恢复core-onlyreset，不写PHYbit31；首16次w64日志和限定allzero/nonCRCR lo-hi补试，签名与PAC不变。 | 原b5q边界衍生模型26表页；819极碎片描述符1642页，保守上界1742<2048；旧256耗尽安全失败、staticmap溢出拒绝、两项handoff门禁保持；真实目标UsbDma无AllocatePool/FreePool；slot421@d28签名/PAC及427槽认证相同；因果寄存器模型验证两种锁存顺序、>4GiB地址与CRCR排除。 |

## USB页表容量与故障结论边界

USB aperture仍是2GiB..64GiB，静态map仍32768B，不使用AllocatePool/FreePool。普通Loader内存不再被裁成仅owned窗口；BootServicesCode/Data加入同一Normal WB-IS映射。runtime、MMIO、独立DMA保留池、19个原b5q保留区和页表自身继续拒绝映射，`OwnsHead && Retained`仍为成功条件。

819个40B描述符能放入静态map。每段最多两处不齐2MiB的L3边界，加上19个保留区的两端及最多64个L2与两个根页，保守上界为`66 + 2*(819+19) = 1742`页。生产算法的819描述符对抗用例实际占1642页，已超过旧256页。因此仅USB页表池改为2048页/8MiB，并以STATIC_ASSERT固定该上界；其余SMMU参数和0014补丁完全不变。正常b5q范围衍生模型占26页。新测试证明旧容量安全失败、容量用尽无越界、map大于32KiB拒绝以及两个handoff门禁不被绕过。模型使用的原始范围有来源SHA，**没有把模型称为实机最终EFI内存图**。

`sts=0x15`的bit2是HSE，bit3 EINT未置位。当前DarwinBoot的MemoryWindow.h实际上仍排除BootServices页，本轮没有改loader回收策略；所以“这些页被XNU回收导致这次HSE”不能直接记成已证实。本轮严格实现要求的映射扩展、core-onlyreset与寄存器写回诊断，具体DMA故障地址和修后实体枚举仍待后续获批实机日志。

## 编译与门禁

- 最终总门禁 **24项全部PASS**，含源码哈希绑定的保留P0–P4基线、v33b门禁和新增测试；嵌套数量不重复相加。
- 触控、MAXIM并发恢复、PDIC、core-onlyreset、xHCI物理锁存模型和USB页表生产函数测试启用ASan/UBSan。PDIC原NAK/时序/截断/HPD/10万fuzz断言保留，只按新协议修正旧Identify/BootServices断言。
- 通用arm64e目标12对象通过；B5qUsbBoard及DP对象由原无线/媒体/DP目标门禁编译。7个EDK2对象编译通过，16份补丁git apply后与live树diff -ruN返回0。
- 新UsbDma.obj SHA、静态缓冲、无AllocatePool/FreePool及0014常量由真实COFF检查；不是只看源码。
- XHCI_WRITE64实际arm64e对象位于槽421/0xd28，原签名对应符号`opaque421_250860EPvjy`与认证元数据`0x80016089`不变，427槽PAC认证字段均与已交付对象一致。USB/GMU/扩展跨对象PAC及timer/workloop PAC继续通过。
- 31个板级对象及无线/ADSP联合对象零EL1 apps_smmu检查继续通过；只编译审计对象，没有最终部署内核/固件链接。

## 首次失败与范围复核

保留两项新测试夹具首错：MAXIM测试占位符替换误及日志字符串，已限定整行替换；DMA模型额外测试区间与已有范围重叠，生产函数正确拒绝，改用不重叠区间后全部通过。这些是测试夹具错误，未修改生产断言以掩盖失败。首次日志和最终输出均在新审查目录。

除四个指定板级文件、USB页表容量头及0015对应补丁，只调整直接相关单测、总门禁接入和porting记录。所有其余已快照源码逐文件SHA相同。Wi-Fi/BT/GPU/ADSP、board.toml、启动参数、0014文件、原Wi-Fi断言两份脚本、工作流和用户五个TWRP文件均未改。board参数仍1011B，不刊出完整参数。

完成`porting.toml`对应area的findings/evidence更新；完整diff在临时Git树执行apply --check、实际apply和逐文件字节核验。按附件“修完跑完完整本地门禁后停在本地等待复审”，本轮停在此处。
