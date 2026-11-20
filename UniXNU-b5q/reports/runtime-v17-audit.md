# v17 source audit

Latest actual device input remains the v14 capture SHA256 d29670dcadf21fb21c90fc1706ef8632e9ca742c07c1f3e113bda7ac3ded8934. No v15/v16 runtime log is present. Sheng main is still c8f92b208068eeaa4cd2b0f592671f04ee70076e; preserve the current local-clock and software compositor configuration. This audit does not invent a new physical WindowServer blocker from old logs.

Journal metadata/slot reads previously stopped on a single valid transient SCSI response. Production I/O/read replay reproduces old failure and new recovery, including another command replacing host.status at mutex release. Only reads retry (three attempts, 50ms bound); writes/SYNC retain existing behavior and ESP-slot-only gates. Invalid transport, short data and permanent errors fail immediately.

Root media dispatch previously made 256 commands for a 1MiB read. Production dispatch now batches up to 128KiB (eight commands), authenticating every 4KiB block before exposing it. Three devices use 124KiB additional scratch each. The real VerifiedRoot SHA256 test covers 35 partial/aligned reads, corrupted blocks with exact verified prefix, second-command failure, final sector and direction/bounds rejection. Short descriptor copies now return the actual 23 copied bytes rather than zero. The command reduction is a host measurement, not a hardware throughput result.

Only these native read fixes require compilation. Data, firmware, ADT, boot arguments, signatures and logger write authorization are unchanged. Run local pre-CI before one combined target build, then verify the returned native binary and single 800MiB/4Kn ESP image. No QEMU or phone access.
