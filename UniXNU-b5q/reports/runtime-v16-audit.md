# v16 current-source audit

Latest available device capture is v14, SHA256d29670dcadf21fb21c90fc1706ef8632e9ca742c07c1f3e113bda7ac3ded8934. It reaches IOKit quiet with no ring loss. No v15 hardware log is available. The audit preserves the v15 en0/TimeSync and five qualified software compositor rules rather than claiming their real-device outcome.

Three concrete source defects are fixed together. B5qEthernet starts the original network controller, which joins its PM tree, then used to return false after later media/property/interface failures without calling the original stop. Actual-start failure injection reproduces the remaining PM attachment; all ten failure cases and the normal stop now balance allocations and PM. Required properties must succeed before publishing the interface.

readLba previously aborted a root read on the first standards-valid BUSY/TASK SET FULL/UNIT ATTENTION/NOT READY response. The existing UFS sense predicate now drives at most three idempotent read attempts with ten milliseconds between them, outside host.lock. No writes are retried or widened; malformed responses, DMA/transport failures, short reads and illegal requests still fail immediately and block verification remains mandatory.

Finally, readinessCommand copied global host.status after command released its lock. A concurrent legal journal request can replace that global response. command now snapshots optional completion under the same lock as response parsing; both readiness and the new read retry path use it. A production command/read harness deterministically overwrites the shared status at unlock and confirms the original UNIT ATTENTION stays intact. This is a source race regression, not a claim that v14 experienced that race.

Host tests compile real production functions under ASan/UBSan; target arm64e Ethernet compile, all400vtable diversities and135family imports remain valid. No changed DTS, memory map, hardware power/GPIO, signature policies, root/ESP bounds, journal format, firmware or Data seed. One source-correct kernel CI will carry this batch; no QEMU or phone access. CI/delivery results and input hashes live in runtime-v16-audit.json.
