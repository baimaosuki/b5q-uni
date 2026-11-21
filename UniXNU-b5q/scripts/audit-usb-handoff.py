#!/usr/bin/env python3
"""Audit saved b5q FDT and firmware files without accessing hardware."""
import argparse
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'UniXNU/scripts'))
from unixnu.devicetree import read_fdt
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path,
                        default=ROOT / 'UniXNU-b5q/reports/usb-handoff-v24.json')
    args = parser.parse_args()
    work = ROOT / 'artifacts/b5q-runtime-v24-work'
    fdt = ROOT / 'b5q-runtime.fdt'
    firmware = ROOT / 'uefi-b5q/Binaries/b5q/QcomPkg/Drivers'
    hal = firmware / 'HALIOMMUDxe/HALIOMMUDxe.efi'
    usb = firmware / 'UsbConfigDxe/UsbConfigDxe.efi'
    sdk = work / 'firmware-source/BOOT.MXF.2.5.1-HALIOMMU.h'
    assert digest(hal) == 'a6020ff87c4526baf9f8cb39870e618691a83cf5ecb8ae4cd1e9e1d42ed9c2ef'
    assert digest(sdk) == '69cceda4ab807a5eb31db13019eb8db7f1e89a158971de5df6e9bef6fe352d22'
    nodes = list(read_fdt(fdt.read_bytes()).walk())
    smmu = next(n for n in nodes if n.name == 'apps-smmu@15000000')
    dwc3 = next(n for n in nodes if n.name == 'dwc3@a600000')
    assert dwc3.cells('iommus')[1:] == [0x40, 0]
    assert smmu.cells('qcom,handoff-smrs') == [0x1c00, 2]

    # These RVAs are restricted to the exact hash above. Verify the actual
    # protocol-init return and CBAR helper instead of assuming an old ABI.
    blob = hal.read_bytes()
    machine = struct.unpack_from('<H', blob, struct.unpack_from('<I', blob, 0x3c)[0] + 4)[0]
    assert machine == 0xaa64
    disasm = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
    init = [(i.mnemonic, i.op_str) for i in disasm.disasm(blob[0x1700:0x1720], 0x1700)]
    assert ('adrp', 'x8, #0xd000') in init and ('add', 'x8, x8, #0xd0') in init
    body = sdk.read_text().split('typedef struct HAL_IOMMU_fptable_s {', 1)[1].split('}', 1)[0]
    names = re.findall(r'\b(\w+_func)\s*;', body)
    assert len(names) == 15
    addresses = struct.unpack_from('<15Q', blob, 0xd0d0)
    assert addresses == (0x1970, 0x1a20, 0x1ba0, 0x2870, 0x2db0,
                         0x3130, 0x31c0, 0x3260, 0x3020, 0x3280,
                         0x4840, 0x4990, 0x44f0, 0x4770, 0x2cd0)
    cbar = [(i.mnemonic, i.op_str) for i in disasm.disasm(blob[0x36c0:0x3704], 0x36c0)]
    assert ('lsl', 'w2, w8, #2') in cbar and ('mov', 'w1, #0x1000') in cbar
    allocator = [(i.mnemonic, i.op_str) for i in disasm.disasm(blob[0x21a0:0x2308], 0x21a0)]
    assert ('bl', '#0x36c0') in allocator and ('b', '#0x21ec') in allocator
    assert b'Failed to create HAL IOMMU domain' in usb.read_bytes()
    assert b'Failed to attach USB Arid' in usb.read_bytes()

    report = {
        'scope': 'Static audit of saved files; no device, MMIO, SCM or firmware execution',
        'inputs': {str(p.relative_to(ROOT)): digest(p) for p in [hal, usb, sdk, fdt]},
        'saved_runtime_FDT': {
            'USB_SID': '0x40',
            'display_handoff_SMR': {'id': '0x1c00', 'mask': '0x2'},
            'apps_smmu_property_names': sorted(smmu.properties),
            'USB_owned_slot': 'unknown',
            'USB_owned_context_bank': 'unknown',
            'protected_context_bank_bitmap': 'unknown',
        },
        'local_firmware_protocol': {
            'init_RVA': '0x1700',
            'function_table_RVA': '0xd0d0',
            'documented_table': [{'field': n, 'RVA': hex(v)} for n, v in zip(names, addresses)],
            'documented_bank_ownership_query': False,
            'USB_domain_create_attach_strings_present': True,
            'bank_allocator_RVA': '0x21a0',
            'CBAR_read_helper_RVA': '0x36c0',
            'allocation': 'Runtime loop reads GR1 CBAR[index]; no fixed USB bank is established',
            'actual_loaded_phone_firmware_identity_verified': False,
            'private_domain_handle_or_layout_exported_to_XNU': False,
        },
        'Linux_source': {
            'handoff': 'arm_smmu_handoff_cbs reads S2CR.CBNDX and reserves that bit in context_map',
            'allocation': 'arm_smmu_alloc_context_bank uses context_map, not SCTLR.M alone',
            'qsmmuv500_cfg_probe': 'Clears sACR CACHE_LOCK; does not grant bank ownership',
            'wait_safe_toggle': 'Examined call is conditional on qcom,sdm845-smmu-500; not a USB bank allocator',
        },
        'conclusion': 'HAL compatible free CBAR metadata supports native USB allocation without occupied S2CR or bank SCTLR reads',
        'CBAR_allocator_rule': 'type=(CBAR>>16)&3,vmid=CBAR&255; free if type0/type2/type1+VMID255; allocatedtype1VMID0 is excluded',
        'native_implementation': 'package/B5qUsbSmmu.h; validates free SMR/nonzero slot, rejects existing USB SID, excludes last bypass bank',
        'S2CR0_or_occupied_SCTLR_access_required': False,
        'other_device_bank_numbers_used': False,
        'new_apps_smmu_MMIO': False,
        'CI_dispatched': False,
        'v24_image_created': False,
    }
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    print('Static b5q audit complete: exact HAL CBAR metadata supports native USB free-bank allocation')


if __name__ == '__main__':
    main()
