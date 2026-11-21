#!/usr/bin/env python3
"""Inspect the real QcomDwc3 object for the removed EL1 SMMU path."""
import argparse, hashlib, json, struct, sys
from pathlib import Path
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / 'UniXNU-b5q/scripts'))
from b5q_abi import macho, object_symbols

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--object', required=True, type=Path)
p.add_argument('--out', required=True, type=Path)
a = p.parse_args()
raw = a.object.read_bytes()
symbols = object_symbols(raw)
assert not any('gSmmu' in n or 'B5qUsbSmmu' in n for n, _, _ in symbols)
assert b'smmu=skipped-el2-xpu' in raw
assert b'controller-DMA=deferred' in raw
assert b'SID=40 slot=' not in raw

# Record materialized addresses, including MOV/MOVK split immediates; a raw
# byte search alone misses ARM64 instructions that assemble an address.
materialized = []
instructions = 0
md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
for cmd, at, _ in macho(raw)['commands']:
    if cmd != 0x19:
        continue
    nsects = struct.unpack_from('<I', raw, at + 64)[0]
    for i in range(nsects):
        sec = at + 72 + i * 80
        name = raw[sec:sec + 16].split(b'\0')[0]
        if name != b'__text':
            continue
        addr, size, offset = struct.unpack_from('<QQI', raw, sec + 32)
        values = {}
        for ins in md.disasm(raw[offset:offset + size], addr):
            instructions += 1
            op = ins.op_str.replace(' ', '').split(',')
            if ins.mnemonic in ('mov', 'movz', 'movn', 'movk') and len(op) >= 2 and op[1].startswith('#'):
                reg = 'x' + op[0][1:]
                imm = int(op[1][1:], 0)
                shift = int(op[2].removeprefix('lsl#'), 0) if len(op) > 2 else 0
                if ins.mnemonic == 'movk':
                    value = (values.get(reg, 0) & ~(0xffff << shift)) | (imm << shift)
                else:
                    value = (~(imm << shift) if ins.mnemonic == 'movn' else imm << shift)
                values[reg] = value & ((1 << (32 if op[0].startswith('w') else 64)) - 1)
                value = values[reg]
                assert not 0x15000000 <= value < 0x150d0000, (hex(ins.address), ins.mnemonic, ins.op_str)
                if value >= 0x100000:
                    materialized.append(hex(value))
            elif ins.mnemonic in ('ret', 'retab', 'bl', 'blr', 'blraa') or ins.mnemonic.startswith('b.'):
                values.clear()

result = {'passed': True, 'object_sha256': hashlib.sha256(raw).hexdigest(),
          'instructions_inspected': instructions, 'apps_smmu_addresses_materialized': [],
          'removed_allocator_symbols_absent': True, 'hardware_only_DMA_gate_present': True,
          'scope': 'Actual object instructions plus removed map/allocator symbols; production zero-MMIO regression is separate'}
a.out.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
