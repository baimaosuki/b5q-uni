#!/usr/bin/env python3
"""Inspect the built b5q ramdisk for recovery, ADB, shell and ESP tools."""

import argparse
import gzip
import hashlib
import json
import struct
import subprocess
from pathlib import Path


def read_newc(data):
    entries = []
    offset = 0
    while offset < len(data):
        header = data[offset:offset + 110]
        if header[:6] not in (b'070701', b'070702'):
            raise ValueError(f'Unsupported CPIO header at offset {offset}')
        fields = [int(header[6 + i * 8:14 + i * 8], 16) for i in range(13)]
        mode, size, name_size = fields[1], fields[6], fields[11]
        if name_size < 1 or offset + 110 + name_size > len(data):
            raise ValueError('Invalid CPIO name length')
        name = data[offset + 110:offset + 110 + name_size - 1].decode()
        start = (offset + 110 + name_size + 3) & ~3
        if start + size > len(data):
            raise ValueError('CPIO entry exceeds ramdisk size')
        if name == 'TRAILER!!!':
            return entries
        entry = {'path': name.removeprefix('./'), 'mode': oct(mode), 'bytes': size}
        if mode & 0o170000 == 0o120000:
            entry['symlink'] = data[start:start + size].decode()
        entries.append(entry)
        offset = (start + size + 3) & ~3
    raise ValueError('CPIO trailer missing')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', required=True, type=Path)
    parser.add_argument('--lz4', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    data = args.image.read_bytes()
    if data[:8] != b'ANDROID!':
        raise ValueError('Expected Android boot image')
    kernel_size, _, ramdisk_size = struct.unpack_from('<3I', data, 8)
    page_size = struct.unpack_from('<I', data, 36)[0]
    offset = page_size + (kernel_size + page_size - 1) // page_size * page_size
    compressed = data[offset:offset + ramdisk_size]
    if compressed[:2] == b'\x1f\x8b':
        raw = gzip.decompress(compressed)
    else:
        raw = subprocess.run([str(args.lz4.resolve()), '-d', '-c'], input=compressed,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout
    entries = read_newc(raw)
    paths = [entry['path'] for entry in entries]
    required = ['recovery', 'adbd', 'sh', 'toybox', 'mkfs.fat', 'fsck.fat', 'sgdisk']
    tools = {name: [path for path in paths if Path(path).name == name
                   and ('bin' in Path(path).parts or 'sbin' in Path(path).parts)]
             for name in required}
    missing = [name for name, locations in tools.items() if not locations]
    if missing:
        raise ValueError('Recovery ramdisk missing expected tools: ' + ', '.join(missing))
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'ramdisk-inventory.json').write_text(json.dumps(entries, indent=2) + '\n')
    report = {'entries': len(entries), 'cpio_bytes': len(raw), 'tools': tools,
              'ramdisk_sha256': hashlib.sha256(compressed).hexdigest(),
              'hardware_runtime_test': 'not performed'}
    (args.output / 'ramdisk-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
