# b5q hardware source comparison

Sources: Mu b5q reference DTB/DSC/MemoryMapLib; TWRP prebuilt SoC DTBs; previously built local UEFI-menu boot image. Values below come from b5q sources, not sheng.

| Item | b5q evidence | Comparison / interpretation |
| --- | --- | --- |
| DRAM physical banks | `/ddr-regions`: low `0x80000000 + 0x80000000`, high `0x880000000 + 0x180000000` | 2 GiB + 6 GiB physical-bank description; not all allocatable |
| Linux memory | Eight `/memory/reg` tuples, preserved verbatim in JSON | Fragment list differs from the physical-bank description; do not flatten holes |
| HYP | `0x80000000 + 0x00a00000` | Reference FDT and Mu memory map agree |
| CPUSYS VM | `0x80a00000 + 0x00400000` | Reference FDT and Mu memory map agree |
| UH guest | `0xb1000000 + 0x03000000` | Present in b5q FDT; lies inside Mu aggregate Kernel reservation |
| UH heap | `0xb0200000 + 0x00040000` | Present in b5q FDT; lies inside Mu aggregate Kernel reservation |
| TZ stats | `0x82700000 + 0x00100000` | Reference FDT and Mu memory map agree |
| QTEE | `0xd8300000 + 0x00500000` | Reference FDT and Mu memory map agree |
| TZApps | Mu map `0xd8800000 + 0x07400000` | FDT has Trust UI and further secure subregions; retain full detailed inventory |
| RKP | No separately named interval in supplied reference | Do not equate UH with an invented standalone RKP range |
| Main panel | Mu DSC `1080 x 2640`, `32 bpp` | Custom DisplayDxe selected, not SimpleFbDxe |
| Display reservation | `0xb8000000 + 0x02b00000` | Agrees with reference splash region; active scanout pointer/stride not directly encoded |
| Stride | Width times four gives `4320` bytes only as a packed candidate | No measured/GOP stride evidence in these files |
| GICD / GICR | `0x17100000 / 0x17180000` | Agree with Kailua shared definitions |
| UFS / ICE / HWKM | `0x01d84000 / 0x01d88000 / 0x01d90000` | Reference DT, IRQ SPI 265; metadata only, no access |
| GPU OPP | bin 0 max `719000000 Hz`, bin 1 max `680000000 Hz` | Selecting the 719 MHz bin still requires b5q speed-bin and power vote evidence |
| TWRP DTBs | Four Kalama/KalamaP SoC DTBs | Base SoC inputs; no applied b5q board overlay or local phone extraction claim |
| Local boot.img | Previous menu image contains the same Mu reference DTB | Same-source derivative, not an independent hardware confirmation |

The full source hashes, DT offsets and ranges are in `hardware-baseline.json`. Full bootargs and device identity fields are not exported.
