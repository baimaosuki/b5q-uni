# Batch 1 / v33 验证记录（硬件验收尚未完成）

## 1. 实证取证表

输入是 macOS 27.3 `26C5035r` 系统卷的真实 `/sbin/launchd`，不是 iOS 替身。

- fat launchd SHA256：`33cb5981d59aa60db3c27fd309a9aa95bf77ae1bef8369beffa3e9ba37f926bc`
- OS.raw.dmg SHA256：`40d8282eb8650da9b4d7437a981764c48d47ee4bdc5b8b362248f25ecbce0e70`
- 完整指令字节：[runtime-v33.json](runtime-v33.json)；19 项原指令回归：[launchd-26C5035r-policy.json](launchd-26C5035r-policy.json)。系统调用/libxpc 使用边界替身，PAC 指令仅作仿真控制流处理，不能当作硬件 PAC 测试。

| 功能 | 原始地址 | 已核实行为 |
|---|---|---|
| SIP | `0x1000480d8..0x1000480ec` | `mov w0,#2; bl _csr_check`，返回非零设置 rootless 标志 |
| 系统禁用文件 | `0x100048b10..0x100048b3c` | 格式化 `%s/disabled.plist`，调用安全文件读取器 |
| 每 UID 禁用文件 | `0x100048b94..0x100048bd8` | `disabled.%u.plist`，使用相同读取器；501 仍要求文件 UID=0 |
| 迁移标记 | `0x1000488d0..0x1000488d4` | `stat` 成功跳转 `0x100048b10`，只跳过旧数据库迁移；不跳过当前策略 |
| 属主/权限 | `0x10005bd54..0x10005bd70` | fstat 成功、st_uid=0、st_mode & 0x12=0；未检查 st_gid |
| 覆写查询 | `0x10002ed68` | 域 +0x3a0 字典，接受布尔值或含 Disabled 的字典 |
| SIP 限制 | `0x100003e94..0x100003f30` | system import flag bit8 + SIP 时，非 RemovableServices 的覆写被忽略；_Protected 也限制覆写 |
| 强制启用 | `0x100003f34..0x100003f70` | ForceEnableHack/导入标志可写启用状态；已选常规 plist 未含该字段 |

907 份常规 plist 与实际 Label/路径/哈希见 [census](launchd-26C5035r-census.json)。11 个符号链接未当成独立提取成功。`usermanagerd` 的正确 Label 为 `com.apple.mobile.usermanagerd`。ReportCrashService、geod、WallpaperAerials 是独立嵌套 XPC/ExtensionKit 项，不能仅凭同名守护程序判断它们已被禁用。

## 2. 精确改动清单

所有相对路径以 `/home/baimao/zflip5/` 为根。

| 路径/函数 | 修改 |
|---|---|
| `UniXNU-b5q/board.toml` | 仅把原生 ADT `/chosen/asmb/lp-sip0` 从 0 覆写为 u64=2；用户明确授权，其他 SIP 位保持 0 |
| `UniXNU-b5q/package/B5qProcTop.c`：created/exited/reporter/b5q_proc_top_init | 原生 MAC 只观察 fork/spawn 与最终退出；不增加访问控制决定；30 秒 TOP-10 |
| `UniXNU-b5q/package/B5qProcTop.h` | 静态桶位、原子计数、显式 overflow、无需持锁打印；同名合并 |
| `UniXNU-b5q/package/B5qBootPolicy.c` | stand-in 保留原生 mobileactivationd/cryptexd 两项；不替换 EndpointSecurity |
| `UniXNU-b5q/patches/tools/b5q-absentd-user-domains.patch` | 记录 PID/Label/配置来源/监听错误/退出原因；Daemon/Agent 正常驻留，无 Label 同步任务成功返回 |
| `UniXNU-b5q/package/b5q-launchd-lite.json` | 根据真实目标 plist 修正/补充服务 Label，删除旧 iOS/错写项 |
| `UniXNU-b5q/scripts/update-b5q-launchd-seed.py`：policies/merge/main | 更新原 4 GiB seed，不重建卷；重写板级策略，移除 EndpointSecurity，root:wheel 0644 |
| `UniXNU-b5q/scripts/b5q_peripherals.py` / `relink-b5q-peripherals.py` | 仅添加板级观察对象、使用固定 XNU 头文件 ABI、从 v32 cache 增量重链 |
| `.github/workflows/b5q-v33-incremental.yml` | 一次增量 CI，复用核心/GPU/固件及现有 Data 卷 |
| `scripts/b5q-install/{check-macos-launchd-policy,check-proctop-pac,check-peripheral-target,pre-ci-v33,verify-v33}.py` / `tests/b5q-ufs/{test-absentd-v33.py,test-proctop.cpp}` | 本地生产路径/目标编译/PAC/最终镜像回读检查 |
| `UniXNU-b5q/porting.toml` 与本目录证据 | 同步 configuration/packaging/diagnostics findings/evidence；没有升级硬件完成等级 |

本批没有修改触控、USB、GPU、UFS 写策略。v32 的七条 absentd unnest 日志没有 Label/退出状态，因此“同一服务重启七次”的精确原因仍 unknown。已消除三项不必要的 stand-in 重定向并补齐身份/退出诊断；不能伪称已从旧日志得到了缺失的退出证据。

## 3. 未改组件与缓存复用

- 核心归档：`88703fdc7eb18011294b5fe634d23b085496732f1e8bd4dd04e47f82dbe6ec2b`。
- NativeHidInput：`4aa18187b0d7229d05908df2bb96767267ac993a4a7251ab480aa38e2fbf6da3`。
- GPU addon：`b68e1164f7dd0ff822f20e116e97adc4606926a4204fc25eaa5241c2a966d82d`。
- 原 seed：`f84207df2076b9eec9f1ba5bec3e2a4e97e8eff1f10ee460967c2dcb91288e2f`；仅原卷内策略/absentd 更新。
- UEFI FD：`df26529ae53be872b6c3856ab1f4fadb3c994fca8a8199c219112438783ea983`。
- 保留已装 v30 boot：`d7124d060a25d623e356cabd3d28c1af61ed38b902f47e78f82a73a6f192dbf6`。

## 4. 本地硬验证

`python3 scripts/b5q-install/pre-ci-v33.py`：12 项 PASS，包括真实 launchd 19 组指令、absentd 全生产源码 8 组 ASan/UBSan 路径、统计的 160000 次并发退出/信号/窗口重置/满表测试、arm64e 编译和符号闭合、fork/exit/startup PAC 对比、账户/日志/安装器回归。

另运行实际 reporter 代码的两轮 30000ms 等待/窗口清空/exit78/sig11 输出测试，以及完整 absentd 的 macOS arm64e 目标编译。原核心 MAC 消费者 PAC：fork=`0x73d8`、exit=`0x2abe`、startup=`0x2abe`、线程 continuation=`0xd507`。新观察对象无硬件映射/SMMU 导入。CI 返回的实际对象已再次核验，四组 PAC 均一致；未进行硬件 PAC 执行测试。

## 5. CI 产物与回读

- CI：[45041019820](https://github.com/baimaosuki/b5q-uni/actions/runs/45041019820)
- 源码：`ac082c9d53049323fd701cec5d6ba5bd7621bc1f`
- 最终 `/home/baimao/zflip5/artifacts/b5q-esp-runtime-v33/esp.img`：838,860,800 字节，SHA256 `aedf41d4fca73fb7de4f3e0ce183e03f5ced72bc74316af5503d731f6fa54975`。
- 原始 Actions artifact SHA256 `d2106cf1fc9ead49ade8e824850c71b7b07969f19405a48e2d4c6d9d0290a549` 与 GitHub digest 一致；下载 ZIP 已由临时目录释放。最终只保留一个 ESP；按既有部署流程恢复同一 v30 DarwinBoot，其他 FAT 成员的差异逐项核验。
- 实际 ADT `/chosen/asmb/lp-sip0` = `02 00 00 00 00 00 00 00`。生成器既有 `lp-sip1` 和其他 asmb 字段与 v32 相同，仅 lp-sip0 改变。
- 实际 APFS Data：55 条系统覆写、22 条 UID501 覆写，文件 root:wheel、0644，目录/账户/自动登录、watchdogd 禁用、4 GiB 原卷 UUID 核验通过。新 seed SHA256 `3c375836fac6170e005ad164d41b05e275114246cd25657c944fa8c97b6b8c5e`。
- 返回两个板级对象的归档归属/强符号闭合/全部新回调 PAC 校验通过，核心归档与 GPU/HID/USB 既有成员哈希未改。新部署内核 SHA256 `8c074f84888d78f3e834238b250463270baec7b5aec2cad0eeb120f4fb9c2bd9`。
- 真实代码签名页及信任缓存核验通过，absentd CDHash `5e1f509bc19e008098a2973fa89dac228f06e69e`。完整 boot-args 保持 949 字节，BGRA 两条 fixup 保持；不发布设备身份信息。
- `fsck.fat -n`、XNU2LOG 2051 连续簇/双 FAT/无别名/token/CRC、POST seal 校验通过。
- 只完成构建与回读；第 7 项硬件验收仍未完成。

## 6. 本次刷写命令

仅在第 5 项最终校验通过后使用，只更新 ESP：

```sh
python3 /home/baimao/zflip5/scripts/b5q-install/install-firstboot.py --directory /home/baimao/zflip5/artifacts/b5q-esp-runtime-v33 --esp
```

本任务没有连接或刷写手机；不使用 --repair，不覆盖 boot。

## 7. 实机验收

- [ ] `B5qProcTop: observer status=0`、`reporter status=0`。
- [ ] 每 30 秒有 `B5qProcTop: window=30s spawns=N exits=M top=name:cnt(exit=code/sig=sig),... overflow=0`。
- [ ] 进桌面后目标嘈杂服务停止持续重启；保留 WindowServer/loginwindow/Dock/Finder。
- [ ] `B5qAbsent` 可识别每个 PID/Label；有效服务驻留，缺 Label 同步任务成功退出；没有 EndpointSecurity 回归。
- [ ] 桌面持续 3 分钟以上、最大 PID 低于 1500（验收目标，不以 PID 当精确启动计数）。
- [ ] 空闲多数 CPU <300‰、温度 <80°C，目标 55–72°C。
- [ ] 零 panic、无 retained-log 丢失；若任一项失败，仍留在 Batch 1，不能开启 Batch 2。
