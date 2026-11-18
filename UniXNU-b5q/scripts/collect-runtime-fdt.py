#!/usr/bin/env python3
"""Extract only hardware memory evidence; never read partitions or emit chosen/IDs."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile


def command(argv):
    return subprocess.run(argv, check=True, capture_output=True, timeout=30).stdout


def inspect(path):
    def get(node, prop, kind='x'):
        try:
            text = command(['fdtget', '-t', kind, str(path), node, prop]).decode().strip()
            return text if kind == 's' else [int(x, 16) for x in text.split()]
        except subprocess.CalledProcessError:
            return None

    def children(node):
        try:
            return command(['fdtget', '-l', str(path), node]).decode().split()
        except subprocess.CalledProcessError:
            return []

    def cells(node, prop, fallback):
        data = get(node, prop)
        return data[0] if data and len(data) == 1 else fallback

    def ranges(node, parent):
        address = cells(parent, '#address-cells', 2)
        size = cells(parent, '#size-cells', 1)
        raw = get(node, 'reg')
        if raw is None:
            return []
        if not (1 <= address <= 2 and 1 <= size <= 2) or len(raw) % (address+size):
            raise ValueError('Unsupported or malformed memory reg cells: '+node)
        def number(words):
            value = 0
            for word in words:
                value = (value << 32) | word
            return value
        found = []
        for at in range(0, len(raw), address+size):
            base, length = number(raw[at:at+address]), number(raw[at+address:at+address+size])
            if base+length > 1 << 64:
                raise ValueError('Memory range overflow')
            found.append(dict(base=hex(base), size=hex(length), nonzero=bool(length)))
        return found

    report = dict(scope='Whitelisted FDT memory facts only; no active EFI/GOP or DMA ownership claim',
                  source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                  memory=[], reserved_memory=[], runtime_gop='unknown',
                  runtime_efi_map='unknown', ufs_access_performed=False)
    for child in children('/'):
        node = '/'+child
        if child == 'memory' or child.startswith('memory@') or get(node, 'device_type', 's') == 'memory':
            report['memory'].append(dict(node=node, ranges=ranges(node, '/')))
    for child in children('/reserved-memory'):
        node = '/reserved-memory/'+child
        report['reserved_memory'].append(dict(node=node, ranges=ranges(node, '/reserved-memory'),
            status=get(node,'status','s') or 'unspecified', no_map=get(node,'no-map') is not None,
            dynamic_size_cells=get(node,'size'), alignment_cells=get(node,'alignment'),
            alloc_ranges_cells=get(node,'alloc-ranges')))
    report['memory_has_nonzero_bank'] = any(r['nonzero'] for n in report['memory'] for r in n['ranges'])
    # memreserve entries are independent of the /reserved-memory node.
    raw = path.read_bytes()
    import struct
    if len(raw) < 40 or struct.unpack_from('>I',raw)[0] != 0xd00dfeed:
        raise ValueError('Invalid FDT header')
    total, _, _, reserve = struct.unpack_from('>4I',raw,4)
    if total > len(raw) or reserve % 8 or reserve > total:
        raise ValueError('Invalid FDT reservation map')
    report['memreserve'] = []
    for at in range(reserve,total-15,16):
        base,length=struct.unpack_from('>2Q',raw,at)
        if not base and not length:break
        if base+length > 1<<64:raise ValueError('Reservation overflow')
        report['memreserve'].append(dict(base=hex(base),size=hex(length)))
    else:
        raise ValueError('Unterminated FDT reservation map')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fdt',type=Path,help='Offline input, never labelled as phone capture')
    parser.add_argument('--adb',default='adb',help='Used only without --fdt')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.fdt:
        report=inspect(args.fdt)
        report['source_kind']='offline-input-not-phone-capture'
    else:
        # Refuse unrelated attached devices before reading their firmware FDT.
        device=command([args.adb,'shell','getprop','ro.product.device']).decode().strip()
        model=command([args.adb,'shell','getprop','ro.product.model']).decode().strip()
        if not device.startswith('b5q') or not model.upper().startswith('SM-F731'):
            raise SystemExit('Connected recovery is not b5q/SM-F731; no FDT was captured.')
        # No identifiers are requested, and no raw FDT is persisted in outputs.
        data=command([args.adb,'exec-out','cat','/sys/firmware/fdt'])
        if len(data)>16*1024*1024:
            raise ValueError('FDT exceeds bounded input size')
        with tempfile.TemporaryDirectory(prefix='b5q-fdt-') as tmp:
            path=Path(tmp)/'input.dtb'
            path.write_bytes(data)
            report=inspect(path)
        report['source_kind']='adb-sys-firmware-fdt'
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print('Saved whitelisted hardware memory evidence:',args.output)
    print('Nonzero memory bank:',report['memory_has_nonzero_bank'])


if __name__ == '__main__':
    main()
