# review8 交付

内核 CI [45656654077](https://github.com/baimaosuki/b5q-uni/actions/runs/45656654077) SUCCESS，源码 `961b809025325dea5c60b419d329fb1d6721ab78`。固件任务跳过，复用已实测 review7 的 64 MiB 固件，FD SHA256 `a98a68dbe8921e578cb54a27ea7a592414015846897ada7af0b97d8de1765c37`。全部固件补丁、源码和 loader 输入逐字节一致；boot.img 与 review7 完全相同。

| 要求 | 实现与本地证据 |
|---|---|
| Wi-Fi | split 回调替换旧 BSS 回调；实际生成 ath11k_ops 与 mac80211 原始互斥断言测试通过。返回目标对象依据真实 arm64e struct 偏移证明旧槽为零、split 两槽有正确重定位；旧 review7 对象负例被拒绝。 |
| 触控 | 仅活跃 kind=1 触点使用 GPIO19 40ms 超时；真实超时、ATTN 高、IRQ 计数未变才清空并 publish(true)，不标恢复。生产 publish→鼠标路径验证正常点击和 32ms 按下保持；IRQ/ATTN 竞态与空闲无轮询负例通过。首五个被忽略非11报告前8字节限频记录。review7 增益、326 CPI、slop/限幅未改。 |
| USB DRP | 按原厂 CCCTRL1 的0b/0c及位4/3/0初始化，保留电流位与既有debug/audio位；同一SE8锁覆盖整个邮箱请求/响应。已有连接、VBUS或水检测时不改策略，发送前重查。256个控制值、读回拒绝/超时/错opcode/插线竞态及实际板级init与48/88诊断测试通过。 |

原始 returned 门禁、无线＋ADSP 156对象联合闭环、跨对象 PAC、零 EL1 apps_smmu、GPU/签名/Wi-Fi plist、ADT/APFS/四档菜单与最终 4Kn 镜像回读全部 PASS。

- `/home/baimao/zflip5/artifacts/b5q-esp-review8/esp.img`，838860800 字节，SHA256 `ec938421e2456e2a8efb00827e8be90de0f8987d212954f54a9a6293b8ff501e`。
- `/home/baimao/zflip5/artifacts/b5q-esp-review8/boot.img`，19124224 字节，SHA256 `20eac73c262470d43984b8edd363dde55f86e38fb75312a68b4a32610907470a`。

状态 `HOST_VERIFIED_PENDING_HARDWARE`：review7 已实测的蓝牙与64MiB DMA为基线证据，本轮新Wi-Fi注册、单击和Host枚举待实机核验。未连接、刷写手机或访问持久Data；无需重刷userdata。
