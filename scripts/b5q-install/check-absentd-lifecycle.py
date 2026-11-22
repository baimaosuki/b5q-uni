#!/usr/bin/env python3
"""Audit five target jobs and execute the target libxpc transaction increment."""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import re
import struct
import sys
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn import arm64_const as regs

ROOT = Path(__file__).resolve().parents[2]


def replay(code, previous):
    u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    u.mem_map(0x184BCE000, 0x1000)
    u.mem_write(0x184BCE5C8, code)
    u.mem_map(0x188060000, 0x30000)  # model imported APIs at their real stubs
    u.mem_map(0x1E2111000, 0x1000)
    u.mem_map(0x200000000, 0x20000)
    calls = []
    state, stop = 0x200001000, 0x200000F00
    u.mem_write(state + 0xA8, bytes([1]))
    u.mem_write(state + 0xAC, struct.pack('<I', previous))
    def reg(name, value=None):
        key = getattr(regs, 'UC_ARM64_REG_' + name.upper())
        if value is not None:
            u.reg_write(key, value)
        return u.reg_read(key)
    def hook(uc, pc, size, _):
        def ret(value=0):
            reg('x0', value)
            reg('pc', reg('lr'))
        if pc == 0x18806CEE0:  # getpid
            ret(123)
        elif pc == 0x188087960:  # kdebug trace
            ret()
        elif pc == 0x188087BA0:  # actual j__proc_set_dirty import stub
            calls.append((reg('w0'), reg('w1')))
            ret()
        else:
            word = int.from_bytes(uc.mem_read(pc, 4), 'little')
            if word in (0xD503237F, 0xD50323FF):  # control-flow-only PAC shim
                reg('pc', pc + 4)
            elif word == 0xD65F0FFF:
                reg('pc', reg('lr'))
            elif 0x188060000 <= pc < 0x188090000:
                raise AssertionError(f'Unmodelled external {pc:#x}')
    u.hook_add(UC_HOOK_CODE, hook)
    reg('x0', state); reg('sp', 0x20001F000); reg('lr', stop)
    u.emu_start(0x184BCE5C8, stop, count=1000)
    assert reg('pc') == stop
    now = struct.unpack('<I', bytes(u.mem_read(state + 0xAC, 4)))[0]
    assert now == previous + 1 and calls == ([(123, 1)] if previous == 0 else [])
    return dict(previous=previous, transaction_count=now, proc_set_dirty_calls=calls)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root', type=Path, required=True)
    p.add_argument('--cache', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    a = p.parse_args()
    data = a.cache.read_bytes()
    assert hashlib.sha256(data).hexdigest() == 'f4aefea64cb86bf2f82a0af1e0f6fde7f56b2ef67eaeba9ff3ae0cdfc1e1c36f'
    sub = a.cache.with_name(a.cache.name + '.01')
    with sub.open('rb') as f:
        assert hashlib.file_digest(f, 'sha256').hexdigest() == 'b954fa0249bb2c9ab5b3d7207bb05f4767bb70d3c675b3cab6a37aafc9c6c890'
        f.seek(0); header = f.read(512)
        assert header[88:104] in data  # source main cache references this exact subcache UUID
        offset, count = struct.unpack_from('<II', header, 16)
        f.seek(offset)
        mappings = [struct.unpack('<3Q2I', f.read(32)) for _ in range(count)]
        mapping, = [m for m in mappings if m[0] <= 0x184BCE5C8 < m[0] + m[1]]
        codeoff = mapping[2] + 0x184BCE5C8 - mapping[0]
        f.seek(codeoff); code = f.read(0x130)
    results = [replay(code, count) for count in (0, 1, 5)]
    patch = (ROOT / 'UniXNU-b5q/patches/tools/b5q-absentd-user-domains.patch').read_text()
    inputs = [('LaunchDaemons', 'com.apple.mobileactivationd'), ('LaunchDaemons', 'com.apple.security.cryptexd'),
              ('LaunchDaemons', 'com.apple.AirPlayXPCHelper'), ('LaunchDaemons', 'com.apple.rtcreportingd'),
              ('LaunchAgents', 'com.apple.talagent')]
    evidence = []
    for domain, label in inputs:
        path = Path('System/Library') / domain / (label + '.plist')
        body = (a.root / path).read_bytes(); job = plistlib.loads(body)
        binary = job.get('Program', job.get('ProgramArguments', [None])[0])
        services = [name for name, enabled in job['MachServices'].items() if enabled is True]
        literal = '{' + json.dumps(label) + ', ' + json.dumps(binary) + ', {' + ', '.join(map(json.dumps, services)) + ', NULL}}'
        assert literal in patch, f'Static service map differs from source {label}'
        assert job['EnablePressuredExit'] is True and job.get('EnableTransactions') in (True, None)
        assert not any('sandbox' in key.lower() for key in job), 'Unexpected launchd-imposed sandbox'
        evidence.append(dict(path=str(path), sha256=hashlib.sha256(body).hexdigest(), label=label,
            binary=binary, binary_sha256=hashlib.sha256((a.root / binary.lstrip('/')).read_bytes()).hexdigest(),
            KeepAlive=job.get('KeepAlive'), MachServices=job['MachServices'],
            EnableTransactions=job.get('EnableTransactions'), effective_transactions=True,
            effective_transactions_evidence='native launchd normalization 0x100005a18..0x100005b74', EnablePressuredExit=True,
            launchd_enforced_sandbox_keys=[], replacement_runtime_plist_reads=0,
            replacement_profile='No app-sandbox entitlement or explicit sandbox installation'))
    assert '+    xpc_transaction_begin();' in patch
    assert '+    const struct board_job *job = resolve_job(label, argc, argv);' in patch
    assert not re.search(r'^\+.*CF(Read|PropertyList)', patch, re.M)
    assert 'endpointsecurityd' not in (ROOT / 'UniXNU-b5q/package/B5qBootPolicy.c').read_text()
    report = dict(passed=True, jobs=evidence, native_transaction_replay=results,
        cache_main_sha256=hashlib.sha256(data).hexdigest(), cache_sub01_sha256='b954fa0249bb2c9ab5b3d7207bb05f4767bb70d3c675b3cab6a37aafc9c6c890',
        code_address='0x184bce5c8', code_file_offset=hex(codeoff), instruction_bytes=code.hex(),
        native_zero_to_one_marks_process_dirty_at='0x184bce6b8 -> j__proc_set_dirty at 0x188087ba0',
        substituted_APIs='getpid, kdebug, proc_set_dirty; PAC prologue/return control-flow shims',
        guaranteed_scope='Fix pressured idle-exit eligibility, known-job no-label early exit, and sandbox-sensitive plist reads; no immunity to arbitrary SIGKILL/OOM',
        v32_seven_individual_exit_reasons='not recorded by v32; seven instances are not a complete per-instance exit trace',
        hardware_verified=False)
    a.report.write_text(json.dumps(report, indent=2) + '\n')
    print('PASS: 5 exact target jobs and service maps; 3 native libxpc dirty-transition cases; no runtime plist dependence')


if __name__ == '__main__':
    main()
