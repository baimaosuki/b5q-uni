# v33d review3：五项定点修复

状态：**LOCAL_REVIEW_READY / HOST_VERIFIED_PENDING_HARDWARE**。4 项 P0 与 1 项 P1 的本地修复和总门禁全部通过。未提交、未推送、未触发 CI、未生成 ESP、未操作手机。

## 复审入口

- 增量 diff：`artifacts/b5q-v33d-review3/complete.diff`，只相对本轮修改前562文件快照；含必要新增文件、单测和记录。
- 完整 stdout/stderr：`artifacts/b5q-v33d-review3/full-test-output.txt`；最终总入口结果为 `pre-ci-final.log` / `v33d-local-gates.json`。
- 源码与证据哈希：`artifacts/b5q-v33d-review3/SHA256SUMS`；同名 JSON 内记录每个变更与输入 SHA。
- 复现命令：`B5Q_GATE_WORK=artifacts/b5q-v33d-review3 python3 scripts/b5q-install/pre-ci-v33d.py`。

## 五项对照

| 要求 | 状态 | 修改 | 本地证据 |
|---|---|---|---|
| P0-1 | LOCAL_DONE | primary 删除全部 self/owner retain/release；inFlight 是 IRQ 与线程退役的唯一生命周期屏障，route/unregister 仍在释放前排空。 | ASan/UBSan 执行生产 Nub；禁止硬 IRQ retain/release/free，并让线程在 IRQ 最终解锁后、IRQ 返回前销毁 owner+nub 最后引用。 日志：`irq-first.log`, `artifacts/b5q-p1-work/usb-irq.log`, `target-compile.log` |
| P0-2 | LOCAL_DONE | PPID0ba 不预过滤owner；observer 先读 type/subtype/mode/vin/pull/src/en。已启用函数2时任意owner直接保留；仅未配置APPS-owned LV/MV pin打开channel按五步写入；回读仅判断有效字段。 | 覆盖 owner3 已启用且不打开/写channel；owner3 未启用拒写；owner0 写入五寄存器；保留位非零仍成功；原有幂等、错误 subtype 和 RPMh 回归保留。 日志：`v33d-wcn-init.log`, `wireless-all-callbacks.log` |
| P0-3 | LOCAL_DONE | 独立共享 AOSS QMP IOLock，强定义由WCN提供；WCN pdcInit 整段和生成ADSP init/send/wait/abandon 使用同一 RAII 锁，ADSP 在 RPMh 投票前释放。目标闭包纳入真实WCN provider与ADSP consumer。 | 真实生产 QMP + 同时启动的 WCN/ADSP 线程，11+1 条消息无重叠；等待时独立 RPMh mutex 可用；timeout/abandon/提前返回解锁且可重试。158对象联合符号闭包与80认证契约通过。 日志：`v33d-review3.log`, `wireless-ADSP-joint.log`, `wireless-ADSP-closure.json`, `artifacts/b5q-p4-work/pre-ci/joint-symbol-vtable-zeroMMIO.log` |
| P0-4 | LOCAL_DONE | reuse分支重编当前kits/b5q/B5qGpu.cpp和GMU helper，ar r替换两member，mmio-helper/reuse记录两者与source/archive/member哈希；其余成员必须SHA不变。返回门禁读取真实上传libAdreno740.a，拒绝旧B5qGpu。restartSecondary同时要求gPreemptWanted和gSubmit.preemption()。 | 真实51成员归档49个SHA相同，仅指定两个替换；已替换归档再次复用仍执行两次编译调用，允许确定性相同输出；返回旧GPU成员负例被拒绝。Host archive案例编译调用为桩，但注入的是另行真实目标编译的当前arm64e对象；不冒充本机执行Xcode record编译。 日志：`gmu-archive-index.log`, `archive-return-first.log`, `v33d-review3.log`, `target-compile.log`, `all-cross-object-PAC.log` |
| P1 | LOCAL_DONE | USB failed load terminate后显式return；Ethernet enabled判断移入linkAction，调用侧不再读controller->enabled；仅b5q-build retention3→30。 | 生产USB失败分支在terminate返回时仍不继续；Ethernet排队后enable/disable改变只由gate内判定；workflow差异严格只有retention一行。 日志：`v33d-review3.log`, `wireless-all-callbacks.log`, `target-compile.log` |

## 验证范围

- 本轮完成一次包含重新执行 P0–P4 的完整总门禁，再在最终源码上复跑总门禁；第二次仅复用源码哈希完全一致的 P0–P4 凭据，其余门禁重新执行。最终精确项数见 JSON，不将嵌套组重复相加。
- IRQ 生命周期、PMK owner/保留位、共享 QMP 并发/超时、GPU secondary 条件、Ethernet gate 与 USB 线程退出均执行生产函数/生成生产片段，Host 测试启用 ASan/UBSan。
- 真实旧 Adreno 归档共51个对象，仅 NativeAdrenoGmuService.o 与当前 B5qGpu.o 被替换；其余49个 SHA 完全一致。已打补丁归档重复复用仍调用两个编译步骤，输出相同合法；返回门禁会读取上传归档而非只相信 JSON，换回旧 B5qGpu.o 必须失败。
- 归档单测对编译器调用使用受控桩，以实际另行目标编译的 arm64e 对象注入；本轮没有在 Linux 上冒充执行 Xcode 原生 compile record。生产脚本已接入真实 record 编译当前 board source，后续 CI 仍须验返回产物。
- 共享锁由 WCN 对象提供真实强符号；媒体审计增加该真实 provider，联合审计包含 ADSP consumer。**158 对象 / 80 项认证契约**通过，未解析符号与重复定义均为0；联合对象零 EL1 apps_smmu。
- 本地通用 arm64e、无线、媒体、DP 目标编译、原有 PAC、31 板级对象零 EL1 apps_smmu、16补丁重建和7个EDK2对象检查全部继续通过。没有新内核/固件最终链接。
- `porting.toml` 新增 `v33d-review3-five-fixes`；单独保留了报告文件生成前记录校验的缺文件失败，生成报告后重新校验通过。其他测试无失败被隐藏。

## 未改动与暂停点

board.toml 与0014补丁逐字节不变，启动参数仍1011B；不输出完整bootargs。固件/loader无本轮修改，不引入lid/副屏代码。Wi-Fi ready/RunAtLoad断言AST和verify-p0-images.py保留，用户已有TWRP修改逐字节不变。

工作流唯一差异是 `b5q-build-*` 保留期3→30天。上轮动态artifact发现逻辑保留，没有重新依赖45047962341，也未发起artifact下载或CI请求。

所有修改已限制为五项及其直接所需的测试/编译/返回验收支持。完整增量patch在临时Git目录执行apply --check、实际apply和逐文件字节比较。依据本轮“仍暂不推送、不触发CI、不生成ESP、不操作手机”，当前停在终审环节。实体硬件结果不属于本轮已验证范围。
