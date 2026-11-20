# b5q v13 启动日志分析

输入 `logs/b5q-xnu2log-v13/XNU2LOG.BIN` 的大小和 SHA256 与用户提供值一致。双槽 CRC 有效，最新序号341，正文147013字节；报告竞争丢失0、覆盖0。解码文本保存在同目录 XNU2LOG.txt。

系统已越过先前的日志分配断言与 PID1 中止，完成早期 boot tasks。日志记录 loginwindow105、WindowServer111，以及后续到PID366的进程启动；没有记录新的内核 panic 或这两个桌面进程的退出。尚不能据此认定桌面已经绘制。

1. cpu1到cpu7在三次IOKit busy记录中均未完成匹配；最后root busy仍为1。ArmCpu源码要求显式smp才能接受副核，当前配置没有该参数。应核查CPU nub匹配/忙计数生命周期与IOKit quiet；当前没有WindowServer线程栈，不能将其等同于已证明的等待链。
2. unixnu-absentd的PID238和253被enforcing Launch Constraints以SIGKILL杀死，reason3:4。现有补丁已包含no-lc参数入口，而配置未启用；需审查上游bring-up策略或修正替身的启动约束。有效签名/CDHash不能单独证明Launch Constraints也会允许启动。
3. default IOSurface已建立，1080x2640、stride4352。没有记录实际copy/frame事件。`display object not attached (kext0)`来自辅助IODisplay/EDID子节点，kext0表示加载成功；这行并不证明主framebuffer启动失败。主显示客户端和辅助节点仍需分别核实。

当前日志不支持“解锁后必然无Metal触发SIGABRT”这一确定结论，也没有记录CPU渲染失败。后续优先处理IOKit匹配和替身Launch Constraints，再根据WindowServer实际状态判断显示/渲染路径。

末尾error30为只读文件系统；mount_apfs的0x4d00是退出码77而非errno。Data与AppCryptex的重挂载更新成功。KeyStore拒绝和软内存告警应记录为后续兼容问题，当前未见它们导致PID1退出。bootstrap页数不能当作末尾剩余内存。

logger中的v12文字在v13继续沿用，不能据此判定刷错镜像。本次仅分析和更新移植记录，未修改驱动、配置或镜像，未触发CI。
