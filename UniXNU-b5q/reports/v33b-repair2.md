# v33b repair2 — desktop regression and input/power corrections

Status: LOCAL_VERIFIED_PENDING_CI_RETURNED_IMAGE. No final image and no phone access.

0. Requirement lock: GPU ADT preservation, no lid/cover display, bounded Bluetooth reset transient, WiFi physical training audit/diagnostics, USB Device power-path diagnostics. Final native/byte acceptance pending; no DONE or flashing claim.
1. Input BIN SHA256 09ea8203ed63805d638840365a23312af883a5225c97385c17d013cf2201e199. Actual prior CI payload contains all3 GPU firmware properties and expected hashes, deliveredESP contains none. Cause is local ADT regeneration from bare board, not skipped CI stage. Evidence artifacts/b5q-v33b-repair2-work/GPU-ADT-regression.json.
2. Production packager restores exactly3 SHA-checked properties from originalpayload before generating persistent/RAM ADTs, then rechecks allADTs. Both returned-payload and finalimage gates enforce them. No Samsung blobs inGit. Lid worker,GPIO107 reads,featurebit1,PMclamshell notifications,backlight override and DP-lid coupling removed. Only innerDSI0+externalDP remain.
3. Bluetooth shared radio_enable already waits55ms after BT_EN; originalSamsungbtpower.c also waits50ms. Add postvote50ms guard and20ms beforeHCI. Startup discards staleRX and tolerates one precommandline-error within50ms; repeated/late/in-command/FIFOerrors remainfatal. No SMMU/DMA. WiFi115PHY writes exactlymatchoriginalDT; existingPERST100ms+postrelease1ms matchesLinux. Preserve those timings, record actualDBI728/72c,PHY214,PARF/GCC andWLAN/PERSTelapsed; no siliconL0claim. USBDeviceadds family-start/cable/desired-power/callback logs; doesnotforceuninitializedDMA.
4. ASan/UBSan positive/negative tests and actualarm64e checks PASS,22sourceboundgroups including retainedP0-P5 regressions;actualCI/returnedimage pending. GPU/Mesa,APFScontainer and unchangedXNUcore/firmware inputs reused withidentitychecks.
5. CI/actualADT/normalWB/PAC/APFS/menu/finaltwoimagereadbacks pending.
6. No flashing commands before finalgates.
7. Hardware qualification remains HOST_VERIFIED_PENDING_HARDWARE.
