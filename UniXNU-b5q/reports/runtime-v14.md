# b5q v14 runtime configuration repair

v13 log records cpu1..cpu7 unmatched in IOKit busy and unixnu-absentd killed by enforcing Launch Constraints. Enable the already-linked ArmCpu secondary path with smp=1, armcpu-spi-ipi=1 and armcpu-self-ipi=1, and the existing launch-constraint policy with no-lc=1. These are the pinned sheng27.3 SoC/runtime switches, with CPU affinity, GIC addresses/stride and PSCI independently checked against the saved b5q runtime FDT; no Xiaomi board values copied. Absence of declared IPI consumers does not prove secure-world ownership or physical multicore startup.

Host ASan/UBSan harness runs the actual ArmCpu probe: seven secondary nubs are rejected without smp and accepted with it; malformed/unsupported inputs still fail. Actual completed v13 ARM64 mac_proc_check_launch_constraints runs locally to confirm absent/zero arguments preserve original policy and nonzero returns at the compiled gate. Boot parser is a fixture and PAuth/hardware are not tested. The official ADT generator preserves all eight verified CPU affinities and SMC conduit. No new kernel patch or diagnostic probe.

Payload-only CI reuses v13 kernel from run44688079841 and byte-identical v11-derived 2GiB RAM Data. Local staging test executes the production reuse script and verifies both hashes. The official payload/runtime recipe rebuilds the signed boot-shim addon, owner trust pairing, deployment seal, ADT and menu. Root remains read-only, Data volatile and log writes restricted. A new kernel compile, firmware compile, Data generation and QEMU are unnecessary.

Evidence, exact input hashes and CI/delivery outcome are recorded in runtime-v14.json. CPU startup, IOKit quiet and desktop output remain physical observations, not conclusions from host build success.
