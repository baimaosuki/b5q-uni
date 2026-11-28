# macOS-only userdata 最小改动交付

## 0. 本次100%完成度锁表

以下DONE指实现、本地验证、真实CI及最终镜像回读完成；不把它们冒称实机验证。

| 当前要求 | 状态 | 实证 |
|---|---|---|
| 最小工作量：原userdata改用持久Data，不保留Android内容 | DONE | 精确LBA3406336..47595510、mode3身份封装、b5q-data-ufs=2；19组生产Python/C++对照 |
| 不重分区、不移动或重刷macosroot/boot | DONE | 全37项GPT保留、0GPT写命令；原48GiB系统根保留 |
| 保留NewBatch2内存/关机/右键滚轮/分行ProcTop及Batch1策略 | DONE | 原归档逐成员核对，仅2存储对象变化；6GiB目标/4.5GiB底线、PSCI/FUA、SIP2/59+26/absentd |
| 增量构建、PAC、零apps_smmu | DONE | CI 45115332412 SUCCESS；326虚表槽、completion IAe90c/PSCI IA0ba5；返回Xcode对象核验 |
| 最终ESP/APFS本地回读和首装工具 | DONE | images.json passed；24CLI+14旧路径用例、raw/gzip生产代码流传输回归；只提交唯一2个IMG |

## 1. 实证取证表

来源为2026-11-19用户GPT listing，不是本轮重新采集；磁盘/分区GUID由安装器核验实际GPT后绑定，当前unknown。原始listing SHA256 `f03c7b4e6349ac7d7d1a92c387fccb9566c940af0efd407a21821d346489a644`；只读根header SHA256 `d93a00b589d64b7e0757aa40288aaa927a5364382ec5a0dd08faa3629d9a7d8b`。本轮无硬件寄存器、launchd、USB协议更改，不新增推测性数值。

| 项目 | LBA，4096B单位、含首尾 | 容量/动作 |
|---|---|---|
| boot #21 |152448..177023|96MiB，保留v30|
| ESP #29 |3162880..3367679|800MiB FAT32 4Kn，更新|
| userdata #36 |3406336..47595510|168.568325GiB，覆盖旧Android内容|
| 空隙 |47595511..49692662|8GiB，保留|
| macosroot #37 |49692663..62275574|48GiB，保留现有已签名只读系统|

userdata前1MiB为B5QDATA1封装；APFS3406592..47595510，44188919块，180997812224B（168.567348GiB）。原macosroot尾部Data不再作为默认数据盘，也不擦除。其他35个GPT分区不变。

生产证据位置：`package/B5qUfs/B5qDataFormat.h:10` mode3与`:12`精确边界、`:18` validIdentity、`:31` selectMode；`package/B5qUfs/B5qUfs.cpp:299`启动模式；`package/B5qRamStorage.cpp:44`持久分支与`:51`4.5GiB底线。均相对`/home/baimao/zflip5/UniXNU-b5q/`。

## 2. 精确改动清单

- `/home/baimao/zflip5/UniXNU-b5q/package/B5qUfs/B5qDataFormat.h`：新增userdataMode3/selectMode和固定边界；原名称/CRC/UUID/非重叠/封装/root-header校验保留。
- `/home/baimao/zflip5/UniXNU-b5q/package/B5qUfs/B5qUfs.cpp`：b5q-data-ufs=2选择userdata；0RAM、1原tail/macOSData兼容。命令队列、root/log写边界保持。
- `/home/baimao/zflip5/UniXNU-b5q/package/B5qRamStorage.cpp`：接受持久模式2，沿用PSCI就绪与内存底线，拒绝持久入口RAMseed。
- `/home/baimao/zflip5/UniXNU-b5q/board.toml`：只把Data参数1改2，仍981ASCII字节；两条fixup及其余输入/调度不变。
- `/home/baimao/zflip5/UniXNU-b5q/scripts/package-batch2-esp.py`、`relink-b5q-peripherals.py`：正常入口mode2/RAM回退mode0、复用Batch2并只编两对象。
- `/home/baimao/zflip5/scripts/b5q-install/b5q_data_format.py`、`install-data-ufs.py`：精确userdata选择、显式替换授权、拒绝挂载/data/dm/swap/已存在APFS；payload全量SHA/checkpoint/tail回读后才commit封装。
- 相关本地验收/回归、最小布局规划与userdata工作流同步；`AGENTS.md`记载最新授权，`porting.toml` findings/evidence已更新。未包含工作区其他固件/旧Batch1等无关修改。
- 首装时实时gzip流可减少ADB传输，不创建压缩包；原始输入按EOF写完以免dd count截断短包。

当前完整源输入哈希：

| 完整工作区相对路径 | SHA256 |
|---|---|
| `UniXNU-b5q/board.toml` | `29e4b1d8fb6204e4c5522083b6ba70eff23e5d5d4c54f7551bf8a939cd28bed9` |
| `UniXNU-b5q/package/B5qRamStorage.cpp` | `6236fd36e643524140221cc1376d2046130471e8bdd8cfef800ba004ad294f78` |
| `UniXNU-b5q/package/B5qUfs/B5qUfs.cpp` | `fe8bf3261227d8c2d567a51deef2cb775c90271e92e7e97c76360d4dfb4599a3` |
| `UniXNU-b5q/package/B5qUfs/B5qDataFormat.h` | `3801a84580eb3dba54211286c06f069fff701157b3d77d8fa945a989ea4cbc30` |
| `UniXNU-b5q/scripts/package-batch2-esp.py` | `e46b340c4b0f64559d9adf61954aa2080168e5be3978ae5aa30473adffc573ef` |
| `UniXNU-b5q/scripts/relink-b5q-peripherals.py` | `2e9b00b49fa365d6f7658fad9f148e7a230574d3c8e835194df82d3b127e6272` |
| `scripts/b5q-install/b5q_data_format.py` | `842ebf39060ea6441dcf7f1a2958aefbd293f8c83dd2eaf3c6462293ab7e988f` |
| `scripts/b5q-install/install-data-ufs.py` | `893debdca8caf03639635a5c04a1736c20975319b197e67c6db545013c0564f2` |
| `scripts/b5q-install/install-firstboot.py` | `ba7c039b2ccd3d6c0afc8bc7240dde733039ce8bcd51e1b24ef45d91648e1dad` |
| `scripts/b5q-install/plan-macos-only.py` | `a2219ec82089e48050d1bd75b026746f1f4d9d6385993f65605b5fa595d4d0ea` |
| `scripts/b5q-install/verify-batch2-images.py` | `337837b6a8539aca933e58229a9cb821bc64a2e1d0df1ae51020f0db83f19b28` |
| `tests/b5q-ufs/test-data-stream.py` | `bc520c31d637998cc759c73f9e4ad6da139a5cb6916f1081e37420549289512e` |
| `tests/b5q-ufs/test-image-hash-receipt.py` | `b375328016cece706200eabc484282f7d1781ef420ea874e6ca0688e1ee218cf` |
| `tests/b5q-ufs/test-userdata-installer.py` | `c2f0391b7300d2352e2eb14bf49f2da26ff17fc428783bc14466a5b2ffd1254b` |
| `.github/workflows/b5q-macos-only-userdata.yml` | `4d7fb3727102e474a93cf393eecf14957eac2ae683948dcc5c2a15166ee1d9a8` |

## 3. 未改组件与缓存复用

- XNU core archive SHA256 `88703fdc7eb18011294b5fe634d23b085496732f1e8bd4dd04e47f82dbe6ec2b`。
- GPU addon SHA256 `b68e1164f7dd0ff822f20e116e97adc4606926a4204fc25eaa5241c2a966d82d`。
- v30 DarwinBoot SHA256 `100080919035179c86c1f4b1eee16e6a8a46166beee95234dc2c842995009cde`；UEFI FD `df26529ae53be872b6c3856ab1f4fadb3c994fca8a8199c219112438783ea983`保持不变，不交付boot镜像。
- 原4GiB Batch1 seed SHA256 `d2e32a5f7dd37807a816d857d8b62eba41615c5da9ac335c2322e3c7a35ffc70`；原生扩容保留账户、Data UUID、59/26策略、absentd。独立RAM恢复入口仍使用原4GiBseed。
- 复用成功Batch2 CI45108577992；本次只编B5qRamStorage.o、B5qUfs.o；libNativeLegacyDisplay和libQcomDwc3逐字节不变。core/GPU/Mesa/UEFI均无重编，不运行QEMU。

## 4. 本地硬验证

`python3 scripts/b5q-install/pre-ci-userdata.py` 13组PASS，另加6个实际哈希复用门禁用例PASS。解包过程计算过的全量SHA只在dev/inode/size/mtime/ctime均未变化时复用，验收前后双次核对；修改内容后即使恢复mtime也拒绝。用户安装器始终自行计算完整SHA。19个Python/C++生产选择/封装正反用例ASan/UBSan；24个userdata实际CLI测试；原tail14类负面用例；8000队列并发迭代/6000实际Data请求；生产raw/gzip流完整零区/部分末块传输与异常不commit测试PASS。

两个arm64e目标对象无缺失/重复符号。对实际CI返回Xcode对象再次核验326个存储vtable槽、completion PAC IAe90c、PSCI/core IA0ba5及objdump零apps_smmu；kernel.json missing/stubbed/allow_missing均为空/false。未禁用任何签名或根完整性校验。

小型证据：`/home/baimao/zflip5/artifacts/b5q-userdata-work/pre-ci.json`、`returned-PAC-zero-smmu.json`、`final-verification/images.json`。CI后安装器仅改主机传输与回归，未改镜像内源码；未来上传压缩级别改1，不重新构建当前镜像。

## 5. CI产物与实际镜像回读

CI [45115332412](https://github.com/baimaosuki/b5q-uni/actions/runs/45115332412) **SUCCESS**，源码 `1df3521219f2232314bf5e1d4960f4526775758a`。普通artifact下载digest核对通过后稀疏解包。

| 交付IMG | 逻辑字节 | SHA256 |
|---|---:|---|
| `/home/baimao/zflip5/artifacts/b5q-esp-macos-only-userdata/esp.img` | 838860800 | `47b496286781e30245456475d5335ebd39bc10db7059477cb8c0bc13b327b840` |
| `/home/baimao/zflip5/artifacts/b5q-esp-macos-only-userdata/data-ufs.img` | 180997812224 | `d343babb7ca905c957c1b2643ae3cb92f844dd9c2cfd47bb911ef17f98edca0a` |

Data稀疏文件逻辑168.57GiB，实际主机占用285.3MiB；请保留稀疏属性，普通复制可能展开空洞。首装工具直接读取该文件，不先复制到手机文件系统。

实测FAT32扇区4096/1簇、双FAT/全成员/连续日志槽PASS；正常入口无initrd且mode2，独立RAM回退mode0；ADT6GiB/4GiB、8CPUcluster、恰好两条textfixup、lp-sip0=`0200000000000000`（8字节u64=2）PASS。Data账户、container/volumeUUID、root:wheel0644二进制disabled.plist59条/disabled.501.plist26条、空disabled.migrated、0755absentd及签名/trustcache、69处POST签名封闭全部PASS。回读原始内容见final-verification/disabled-plists-readback.json。

## 6. 本次用户执行命令

本轮未连接手机、未执行刷写。手机进TWRP，在挂载菜单取消挂载Data（不要Format Data）；工具拒绝已挂载/data或已初始化macOSData。首次转换覆盖Android数据，完整写入和回读需要时间；只运行一次：

```bash
python3 /home/baimao/zflip5/scripts/b5q-install/install-data-ufs.py \
  --image /home/baimao/zflip5/artifacts/b5q-esp-macos-only-userdata/data-ufs.img \
  --partition userdata --replace-android-data --apply
```

上条成功后更新ESP；以后更新也只运行这条：

```bash
python3 /home/baimao/zflip5/scripts/b5q-install/install-firstboot.py \
  --directory /home/baimao/zflip5/artifacts/b5q-esp-macos-only-userdata --esp
```

无需刷boot或macosroot，无需Odin、改GPT、删除super或其他旧分区。不要用此前30GiBdata-ufs.img替代本次168.57GiB镜像。

## 7. 实机日志验收对照

| 观察项 | 成功字段/结果 | 失败判据 |
|---|---|---|
| 持久Data | `B5qData: mode=3 LUN=0 window=[3406592,47595510] blocks=44188919 tag=1 FUA=1 writable=1` | identity/APFS失败、I/O rejected、意外RAM盘 |
| 内存 | `B5qMemory: ... physical-bytes=... minimum=4831838208 target=6442450944`及`outside adopted=... refused=...` | 低于4.5GiB；6GiB是目标，不保证UEFI占用后实际值 |
| 干净关机 | driver-notify `writes=FUA-still-accepted`；最终`B5qPower: ... data-flush=1`再PSCI | flush失败或PSCI返回；写文件重启丢失 |
| 输入/进程 | Batch2鼠标左键/右键/滚轮、30秒ProcTop TOP1..5与TOP6..10完整 | 点击/滚轮不生效或输出截断 |
| Batch1 | 常驻absentd、59/26策略保持 | respawn风暴/关键启动服务回归 |

物理持久化、正常关机与输入手势尚未在本次镜像上实机验证；本地通过不替代上述硬件结果。
