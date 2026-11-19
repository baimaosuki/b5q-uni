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

## 当前扩展任务（2026-11-19，用户最新指令）

用户要求在本工作区独立目录从原始 IPSW 重新提取，并依据用户提供 GPT 准备完整安装产物和刷入指南。允许继续独立文件构建与差异审计；不代表已授权连接手机、写分区或越过 RamBlock-before-UFS 门槛。用户已明确 root 目标为新建 macosroot（48GiB）、esp 为800MiB；禁止把上游 userdata 刷写命令直接套用到该布局。若当前板级实现缺少完整启动路径，必须如实记录具体阻塞，不能把素材包标成完整可启动刷机包。

## UFS 暂停已解除（2026-11-19，最新明确用户授权）

允许实现、编译和打包面向 macosroot 的 b5q UFS 根读取路径，包括所需控制器队列与专用 SMMU 流配置；此前 UFS 开发暂停及其门槛不再阻止本次实现。首版限定系统根只读，Data 在 RAM；禁止发出持久块写命令和访问受保护分区。允许扫描 GPT 元数据以识别唯一 macosroot，严格匹配用户范围；不得从分区表猜 LUN。无需再次确认继续驱动开发。仍未授权直接刷写手机，也不得把编译成功称为实机进入桌面。

## CI 检查位置（2026-11-19，最新用户指令）

新增的完整性、源码契约、设备记录、模板一致性及打包输出校验均在本地完成；推送前执行本地 pre-ci 并保留结果。CI 负责依赖准备、上游构建/打包和产物传回，不新增中途验收关卡，不取消或丢弃已构建的产物。目标编译器及上游正常构建自身的错误仍如实保留；不通过禁用密码学、签名或链接正确性来伪造成功。生成后才可验证的实际二进制在下载回本地后检查。

## 按指南恢复既有部署基线（最新用户指令）

不得新增自定义入口/延时复位探针、额外测试菜单或要求用户跑探针。撤销助手把“不新增探针”扩展成“禁用原有 panic_screen、必须部署 CI 中间内核”的决定。按已锁定 UniXNU 指南恢复此前的 payload.panic_screen=true 和已由官方 payload 步骤生成的部署副本；不启用 entry_probe_reset_delay，不增加复位测试项。不得把原来蓝/品红标记被移除后的仅绿条画面当作执行退步的证据。每次只更正有来源的差异，不改 DTS、内存窗口、驱动或启动参数来猜测修复。

用户已报告实体 ESP 需 4096 字节 FAT 扇区才可挂载；保留这项设备格式适配（800MiB，-S4096 -s1）。RAM FAT 的独立 BlockIo 和 sysfs 的512字节计数单位不得混为一谈。scripts/package.sh 必须与 UniXNU/templates/package.sh 一致。撤回 v3 自定义复位包与 v4 中间内核替换包，历史产物仅作追溯。

## 镜像交付（2026-11-20，最新用户指令）

后续只交付本次需要刷入的 `.img`。不自动生成 Odin TAR、ZIP、tar.zst、整包压缩档或同内容的重复镜像。构建与校验所需的临时文件使用临时目录，完成后释放；必要源码、移植记录和小型构建元数据保留在工作区。刷入命令直接写在回复中。

## CI 传输与验证成本（2026-11-20，最新用户指令）

使用普通 GitHub Actions artifact 返回构建产物，禁止加密 Checks 回传。非必要不运行 QEMU；协议问题优先用实际生产辅助函数的本地回归、目标编译器和返回二进制验证。交付仍为本次需要的 IMG，传输 ZIP 仅可放临时目录并在解包校验后释放。
