# v17 log and v18 ADT update

Input XNU2LOG.BIN SHA2569837740e58bfd184371cc29560ce3993c2658768402b3bae71616dd18d927c07 validates both slots. Latest slot1/seq90 has108331bytes/2123lines, overwritten0, capture-lock loss42bytes. No kernel panic occurs in the committed snapshot; bytes after the last commit are unknown.

Observed: Ethernet state1 atline190, en0 scheduled961, local TimeSync port1012, IOKit quiet1065, display powerstate1 at1075, all5existing fixups applied. Twelve framebuffer copies at1419..2110 move11404800bytes each (968..7954us). Completed copies do not establish actual visible pixels. SecurityAgent starts5times. WindowServer110/357/403/425/443 dies withSIGABRT at1677/1847/1945/2032/2114; sessions restart.

The precise b5q userland assertion/backtrace is absent. Same-build NABU captured CompositorSW->CGLayerKitFetch->CARenderOGLRender->prepare_layers_roi with unfinished backdrop invalidations. This supports the proposed lifecycle repair, not proof of an identical b5q stack or a unique remaining blocker.

Add2native backdrop-completion rules and the requested SafeAperture/Magnify/managedTCC optional startup choices. Backdrop calls the original clip/finalizer only when needed and keeps the ROI assertion. URL queries take original unavailable/default paths. The AppKit managed-Mac launch-disclosure feature takes its native disabled branch; TCC authorization decisions/tccd are unchanged. The3optional UI rules come from reference waits, not b5q wait stacks.

All10original sites/grouped patched4KiB page hashes match the exact26C5035r caches already independently bound to b5q IPSW compressed forks in runtime-v15.json.196original-instruction cases pass (8backdrop/99SafeAperture/57Magnify/32managedTCC). Allocator/locks/shape/ObjC/CF/IPC/PAC boundary models are explicit; pixels and authorization are not emulated.

Local official ADT generation changes only /chosen/text-fixups and fresh random-seed; menu title becomesv18. Every other ADT property, boot arguments and ESP member matchesv17. Exact deployed kernel201ab9f5026b4433c19efb9731210b030f8a53e02028edb868e14cd7227fb3f9,2GiBRAMData,bootshim/trust and firmware are preserved. No CI,compile,Data regeneration,QEMU or phone access. Full FAT member roundtrip,4Kn geometry,mirroredFAT/2051contiguous journal clusters/noaliases/tokenCRC,13APFS checksums and shim signatures/trust pass. New v18IMG bytes/hash are in runtime-v18.json. Its physical result remains pending.
