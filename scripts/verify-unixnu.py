#!/usr/bin/env python3
"""Verify delivered boot, compressed firmware, embedded modules, FAT and Odin tar."""
import argparse
import hashlib
import json
import lzma
from pathlib import Path
import re
import struct
import subprocess
import tarfile
import uuid
import zlib

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sections(data):
    position = 0
    while position + 4 <= len(data):
        size = int.from_bytes(data[position:position + 3], 'little')
        kind = data[position + 3]
        header = 4
        if size == 0xffffff:
            size = struct.unpack_from('<I', data, position + 4)[0]
            header = 8
        require(header <= size <= len(data) - position, 'invalid firmware section')
        yield kind, data[position + header:position + size]
        position = (position + size + 3) & ~3


def files(data):
    require(data[40:44] == b'_FVH', 'firmware volume signature missing')
    position = (struct.unpack_from('<H', data, 48)[0] + 7) & ~7
    while position + 24 <= len(data) and data[position:position + 24] != b'\xff' * 24:
        header = 24
        size = int.from_bytes(data[position + 20:position + 23], 'little')
        if size == 0xffffff:
            size = struct.unpack_from('<Q', data, position + 24)[0]
            header = 32
        require(header <= size <= len(data) - position, 'invalid firmware file size')
        yield str(uuid.UUID(bytes_le=data[position:position + 16])), data[position + 18], data[position + header:position + size]
        position = (position + size + 7) & ~7


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'artifacts/unixnu-b5q')
    args = parser.parse_args()
    out = args.out
    fd = (out / 'SILICIUM_UEFI.fd').read_bytes()
    require(len(fd) == 0x300000, 'b5q firmware must be 3 MiB')
    outer = {guid: (kind, payload) for guid, kind, payload in files(fd)}
    _, guided_file = outer['9e21fd93-9c72-4c15-8c4b-e77f1db2d792']
    kind, guided = next(sections(guided_file))
    require(kind == 2, 'expected GUID-defined compressed FV')
    require(str(uuid.UUID(bytes_le=guided[:16])) == 'ee4e5898-3914-4259-9d6e-dc7bd79403cf', 'expected LZMA FV')
    offset = struct.unpack_from('<H', guided, 16)[0]
    decoded = lzma.decompress(guided[offset - 4:])
    fv = next(payload for kind, payload in sections(decoded) if kind == 0x17)
    inner = {guid: (kind, payload) for guid, kind, payload in files(fv)}
    tree = ROOT / 'sources/UniXNU'
    paths = {
        'UniXNU': tree / 'package/UniXNUPkg/Application/UniXNU/UniXNU.inf',
        'UniXNUDxe': tree / 'package/UniXNUPkg/Driver/UniXNUDxe/UniXNUDxe.inf',
        'UniXNURamDiskDxe': tree / 'package/UniXNUPkg/Driver/UniXNURamDiskDxe/UniXNURamDiskDxe.inf',
        'DarwinBoot': tree / 'drivers/DarwinBoot/DarwinBootPkg/Driver/DarwinBoot.inf',
    }
    modules = {}
    for name, inf in paths.items():
        guid = re.search(r'FILE_GUID\s*=\s*([\w-]+)', inf.read_text()).group(1).lower()
        _, body = inner[guid]
        pe = next(payload for kind, payload in sections(body) if kind == 0x10)
        require(pe == (out / f'{name}.efi').read_bytes(), f'{name}: embedded binary differs')
        pe_offset = struct.unpack_from('<I', pe, 60)[0]
        require(pe[pe_offset:pe_offset + 4] == b'PE\0\0', f'{name}: not PE')
        require(struct.unpack_from('<H', pe, pe_offset + 4)[0] == 0xaa64, f'{name}: not AArch64')
        modules[name] = {'guid': guid, 'machine': 'AArch64', 'embedded_matches_efi': True}
    for inf in ['MdeModulePkg/Universal/Disk/DiskIoDxe/DiskIoDxe.inf', 'FatPkg/EnhancedFatDxe/Fat.inf']:
        text = (ROOT / 'sources/Mu-Silicium/Mu_Basecore' / inf).read_text()
        guid = re.search(r'FILE_GUID\s*=\s*([\w-]+)', text).group(1).lower()
        require(guid in inner, f'filesystem driver missing: {inf}')
    boot = (out / 'boot.img').read_bytes()
    require(boot[:8] == b'ANDROID!' and struct.unpack_from('<I', boot, 40)[0] == 4, 'not Android boot v4')
    kernel_size, ramdisk_size = struct.unpack_from('<II', boot, 8)
    codec = zlib.decompressobj(16 + zlib.MAX_WBITS)
    combined = codec.decompress(boot[4096:4096 + kernel_size])
    require(codec.eof and codec.unused_data == (out / 'b5q.dtb').read_bytes(), 'kernel DTB mismatch')
    shim_size = len(combined) - len(fd)
    require(combined[shim_size:] == fd, 'packaged firmware mismatch')
    require(combined[56:60] == b'ARM\x64', 'ARM64 shim signature missing')
    require(struct.unpack_from('<QQ', combined, 8) == (0xa7100000, len(combined)), 'ARM64 shim geometry mismatch')
    ramdisk_start = 4096 + ((kernel_size + 4095) & ~4095)
    require(boot[ramdisk_start:ramdisk_start + ramdisk_size] == (out / 'menu-payload.fat').read_bytes(), 'ramdisk mismatch')
    fat_files = {}
    for path in sorted((out / 'esp').rglob('*')):
        if path.is_file():
            rel = path.relative_to(out / 'esp').as_posix()
            readback = subprocess.check_output(['mtype', '-i', str(out / 'menu-payload.fat'), '::/' + rel])
            require(readback == path.read_bytes(), f'FAT file mismatch: {rel}')
            fat_files[rel] = hashlib.sha256(readback).hexdigest()
    with tarfile.open(out / 'unixnu-b5q-odin.tar') as tar:
        require(tar.getnames() == ['boot.img'], 'Odin tar must contain only boot.img')
        require(tar.extractfile('boot.img').read() == boot, 'Odin boot.img mismatch')
    with tarfile.open(out / 'unixnu-b5q-esp.tar') as tar:
        require(set(tar.getnames()) == set(fat_files), 'ESP archive inventory mismatch')
        for rel, expected in fat_files.items():
            require(hashlib.sha256(tar.extractfile(rel).read()).hexdigest() == expected, f'ESP archive mismatch: {rel}')
    report = {'result': 'PASS', 'hardware_tested': False, 'firmware_bytes': len(fd),
              'decompressed_fv_bytes': len(fv), 'embedded_modules': modules, 'fat_files': fat_files,
              'boot_header_version': 4, 'boot_bytes': len(boot), 'shim_bytes': shim_size,
              'checks': ['LZMA FV extraction', 'embedded PE equality and AArch64', 'DiskIo and FAT drivers',
                         'boot shim geometry', 'gzip firmware and appended DTB', 'FAT ramdisk equality',
                         'FAT file readback', 'Odin and ESP tar readback']}
    (out / 'verification-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
