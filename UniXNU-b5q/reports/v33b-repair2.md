# v33b-repair2 最终交付

0. **完成度锁表**

| 编号 | 要求 | 源码/离线/原生/镜像验收 | 实证 |
|---|---|---|---|
| Req-1 | GPU 固件随最终 ADT 保留并严格验证 | DONE | payload具有三份固件，最终ESP重生成丢失的根因已修；正常/RAM/四档实际SHA回读通过 |
| Req-2 | 永久移除合盖，内屏+外接DP | DONE | 无lidWorker/featurebit1/PMclamshell通知/背光强制0/DP联动；mask61；无DSI1输出 |
| Req-3 | 蓝牙复位稳定和首命令前瞬态恢复 | DONE | 复位后guard+UART稳定窗口；一次有界Break恢复及损坏数据丢弃；重复/晚到/命令中/FIFO故障拒绝 |
| Req-4 | Wi-Fi -16 训练审计与实测状态日志 | DONE | 115PHY元组原厂一致、PERST/时钟时序模型通过；记录DBI728/72c/PHY214及电源时钟/引脚时序，物理L0原因未冒充已知 |
| Req-5 | USB Device原生电源触发路径日志 | DONE | familystart、cable请求、desiredpower、POWER_ON回调和当前电源态可定位on0；不强行启动DMA |

DONE 限本轮要求的实现、审计和离线验收。真实桌面、蓝牙版本、WiFi L0与USB Device枚举仍为 HOST_VERIFIED_PENDING_HARDWARE；本轮没有连接或刷写手机。

1. **实证取证表**

- 本次实机 BIN SHA256：`09ea8203ed63805d638840365a23312af883a5225c97385c17d013cf2201e199`；L207 GPU固件无效，L408/409合盖息屏，L641 PCIe-16。
- [旧payload/ESP直接对照](/home/baimao/zflip5/artifacts/b5q-v33b-repair2-work/GPU-ADT-regression.json)：CIpayload具有GMU66844B、SQE76724B、ZAP12088B及正确SHA，交付ESP均缺失；错误来自本地重新生成ADT。不是CI漏跑stage。
- [原厂输入哈希](/home/baimao/zflip5/artifacts/b5q-v33b-repair2-work/input-evidence.json)：b5qDT SHA `345420f6987a86bbaaa930c9b908668e172fdcfde44d57624679cd93c8cafb1f`；Samsungmsm_geni_serial.c3494..3506处理parity/break，btpower.c729已含50ms等待。当前共享radio_enable也已有55ms，新增的是切换UART后的保护。
- PCIe115对PHY逐项匹配原厂qcom,phy-sequence；原PERST>=100ms和释放后1ms与Linux驱动一致。没有现有实测LTSSM值就不能断言-16是哪个物理条件。

2. **精确修改清单**

- [源码路径与SHA清单](/home/baimao/zflip5/artifacts/b5q-v33b-repair2-work/delivered-sources.json)；源码提交 `037cd05c654f92145ef82bd86fc4c40a415bfccc`。
- b5q_gpu_adt校验并保留payload的三份原厂固件；stage、payload返回门禁、所有最终ADT和ESP回读均强制校验大小及SHA。三星固件没有提交Git。
- B5qDaily/B5qFeatures/B5qBacklight/B5qDpLink去掉GPIO107采样、lid位、clamshell通知、背光强制0及DP合盖联动；内屏DSI0与外接DP保留，不初始化或渲染背部DSI1。
- B5qBluetooth/B5qBtFifo增加50msguard+20ms稳定期；丢弃启动损坏RX，仅一次50ms内且尚未发命令的线路错误可恢复，其他线路/FIFO错误明确失败。
- B5qPcieCore/B5qWifiBoard保留原厂115PHY与已核实时序，记录实际728/72c/214、GCC/PARF和WLAN_EN/PERST耗时；QcomDwc3增加原生Device电源路径日志，不强制DMA。porting.toml同步来源与证据。

3. **未改组件与缓存**

- XNU core源码和补丁未改；匹配编译进度复用并按原生依赖重链板级对象。GPU/Mesa与用户态addon复用既有缓存；GPU firmware严格保留原始字节。
- 复用同一4GiB APFS恢复容器及58/25策略，不初始化或读取实体168.5GiB Data。
- UEFI13份补丁、源码锁、固件配置和构建job逐字节一致；复用FD及boot。boot SHA：`0c9f83986eae0f239f9e5a7f6fc81ee98ea56bf865fdb84b6f596c9566de3bc6`。固件复用[完整证明](/home/baimao/zflip5/artifacts/b5q-v33b-repair2-work/returned/firmware-reuse.json)，本次只交付ESP。

4. **本地硬验证**

- pre-ci-p4.py + pre-ci-v33b.py：22组门禁、377文件SHA绑定，全部PASS。原有Wi-Fi plist断言保持。
- 真实payload→空配置→正常/RAM ADT保留测试；三份固件各missing/short/corrupt共9负例与上次坏ESP均拒绝。
- 257项真实背光目标计算、无合盖/DSI1扫描；4096种BT TX长度、RX/背压/取消、启动Break正例及重复/晚到/命令中/FIFO反例；ASan/UBSan PASS。
- 原厂115PHY逐项一致，WLAN_EN/PERST/时钟/LTSSM因果模型、3种超时状态捕获PASS；22组含原有P0–P5回归。
- 实际arm64eABI/PAC、无线/媒体/DP符号闭包、NormalWB/MMIO映射参数与零EL1apps_smmu检查见[返回二进制门禁](/home/baimao/zflip5/artifacts/b5q-v33b-repair2-work/returned/package-ready.json)。

5. **CI与实际镜像回读**

- [CI 45443154576](https://github.com/baimaosuki/b5q-uni/actions/runs/45443154576)成功。普通Actions artifact整体SHA、每个成员SHA与manifest验证通过。
- [esp.img](/home/baimao/zflip5/artifacts/b5q-esp-v33b-repair2/esp.img)：**838,860,800字节**；SHA256 `cfcdc33d75d62e35b83807298e7ecbf84580661a0cb79e1423b50430edeb1cb2`。
- 两次独立FAT32/4Kn、菜单、ADT/APFS/签名/trustcache/内核/PAC回读PASS；featuremask61、lp-sip0为8字节u64=2；两条BGRAfixup保留。
- [四档GPU固件回读](/home/baimao/zflip5/artifacts/b5q-v33b-repair2-work/GPU-all-profile-readback.json)：每档3属性大小/SHA均匹配内核要求；[第一次](/home/baimao/zflip5/artifacts/b5q-v33b-repair2-work/readback-1/images.json) / [第二次](/home/baimao/zflip5/artifacts/b5q-v33b-repair2-work/readback-2/images.json)。

6. **仅更新ESP**

TWRP中由机主执行；脚本先核验镜像SHA、机型、ESP精确GPT边界与4096扇区，再仅写ESP并回读SHA。boot、userdata、macosroot与GPT不写。

```bash
cd /home/baimao/zflip5
python3 scripts/b5q-install/install-firstboot.py \
  --directory artifacts/b5q-esp-v33b-repair2 --esp
```

7. **新XNU2LOG验收**

| 项 | 成功/诊断关键字 |
|---|---|
| GPU/桌面 | 不再Samsung-firmware-invalid；B5qGpu stage1..97及swap accepted，WindowServer不再signal6循环 |
| 内屏 | B5qDaily lid=removed，featuremask61；无B5qLid线程、clamshell通知及closed=1强制背光0；不输出背屏 |
| 蓝牙 | reset-settle、rx-settled显示pins/ios/startup-line/discarded/irq；QCA版本是否读出仍需物理日志确认 |
| Wi-Fi | link-state显示dbi728/dbi72c/ltssm/up/polls/phy214；perst显示held-us与wlan-return-us，link-clock显示GCC/PARF |
| USB Device | family-start→cable-request→desired-power→power-on；power-path给出started/allowed/requests/wanted/cable-result/pwr，on0可定位卡在哪一层 |
