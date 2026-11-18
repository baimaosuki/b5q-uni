# b5q port: stage contract

当前授权：**完整 b5q macOS 27.3 自动化移植与构建流程**（后续用户指令取代此前 Stage 1 等待确认要求）。
目标设备：Samsung Galaxy Z Flip5 / b5q / SM8550-AC。
目标系统：`macos-27.3-26C5035r`。

## 硬性约束

1. 按官方 Format 2、packaging 与 macOS 指南实施完整移植与编译。可以连续完成硬件提取、UEFI、内核、图形和打包，无需阶段确认；遇到无法解决的输入或环境阻塞，保留首个失败日志并向用户明确缺失项。不得伪造编译或硬件成功。
2. 每次变更必须在同一变更中同步更新 `UniXNU-b5q/porting.toml` 对应 area 的 **findings 与 evidence**，记录具体发现、来源、输入哈希与验证结果。它是本工作区两套骨架的唯一移植记录入口。不得以成功编译替代实机证据。
3. 严禁复用 UniXNU-sheng 的 **ShengPreflight**（小米 fastboot 镜像分段下载）、**DRAM reserved-memory、GPIO、Novatek 触控、小米签名固件**。仅参考目录结构、格式和接口；禁止把 sheng 的 DTS 数值写入 b5q。共享 SoC 定义也必须经 b5q 证据核对后再采用。
4. **RamBlock 验证通过前，严禁启用任何 UFS 控制器写操作**，包括命令提交、初始化/复位/时钟配置等 MMIO 写入、DMA、块写入和持久化。默认配置使用 RamBlock，不访问 UFS 控制器；B5qUfs 是独立可选路径。后续 UEFI 如含厂商 UFSDxe，必须单独审计并默认不调度，不能仅禁用 OS 层写接口。
5. **严禁触碰三星 `efs`、`sec_efs`、`param`、`xbl`、`abl` 分区**，包括读取、写入、格式化、擦除、挂载、重分区、刷写，以及其槽位/别名变体。已有 DT 文件中出现这些名字不构成访问授权。
6. 区分：Project-Silicium 参考 DTS/DTB、TWRP 预置 DTB、既有本地构建镜像、手机本机原始提取物。必须记录父文件、提取偏移、SHA256、来源提交；同源复制不能记为独立佐证。
7. 缺失值必须写为 `unknown` / `pending` 并说明待验证证据，不得猜测。DRAM 物理 bank、Linux `/memory/reg`、可分配 RAM、保留区与显示缓冲区不是同一概念。
8. 不发布完整 `/chosen/bootargs`、bootconfig、设备序列号或其他设备身份字段。只提取本阶段所需的硬件属性。
9. 保留此前 sources、补丁与 artifacts 的来源记录；对齐新源码时使用独立 checkout 或可复现补丁。UniXNU-b5q 与 uefi-b5q 分别负责设备与固件。构建授权不等于对手机执行刷写授权。
10. CI 凭据只用于认证，严禁写入文件、Git、日志、命令行参数或文档。

## 必读与记录

- `docs/macos-27.3-repositories.md` 和 `.json`。
- `sources/UniXNU/docs/porting/device-repository.md`、`records.md`、`device-tree.md`。
- `sources/UniXNU/components.toml`、目标 OS profile 和 SM8550 公共层的 `AGENTS.md`/`soc.toml`。
- `UniXNU-b5q/README.md`、`UniXNU-b5q/porting.toml`、`uefi-b5q/README.md`。

新设备仓使用格式 2；移植记录使用其官方独立的 schema version 1。
优先执行官方 templates/package.sh；依赖、固件或补丁失败须保留真实首错。仅在产物实际存在且校验通过后报告对应成功状态。

## 当前收窄目标（2026-11-19，用户后续指令）

仅闭环编译 `macos-27.3-26C5035r` 的真实 `kernel.macho`、RamBlock `payload.img` 和 `package.manifest.json`。
暂停 B5qUfs 与所有固件构建，不连接或采集设备，不汇报中间进度。
允许明确记录、拒绝硬件访问的板级兼容桩；禁止把桩当驱动成功、绕过签名/VerifiedRoot 校验或伪造系统根挂载。
每轮先整体分析全部最终链接缺失符号，静态核对后推送并跟进到 CI 结束。
仅在产物生成并下载校验成功，或三轮修复仍留下同一批符号并提供完整调用位置/精确参考差异时最终回复。
