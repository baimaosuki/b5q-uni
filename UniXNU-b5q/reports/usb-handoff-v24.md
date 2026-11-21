# Superseded v24 USB handoff conclusion

USBSTS 0x08 is EINT;0x04 is HSE. The earlier HSE statement was wrong.
The exact HAL allocator uses free CBAR metadata (type0/type2/type1VMIDff), not occupied S2CR or CB.SCTLR reads.
The native QcomDwc3 implementation now uses this allocation rule. Current code/tests and CI state are in runtime-v24.json and porting.toml.
