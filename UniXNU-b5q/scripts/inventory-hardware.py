#!/usr/bin/env python3
"""Read b5q hardware properties from local FDTs; never access a device or disk partition."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

MAGIC = b'\xd0\x0d\xfe\xed'


def parse_fdt(data):
    fields = struct.unpack_from('>10I', data)
    if fields[0] != 0xd00dfeed or fields[1] > len(data):
        raise ValueError('invalid FDT header')
    _, total, offset, strings, reserve, version, last, cpu, strings_size, struct_size = fields
    names = data[strings:strings + strings_size]
    nodes = {}
    stack = []
    position = offset
    while position < offset + struct_size:
        token = struct.unpack_from('>I', data, position)[0]
        position += 4
        if token == 1:
            end = data.index(b'\0', position)
            stack.append(data[position:end].decode())
            path = '/' + '/'.join(stack[1:])
            nodes[path] = {}
            position = (end + 4) & ~3
        elif token == 2:
            stack.pop()
        elif token == 3:
            length, name_offset = struct.unpack_from('>II', data, position)
            position += 8
            end = names.index(b'\0', name_offset)
            name = names[name_offset:end].decode()
            nodes['/' + '/'.join(stack[1:])][name] = data[position:position + length]
            position = (position + length + 3) & ~3
        elif token == 4:
            pass
        elif token == 9:
            break
        else:
            raise ValueError(f'unknown FDT token {token}')
    reservations = []
    while reserve + 16 <= total:
        base, size = struct.unpack_from('>QQ', data, reserve)
        reserve += 16
        if base == size == 0:
            break
        reservations.append(region(base, size))
    return nodes, reservations


def cells(value):
    return list(struct.unpack('>' + 'I' * (len(value) // 4), value)) if value else []


def text(value):
    return value.rstrip(b'\0').decode(errors='replace')


def integer(value, default=0):
    return int.from_bytes(value, 'big') if value else default


def region(base, size):
    return {'base': hex(base), 'size': hex(size), 'end_exclusive': hex(base + size)}


def reg(nodes, path):
    parent = nodes.get(path.rsplit('/', 1)[0] or '/', {})
    ac = integer(parent.get('#address-cells'), 2)
    sc = integer(parent.get('#size-cells'), 1)
    value = nodes[path].get('reg', b'')
    width = (ac + sc) * 4
    if not width or len(value) % width:
        return []
    return [region(integer(value[i:i + ac * 4]), integer(value[i + ac * 4:i + width])) for i in range(0, len(value), width)]


def inventory(data):
    nodes, reservations = parse_fdt(data)
    result = {'model': text(nodes['/'].get('model', b'')), 'memory': [], 'reserved_memory': [],
              'controllers': [], 'fdt_memreserve': reservations, 'framebuffer_nodes': [], 'operating_points': []}
    for path, props in nodes.items():
        compat = text(props.get('compatible', b''))
        if props.get('device_type') == b'memory\0':
            result['memory'] += reg(nodes, path)
        if path.startswith('/reserved-memory/') and path.count('/') == 2:
            result['reserved_memory'].append({'path': path, 'regions': reg(nodes, path),
                'status': text(props.get('status', b'okay')), 'no_map': 'no-map' in props,
                'dynamic_size': hex(integer(props['size'])) if 'size' in props else None})
        if 'arm,gic-v3' in compat or 'ufshc' in compat or 'adreno' in compat and 'iommu' not in path:
            result['controllers'].append({'path': path, 'compatible': compat.split('\0'),
                'reg': reg(nodes, path), 'reg_names': text(props.get('reg-names', b'')).split('\0'),
                'interrupts': cells(props.get('interrupts', b'')), 'status': text(props.get('status', b'okay'))})
        if compat == 'simple-framebuffer':
            result['framebuffer_nodes'].append({'path': path, 'reg': reg(nodes, path),
                **{name: integer(props[name]) for name in ['width','height','stride'] if name in props},
                'format': text(props.get('format', b''))})
        selected = {k: cells(v) for k, v in props.items() if k in {'opp-hz','qcom,gpu-freq','clock-frequency','qcom,initial-freq'}}
        if selected:
            result['operating_points'].append({'path': path, 'properties': selected})
    result['secure_regions'] = [r for r in result['reserved_memory'] if re.search('hyp|cpusys|uh_|rkp|qtee|tz|trust_ui|kaslr', r['path'], re.I)]
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    root = args.workspace
    inputs = {
        'mu_b5q_reference': ('sources/Mu-Silicium/Resources/DTBs/b5q.dtb', 'Project-Silicium reference DTB; not a local phone extraction'),
        'twrp_b5q_prebuilt': ('sources/twrp-b5q/prebuilt/dtb', 'TWRP repository prebuilt; not a local phone extraction'),
        'existing_menu_boot': ('artifacts/unixnu-b5q/boot.img', 'Earlier local UEFI-menu build; derived from Mu b5q DTB'),
    }
    report = {'board': 'b5q', 'soc': 'SM8550-AC', 'phone_extracted_input_present': False, 'inputs': {}}
    for name, (rel, origin) in inputs.items():
        path = root / rel
        if not path.is_file():
            continue
        data = path.read_bytes()
        item = {'path': rel, 'provenance': origin, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'trees': []}
        start = 0
        while True:
            offset = data.find(MAGIC, start)
            if offset < 0:
                break
            start = offset + 4
            try:
                size = struct.unpack_from('>I', data, offset + 4)[0]
                if not 40 <= size <= len(data) - offset:
                    continue
                blob = data[offset:offset + size]
                hardware = inventory(blob)
                item['trees'].append({'offset': offset, 'bytes': size, 'sha256': hashlib.sha256(blob).hexdigest(), **hardware})
                start = offset + size
            except (ValueError, struct.error, IndexError):
                continue
        report['inputs'][name] = item
    mu = root / 'sources/Mu-Silicium'
    memory_file = mu / 'Platforms/Samsung/b5qPkg/Library/MemoryMapLib/MemoryMapLib.c'
    mappings = [{'name': n, **region(int(b, 16), int(s, 16))} for n,b,s in re.findall(r'\{"([^"]+)"\s*,\s*(0x[0-9A-Fa-f]+)\s*,\s*(0x[0-9A-Fa-f]+)', memory_file.read_text())]
    report['mu_memory_map'] = {'path': str(memory_file.relative_to(root)), 'sha256': hashlib.sha256(memory_file.read_bytes()).hexdigest(), 'regions': mappings}
    dsc_file = mu / 'Platforms/Samsung/b5qPkg/b5q.dsc'
    dsc = dsc_file.read_text()
    width = int(re.search(r'PcdFrameBufferWidth\|(\d+)', dsc).group(1))
    height = int(re.search(r'PcdFrameBufferHeight\|(\d+)', dsc).group(1))
    bpp = int(re.search(r'PcdFrameBufferColorDepth\|(\d+)', dsc).group(1))
    display = next(m for m in mappings if m['name'] == 'Display Reserved')
    report['display'] = {'width': width, 'height': height, 'bits_per_pixel': bpp,
        'reserved_base': display['base'], 'reserved_size': display['size'],
        'scanout_address': 'unknown; reservation base is not an observed active scanout pointer',
        'stride_bytes': 'unknown; requires Samsung scanout/GOP evidence',
        'packed_stride_candidate': width * (bpp // 8), 'packed_stride_candidate_is_verified': False,
        'mu_uses_custom_display_driver': 'USE_CUSTOM_DISPLAY_DRIVER      = 1' in dsc,
        'simple_framebuffer_node_present': bool(report['inputs']['mu_b5q_reference']['trees'][0]['framebuffer_nodes'])}
    report['rkp'] = {'status': 'not separately named in the reference FDT; no invented RKP range',
                     'uh_regions_are_preserved_separately': True}
    target = root / 'UniXNU-b5q/reports/hardware-baseline.json'
    target.write_text(json.dumps(report, indent=2) + '\n')
    print(f'Wrote {target}')
    print('Reference memory tuples:', len(report['inputs']['mu_b5q_reference']['trees'][0]['memory']))
    print('TWRP embedded FDTs:', len(report['inputs'].get('twrp_b5q_prebuilt', {}).get('trees', [])))
    print('Display:', json.dumps(report['display']))


if __name__ == '__main__':
    main()
