# New Batch2 持久Data挂载修复

## 0. 100%完成度锁表

DONE仅指本轮全部实现、本地验证、真实CI与最终镜像回读完成；本次未刷机，不把它们冒称新镜像实机启动通过。

| 用户编号要求 | 状态 | 实证 |
|---|---|---|
| Req-1 修复native_ram_block_volume_seed/selectVolumeSeed与B5qDataBlock对接，base0/bytes180997812224/确定性digest，保留RAM回退 | DONE | b5q-storage-provider.patch；typed hook native_ram_block_provider_seed；B5qData::seed；21生产体用例 |
| Req-2 load_init_program前唯一UUID+BSDName就绪，同步等待、防重复匹配 | DONE | b5qDataWaitReady在publish线程最前；UUID/名称/major/minor/typed祖先链全通过才允许根盘发布；延迟/缺属性/重复卷用例 |
| Req-3 专项ASan/UBSan正反单测、跨对象PAC、零apps_smmu | DONE | 21生产selector/hook/wait用例；实际返回2对象与原5对象；IA0xbd41/directBR26、326RAM/Data槽、IAe90c/IA0ba5全部PASS |
| Req-4 仅增量存储对象、复用全部缓存、单张ESP与--esp命令、0～7报告 | DONE | CI45127313070SUCCESS；只有2存储archive成员变化；实际ESP回读PASS；本报告与package.manifest.json |

## 1. 实证取证表

输入日志 `/home/baimao/zflip5/logs/b5q-xnu2log-batch2/XNU2LOG.txt` SHA256 `a4fe97b42b23971720526d22c30240f0ef7c056203ba79850d409f6dbfb47089`：L58领养205811pages/0refused；L149实际RAM7014903808B（约6.533GiB）；L161注册44188919块持久Data；L167～170 APFS发现disk0/xid23；L255在launchd前`offline scratch Data mount failed: 2 @kern_exec.c:9901`，后续spawns0。

源码 `/home/baimao/zflip5/UniXNU/patches/xnu-12377/offline-owner-systemos-mount.patch:204` 调用native_ram_block_volume_seed；`/home/baimao/zflip5/UniXNU/drivers/RamBlock/NativeRamBlock.cpp:668`只接受NativeRamBlock。该原文件SHA256`772d47a069c50c9bf92f6c9292668340e005a61d996651033d9af2b6474b897c`保持不变。板级生成副本追加最小provider补丁，不修改osfmk/bsd或任何XNU core补丁。

## 2. 精确改动清单

- `/home/baimao/zflip5/UniXNU-b5q/scripts/b5q-storage-provider.patch`：selectVolumeSeed保留原RAM分支，非RAM祖先经弱typedproviderhook核验；base必须0、size正值/4Kn对齐/≤1TiB。
- `/home/baimao/zflip5/UniXNU-b5q/package/B5qUfs/B5qDataSeed.h`：精确DataUUID、volume.valid、online、容量、非零摘要校验，输出base0、bytes=dataVolume.blocks*4096与确定性摘要。
- `/home/baimao/zflip5/UniXNU-b5q/package/B5qUfs/B5qDataBlock.h`：提供hook、校验envelope后计算SHA256；摘要只标识不可变B5QDATA1封装，不宣称是可写Data全盘内容摘要。media-ready等待打印/dev/diskXsY和容量。
- `/home/baimao/zflip5/UniXNU-b5q/package/B5qUfs/B5qUfs.cpp`：根盘publisher线程在任何root发布前等Data就绪；最多1200次×50ms，重复/缺属性/无typedprovider则不放行。等待在单独发布线程内，避免阻塞原APFS加载线程。
- `/home/baimao/zflip5/UniXNU-b5q/scripts/b5q_ramblock.py`、`build-b5q-storage.py`、`b5q_peripherals.py`、`relink-b5q-peripherals.py`：完整与增量构建使用同一生成源补丁；新增data-mount双对象recipe/late转换。
- `/home/baimao/zflip5/tests/b5q-ufs/test-data-volume-seed.py`：编译实际production selector/hook/wait与真实seed-policy；IOKit注册表/时钟为主机替身，明确不声称真实IOKit执行。
- `/home/baimao/zflip5/scripts/b5q-install/check-peripheral-target.py`、`check-data-provider-objects.py`、`verify-data-mount-esp.py`及`retain-data-mount-ADT.py`：目标编译、返回对象和最终ESP验证。工作流`.github/workflows/b5q-data-mount-fix.yml`复用旧cache，仅编两对象；旧userdata工作流保留manual但取消重复push触发。
- `/home/baimao/zflip5/UniXNU-b5q/porting.toml`与`reports/data-mount-fix.json`同步findings/evidence。未修改board.toml、DTS、core/GPU/UEFI；工作区其他既有修改未混入本修复。

## 3. 未改组件与缓存复用

core archive SHA256 `88703fdc7eb18011294b5fe634d23b085496732f1e8bd4dd04e47f82dbe6ec2b`；GPUaddon `b68e1164f7dd0ff822f20e116e97adc4606926a4204fc25eaa5241c2a966d82d`；v30DarwinBoot `100080919035179c86c1f4b1eee16e6a8a46166beee95234dc2c842995009cde`；UEFIFD基线 `df26529ae53be872b6c3856ab1f4fadb3c994fca8a8199c219112438783ea983`未构建/未刷。

原4GiBRAM恢复seed `d2e32a5f7dd37807a816d857d8b62eba41615c5da9ac335c2322e3c7a35ffc70`保留；userdata168.57GiB持久Data完全不访问、不初始化，其首装来源SHA `d343babb7ca905c957c1b2643ae3cb92f844dd9c2cfd47bb911ef17f98edca0a`只是历史输入记录，不冒称运行后全盘仍等于初始镜像。

从CI45115332412精确cache复用；libNativeLegacyDisplay/libQcomDwc3无变化，libRamBlock仅`NativeRamBlock.late.o`及`B5qUfs.late.o`变化。未重编XNUcore/GPU/Mesa/UEFI，未运行QEMU或新生成Data。

## 4. 本地硬验证

`python3 tests/b5q-ufs/test-data-volume-seed.py`：21实际production体ASan/UBSan用例PASS。覆盖无RAMprovider持久卷、错误UUID/不在线/无效volume/UUID不符/零或超限容量/零摘要/缺BSD名或minor/越界设备号/空名/短输出/重复UUID/非typed祖先/RAM恢复/延迟就绪/超时。

`check-peripheral-target.py --sources NativeRamBlock.cpp,B5qUfs.cpp`：2个arm64e目标对象、缺失符号0、重复定义0。原Data生产队列8000并发迭代、19Python/C++GPT选择/边界用例、4GiBRAM恢复与981B参数/关机顺序回归PASS。

对CI实际返回对象执行`check-data-provider-objects.py`与`check-batch2-objects.py`：弱导入存在性PAC IA0xbd41，新hook/selector交叉调用为BRANCH26直接调用；RAM/Data继承326个虚表槽PAC一致；completion IAe90c与平台PSCI IA0ba5一致；7对象objdump/指令扫描零apps_smmu。新provider helper为非virtual，不增加/改变虚表。

## 5. CI产物与本地回读校验

CI [45127313070](https://github.com/baimaosuki/b5q-uni/actions/runs/45127313070) **SUCCESS**，源码`05eeb6e4599d0170322853f97f0a2e71baf92bb2`。普通GitHubartifact SHA256验证后解包；单张部署镜像：

`/home/baimao/zflip5/artifacts/b5q-esp-data-mount-fix/esp.img`

大小 **838860800B（800MiB）**；SHA256 **`5dffcb16774b4b25746676835b61977d1e2fa8d305fbe5deb13b925be2c42ed0`**。

CI生成ADT有正常构建熵变化；本地`retain-data-mount-ADT.py`先证明仅`/chosen/random-seed`与构建标识变化，再恢复上一ESP的两份完整ADT，不重编。最终FAT成员只有正常/RAM入口kernel和配套HMAC JSON改变，其余成员逐字节相同。

实际回读：FAT32 4096B扇区/1簇、双FAT/连续2051簇日志区/全成员PASS；981B参数、lp-sip0=`0200000000000000`（u64=2）、两条fixup、正常6GiB/恢复4GiBADT、默认无RAMData/独立RAM恢复PASS；新hook和volume选择符号均存在，旧核心`_sheng_cpu_idle_mach`保留；69个POST签名点/HMAC独立校验PASS；原恢复APFS账户、自动登录、root:wheel0644二进制59/26策略与absentdSHA通过。永久Data未读取或写入。

完整机器结果：`/home/baimao/zflip5/artifacts/b5q-data-mount-fix-work/final-verification/images.json`；`returned-provider-PAC.json`；`returned-PAC-zero-smmu.json`。

## 6. 本次刷写命令

设备已进入TWRP后，只更新ESP：

```bash
python3 /home/baimao/zflip5/scripts/b5q-install/install-firstboot.py \
  --directory /home/baimao/zflip5/artifacts/b5q-esp-data-mount-fix --esp
```

此清单仅包含esp.img，安装器拒绝--root/--boot/--all/--repair。**不要再格式化或初始化userdata**，不刷boot/macosroot。本轮按交付要求仅给出命令，未连接手机或执行刷写。

## 7. 实机XNU2LOG验收对照表

| 观察项 | 成功结果 | 失败判据 |
|---|---|---|
| Data准备 | 原`B5qData: mode=3 ... blocks=44188919`之后出现`B5qData: media-ready path=/dev/diskXsY bytes=180997812224 retry=N unique=1` | `media/UUID/BSD readiness timeout or duplicate UUID`；不要依赖固定disk编号 |
| Data挂载 | 原L255 ENOENT消失，APFS成功挂载对应Data卷、launchd进入用户态 | 重复UUID/错误容量/挂载失败 |
| 系统进度 | ProcTop spawns>0，WindowServer/loginwindow与桌面继续运行 | 永久spawns0或启动任务回归 |
| 持久盘 | 原文件保留，正常启动无需初始化 | 数据丢失、I/O rejected；请保留原日志 |
| 其他Batch2 | 205811adopted/0refused及6.533GiBRAM基线、PSCI、HID相对鼠标与分行ProcTop保持 | 回退到RAMData或相关功能回归 |

这些是新镜像的实机验收条件，尚未宣称已在设备上通过；本轮本地可做的Req1～4全部完成。
