#!/usr/bin/env python3
"""Compare the real observer's callback PAC with its unchanged core callers."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_ARM

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'UniXNU-b5q/scripts'))
from b5q_abi import macho, object_symbols


def scan(path):
    raw = path.read_bytes()
    symbols = object_symbols(raw)
    instructions, relocations, signed = [], {}, {}
    for segment in macho(raw)['segments']:
        for sec in segment['sections']:
            off, count = struct.unpack_from('<II', raw, sec['command_offset'] + 56)
            for i in range(count):
                at, bits = struct.unpack_from('<II', raw, off + i * 8)
                if not bits >> 27 & 1:
                    continue
                target = symbols[bits & 0xffffff][0]
                relocations[sec['va'] + at] = target
                if bits >> 28 == 11:
                    word = struct.unpack_from('<Q', raw, sec['fileoff'] + at)[0]
                    signed.setdefault(target, []).append(dict(site=hex(sec['va'] + at),
                        key=word >> 49 & 3, diversity=word >> 32 & 0xffff, address_diversity=word >> 48 & 1))
            if sec['name'] == '__text':
                decoder = Cs(CS_ARCH_ARM64, CS_MODE_ARM)
                decoder.skipdata = True
                instructions += list(decoder.disasm(raw[sec['fileoff']:sec['fileoff'] + sec['size']], sec['va']))
    calls = []
    for i, ins in enumerate(instructions):
        if ins.mnemonic == 'pacia' and i >= 2:
            previous = instructions[i - 1]
            target = relocations.get(instructions[i - 2].address)
            if target and previous.mnemonic == 'mov' and previous.op_str.startswith('x17, #'):
                signed.setdefault(target, []).append(dict(site=hex(ins.address), key=0,
                    diversity=int(previous.op_str.split('#')[1], 0), address_diversity=0))
        if ins.mnemonic == 'blraa' and i:
            previous = instructions[i - 1]
            modifier = ins.op_str.split(', ')[1]
            if previous.mnemonic == 'mov' and previous.op_str.startswith(modifier + ', #'):
                calls.append(dict(site=ins.address, diversity=int(previous.op_str.split('#')[1], 0)))
    return dict(sha256=hashlib.sha256(raw).hexdigest(), symbols=symbols,
                signed=signed, calls=calls, instructions=instructions)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--object', type=Path, required=True)
    p.add_argument('--core-objects', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    producer = scan(a.object)
    core = scan(a.core_objects / 'mac_process.o')
    contracts = []
    for callback, caller, expected in [('_created', '_mac_cred_label_associate_fork', 0x73d8),
                                        ('_exited', '_mac_proc_notify_exit', 0x2abe)]:
        sites = producer['signed'][callback]
        assert sites and all(s['key'] == 0 and s['diversity'] == expected and not s['address_diversity'] for s in sites)
        start = next(v for n, v, k in core['symbols'] if n == caller and k & 0xe)
        end = min(v for _, v, k in core['symbols'] if k & 0xe and v > start)
        calls = [c for c in core['calls'] if start <= c['site'] < end and c['diversity'] == expected]
        assert calls, (callback, caller)
        contracts.append(dict(callback=callback, caller=caller, diversity=hex(expected), signed=sites, calls=calls))
    startup = scan(a.core_objects / 'startup.o')
    sites = producer['signed']['_b5q_proc_top_init']
    assert sites and all(s['key'] == 0 and not s['address_diversity'] for s in sites)
    expected = sites[0]['diversity']
    matches = [c for c in startup['calls'] if c['diversity'] == expected]
    assert matches, ('startup callback PAC', sites)
    contracts.append(dict(callback='_b5q_proc_top_init', caller='kernel_startup_initialize_upto', signed=sites, calls=matches))
    # No address-space MMIO, mappings or hardware controller imports are part of
    # this CPU-only observer; inspect decoded instructions plus external imports.
    imports = {n for n, _, k in producer['symbols'] if k == 1}
    assert not any('ioremap' in n.lower() or 'IOMemory' in n or 'smmu' in n.lower() for n in imports)
    assert not any('0x15000000' in i.op_str for i in producer['instructions'])
    a.out.write_text(json.dumps(dict(passed=True, contracts=contracts,
        sha256=dict(observer=producer['sha256'], mac_process=core['sha256'], startup=startup['sha256']),
        imports=sorted(imports), apps_smmu_MMIO_references=0, hardware_PAC_execution_tested=False), indent=2) + '\n')
    print('PASS: observer fork/exit/startup PAC matches unchanged core; no hardware MMIO imports/references')


if __name__ == '__main__':
    main()
