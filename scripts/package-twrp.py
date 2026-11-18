#!/usr/bin/env python3
"""Check b5q recovery image structure, then create a recovery-only Odin tar."""

import argparse
import hashlib
import json
import shutil
import struct
import tarfile
from pathlib import Path

PARTITION_SIZE = 109576192


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    data = args.image.read_bytes()
    if len(data) > PARTITION_SIZE:
        raise SystemExit('Image exceeds the b5q recovery partition size in BoardConfig.mk')
    if len(data) < 1660 or data[:8] != b'ANDROID!':
        raise SystemExit('Expected an Android boot image')
    kernel_size, _, ramdisk_size = struct.unpack_from('<3I', data, 8)
    page_size, version = struct.unpack_from('<2I', data, 36)
    if version != 2 or page_size != 4096:
        raise SystemExit(f'Unexpected boot header: version={version}, page_size={page_size}')
    if not kernel_size or not ramdisk_size:
        raise SystemExit('Kernel and recovery ramdisk must be present')
    dtbo_size, dtbo_offset, header_size = struct.unpack_from('<IQI', data, 1632)
    dtb_size, dtb_address = struct.unpack_from('<IQ', data, 1648)
    if header_size != 1660 or not dtbo_size or not dtb_size:
        raise SystemExit('Missing expected recovery DTBO or DTB')
    padded = lambda size: (size + page_size - 1) // page_size * page_size
    ramdisk_offset = page_size + padded(kernel_size)
    if dtbo_offset + dtbo_size > len(data):
        raise SystemExit('Recovery DTBO exceeds the image size')
    dtb_offset = dtbo_offset + padded(dtbo_size)
    if dtb_offset + dtb_size > len(data):
        raise SystemExit('DTB exceeds the image size')
    if data[page_size:page_size + 2] != b'\x1f\x8b':
        raise SystemExit('Expected the supplied gzip kernel')
    if data[dtb_offset:dtb_offset + 4] != b'\xd0\x0d\xfe\xed':
        raise SystemExit('DTB magic mismatch')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    image = output / 'recovery.img'
    if image.resolve() != args.image.resolve():
        shutil.copy2(args.image, image)
    archive = output / 'twrp-b5q-odin.tar'
    with tarfile.open(archive, 'w', format=tarfile.USTAR_FORMAT) as tar:
        tar.add(image, arcname='recovery.img')
    with tarfile.open(archive) as tar:
        if tar.getnames() != ['recovery.img']:
            raise SystemExit('Unexpected Odin archive contents')
        with tar.extractfile('recovery.img') as member:
            if hashlib.sha256(member.read()).digest() != hashlib.sha256(data).digest():
                raise SystemExit('Odin archive image checksum mismatch')
    report = {
        'device': 'b5q', 'product_model': 'SM-F731B',
        'image_bytes': len(data), 'partition_limit_bytes': PARTITION_SIZE,
        'boot_header_version': version, 'page_size': page_size,
        'kernel_bytes': kernel_size, 'ramdisk_bytes': ramdisk_size,
        'ramdisk_offset': ramdisk_offset,
        'recovery_dtbo_bytes': dtbo_size, 'recovery_dtbo_offset': dtbo_offset,
        'dtb_bytes': dtb_size, 'dtb_offset': dtb_offset, 'dtb_load_address': dtb_address,
        'avb_footer_present': data[-64:-60] == b'AVBf',
        'hardware_boot_test': 'not performed',
        'note': 'Upstream Samsung digest patch modifies AVB metadata; this check does not verify the AVB signature.',
        'sha256': {},
    }
    for path in [image, archive]:
        report['sha256'][path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    (output / 'SHA256SUMS').write_text(''.join(f'{digest}  {name}\n' for name, digest in report['sha256'].items()))
    (output / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
