# b5q macOS 27.3 首版启动候选包

最终 CI `44494359247` 完成 SUCCESS，构建源码 `5b19c2aab0127326f2b95aa5a3cd803de26a6312`。真实内核完整链接，无未解析符号，XnuPrelink 完整映射，无 missing/stubbed；全部产物已取回本地。

产物目录：`/home/baimao/zflip5/artifacts/b5q-macos-27.3-firstboot-v1`。完整安装与输入说明见目录内 `刷入与输入指南.md`。

完整压缩包：`/home/baimao/zflip5/artifacts/b5q-macos-27.3-firstboot-v1.tar.zst`，13796848064 字节，SHA256 `2f38dd69de0ecda756264be774fc2ac4094d302cd87b0153e5f6b0a1dc9f9c81`。压缩流测试及33个文件的逐项归档哈希核验均在本地 PASS。

| 文件 | 字节 | SHA256 |
| --- | ---: | --- |
| `boot-b5q-firstboot.tar` | 56043520 | `b7def1b3f5305acc334dcea8cbe31c0d3128c90f6545b5a80dfb7834a852a39d` |
| `boot.img` | 56041472 | `329339d426ea5e6573e482001e241878a85ba0a02503a9fe5558daa97373295f` |
| `kernel.macho` | 142983168 | `12515af5f800b1f2ce0b6cd80446c4c3da6b8ed09124341197db10666bf975df` |
| `macosroot.img` | 17603493888 | `35b1c581c7074c626b4b3750af93901a988425e42671f1aaeafd7fd6e13de199` |
| `payload.img` | 268435456 | `821366a9a768e8afa2c13089c01e15b20f4dc52ccb33e7d9b771c5207f6ebf13` |

`package.manifest.json` 保存精确构建来源、最终输出哈希和首版验证范围；`SHA256SUMS` 覆盖部署目录全部普通文件。`boot-b5q-firstboot.tar` 仅包含同一 boot.img；macosroot 必须单独写入。

```bash
cd /home/baimao/zflip5/artifacts/b5q-macos-27.3-firstboot-v1
sha256sum -c SHA256SUMS
python3 install-firstboot.py --check
python3 install-firstboot.py --all
```

脚本在 TWRP 下检查 b5q 身份及用户 GPT 中 boot/macosroot 的字节起点、容量。先写系统根并读回验证，再写 boot 并读回验证。只更新内核负载时用 `--boot`，只写根镜像用 `--root`。装完由用户在 TWRP 重启 System。

已有菜单路径：把 `esp-files/EFI/UniXNU/` 的 Payloads、Drivers、unixnu.toml 放到菜单实际读取的 FAT 卷。部署内核位于 Payloads，包含诊断探针，其哈希与包根目录的原始链接内核不同。新 boot.img 已带同组 RAM FAT，无需为此修改 ESP。

最新用户要求：新增检查本地执行。`scripts/b5q-install/pre-ci.py` 已通过14项检查，CI中新增模板/设备记录/工具验证及补充输出完整性关卡已移除，构建后的二进制下载回本地再检查。本次调整用 skip-ci 推送，保留所有已完成和排队的构建。

这是首个硬件启动候选包，硬件启动和 macOS 桌面尚未验证。B5qUfs 依赖固件保留已上电/空闲链路及专用可用 SMMU 上下文，没有冷 PHY/复位初始化；Data 为 RAM，重启丢失。Metal、输入和持久 Data 不能由完整编译推导为可用。本次未连接或刷写手机。
