# b5q 自动交付

用户授权提交本轮并开始 CI 后，直接运行：

```bash
python3 scripts/b5q-release.py start --review review15
```

`review15` 替换为实际轮次。只在 `main` 持续开发：它读取对应 `UniXNU-b5q/reports/review15-source-audit.json`，验证已有本地门禁与源文件哈希，仅暂存该清单及对应 porting 记录，提交到 `main` 并仅推送 `HEAD:refs/heads/main`。已测试但未列入本轮清单的脏源文件会阻止提交。发布脚本拒绝其他分支和其他推送目标；远端仅保留 `main`。

同一进程连续完成：提交、推送、发现对应 SHA 的 CI、等待成功、下载普通 artifact、原有完整 returned 门禁、生产 ESP 打包、最终 FAT/ADT/签名/plist/PAC/POST/日志槽位回读、输出绝对路径与 SHA256。轮询间隔 5 秒，CI 完成后不再等助手逐步发命令。固件配对文件在 CI 运行期间准备。

过程日志、每段起止时间与耗时写到 `artifacts/b5q-review15-release/`。完成后自动写交付报告和 porting evidence。最终交付仍为一个 800 MiB/4Kn 的 ESP；不自动生成压缩包或重编固件。认证继续通过环境或已有 token 文件，仅用于 API 请求。

已有本地门禁的输入哈希匹配时直接使用。输入变化或门禁失败会保留首错日志并停止；不删断言。每轮 returned 门禁和最终二进制回读仍须通过，才会标为可交付。

中断后继续同一个 CI：

```bash
python3 scripts/b5q-release.py resume --review review15 --run RUN_ID
```

`resume` 不提交、不推送、不触发新 CI。已下载的相同 run/SHA 产物直接使用；已生成且与生产清单哈希一致的镜像继续回读，不重新生成。不同内容的已有 IMG 拒绝覆盖。

修改经验证的固件配对或增加新的二进制验收标记时，更新 `scripts/b5q-release.json`；它不改变 CI 工作流或任何硬件代码。

流程本地验证命令：

```bash
python3 tests/test_b5q_release.py
python3 scripts/b5q-release.py replay --review review14 --run 45902130941 \
  --ci-dir artifacts/b5q-review14-ci-45902130941 \
  --work-dir artifacts/b5q-release-flow-validation/replay \
  --output artifacts/b5q-release-flow-validation/replay/esp.img
```

`replay` 不联网、不提交、不推送、不改正式交付记录。生产打包元数据写入临时叠加目录，保留原 CI 目录及正式 IMG。验证后删除回放 IMG，保留小型计时和验收记录。若已有同名回放 IMG，先保留其证据并移除该临时 IMG 或选择新路径。

首次使用实际 review14 产物回放：preflight 0.044 秒、固件配对 0.206 秒、完整 returned 门禁 15.736 秒、打包 1.750 秒、最终回读 3.830 秒，总计 21.575 秒。回放复用了已下载产物，下载耗时不在这次计时内；下一次真实发布会单独记录下载及完整端到端时间。

加入恢复和元数据保护后，最终版本再次回放通过，总计24.895秒（returned门禁18.495秒、打包1.904秒、回读4.198秒）。两次回放均执行完整原门禁，临时IMG在验证后删除，正式review14IMG与原CI打包清单保持不变。
