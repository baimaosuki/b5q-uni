#!/usr/bin/env python3
"""Execute the existing ARM64 launch-constraint switch up to native policy.

Only the boot-argument parser is mocked. With the switch off, execution stops
before native MAC policy calls; with it on, the compiled function must return.
This is a local function test, not a boot or hardware test.
"""
import argparse
import hashlib
import json
import struct
import sys
from pathlib import Path
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm64_const import *

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / 'sources/UniXNU/kits/XnuPrelink'))
from kc_image import Image
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('kernel', type=Path)
p.add_argument('--out', required=True, type=Path)
a = p.parse_args()
raw = a.kernel.read_bytes()
outer = Image(raw)
im = Image(raw, outer.entries['com.apple.kernel'][1]) if outer.entries else outer
names = {n: v for v, ns in im.symbols().items() for n in ns}
start = names['_mac_proc_check_launch_constraints']
md = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
ins = list(md.disasm(im.read(start, 128), start))
call = next(i for i in ins if i.mnemonic == 'bl')
assert int(call.op_str[1:], 16) == names['_PE_parse_boot_argn']
branch = next(i for i in ins if i.mnemonic == 'b.ne')
native_policy = branch.address + 4
uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
lo = min(s['va'] for s in im.segments if s['size']) & ~4095
hi = (max(s['va'] + s['size'] for s in im.segments if s['size']) + 4095) & ~4095
uc.mem_map(lo, hi - lo)
for s in im.segments:
    if s['filesize']:
        uc.mem_write(s['va'], raw[s['fileoff']:s['fileoff'] + s['filesize']])
fixture = 0xfffffff030000000
uc.mem_map(fixture, 0x10000)
stop = fixture
present, value, observed = 0, 0, None

def hook(e, pc, size, context):
    global observed
    if pc == names['_PE_parse_boot_argn']:
        assert bytes(e.mem_read(e.reg_read(UC_ARM64_REG_X0), 6)) == b'no-lc\0'
        assert e.reg_read(UC_ARM64_REG_X2) == 4
        if present:
            e.mem_write(e.reg_read(UC_ARM64_REG_X1), struct.pack('<I', value))
        e.reg_write(UC_ARM64_REG_X0, present)
        e.reg_write(UC_ARM64_REG_PC, e.reg_read(UC_ARM64_REG_X30))
        return
    if pc == native_policy:
        observed = 'original_policy'
        e.emu_stop()
        return
    i = next(md.disasm(bytes(e.mem_read(pc, 4)), pc))
    if i.mnemonic in ('pacibsp', 'paciasp', 'autibsp', 'autiasp'):
        e.reg_write(UC_ARM64_REG_PC, pc + 4)
    elif i.mnemonic in ('retab', 'retaa'):
        e.reg_write(UC_ARM64_REG_PC, e.reg_read(UC_ARM64_REG_X30))

uc.hook_add(UC_HOOK_CODE, hook)
cases = []
for present, value in [(0, 0), (1, 0), (1, 1), (1, 2)]:
    observed = None
    uc.reg_write(UC_ARM64_REG_SP, fixture + 0xf000)
    uc.reg_write(UC_ARM64_REG_X30, stop)
    uc.emu_start(start, stop, count=1000)
    if value:
        assert uc.reg_read(UC_ARM64_REG_PC) == stop and uc.reg_read(UC_ARM64_REG_X0) == 0
        observed = 'return_0'
    else:
        assert observed == 'original_policy'
    cases.append(dict(argument_present=bool(present), value=value, outcome=observed))
assert '__ZN6ArmCpu5probeEP9IOServicePi' in names
result = dict(passed=True, kernel_sha256=hashlib.sha256(raw).hexdigest(),
              actual_compiled_launch_constraint_gate=True, cases=cases,
              ArmCpu_probe_present=True, verifier_compiles_kernel=False,
              boot_parser_mocked=True, PAuth_not_tested=True, hardware_tested=False)
a.out.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
