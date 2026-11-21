#!/usr/bin/env python3
"""Package the b5q firmware memory reservation fix as a boot-only update."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import tomllib
from types import SimpleNamespace
import zlib

ROOT = Path(__file__).resolve().parents[2]


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def record(path):
    return {'bytes': path.stat().st_size, 'sha256': sha256(path)}


def unpack(path):
    image = path.read_bytes()
    if image[:8] != b'ANDROID!' or struct.unpack_from('<I', image, 40)[0] != 4:
        raise ValueError('Expected the deployed Android v4 boot image')
    kernel_size, ramdisk_size = struct.unpack_from('<II', image, 8)
    kernel = image[4096:4096 + kernel_size]
    decoder = zlib.decompressobj(31)
    combined = decoder.decompress(kernel)
    if not decoder.eof or not decoder.unused_data:
        raise ValueError('Expected gzip firmware followed by a Samsung DTB')
    ramdisk_start = 4096 + (kernel_size + 4095) // 4096 * 4096
    ramdisk = image[ramdisk_start:ramdisk_start + ramdisk_size]
    if len(ramdisk) != ramdisk_size:
        raise ValueError('Truncated boot ramdisk')
    return combined, decoder.unused_data, ramdisk


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--firmware', required=True, type=Path)
    parser.add_argument('--baseline', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    firmware = args.firmware.resolve()
    baseline = args.baseline.resolve()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=False)
    original, dtb, ramdisk = unpack(baseline)
    if hashlib.sha256(original).hexdigest() != '96e108cf9f0b1e868cf8a5fbd900a852762edd33e60be95c6b086f7207ae933d':
        raise ValueError('Baseline does not match the deployed firmware transport')
    os.environ['PATH'] = '/usr/lib/llvm-17/bin:' + os.environ['PATH']
    tree = ROOT / 'sources/UniXNU'
    uefi = ROOT / 'sources/Mu-Silicium'
    sys.path.insert(0, str(tree / 'scripts'))
    from unixnu import bootimg
    config = tomllib.loads((ROOT / 'configs/unixnu-b5q.toml').read_text())
    target = output / 'boot.img'
    with tempfile.TemporaryDirectory(prefix='b5q-boot-inputs-') as temporary:
        inputs = Path(temporary)
        (inputs / 'b5q.dtb').write_bytes(dtb)
        (inputs / 'bootstrap.fat').write_bytes(ramdisk)
        ctx = SimpleNamespace(tree=tree, work=inputs, logs=inputs / 'logs', board=config)
        bootimg.build(ctx, uefi, firmware, inputs / 'b5q.dtb', inputs / 'bootstrap.fat', target)
    # Mu's mkbootimg adds a zero-filled GKI signature slot by default. Match
    # the existing Samsung transport only when the entire slot is empty.
    candidate = bytearray(target.read_bytes())
    signature_size = struct.unpack_from('<I', candidate, 1580)[0]
    if signature_size:
        kernel_size, ramdisk_size = struct.unpack_from('<II', candidate, 8)
        signed_end = 4096 + (kernel_size + 4095) // 4096 * 4096
        signed_end += (ramdisk_size + 4095) // 4096 * 4096
        if signature_size != 4096 or candidate[signed_end:] != bytes(4096):
            raise ValueError('Unexpected populated boot signature')
        struct.pack_into('<I', candidate, 1580, 0)
        target.write_bytes(candidate[:signed_end])
        boot_record = output / 'boot.json'
        details = json.loads(boot_record.read_text())
        details.update(image_bytes=target.stat().st_size, image_sha256=sha256(target),
                       empty_gki_signature_slot_removed=True)
        boot_record.write_text(json.dumps(details, indent=2) + '\n')
    new_image, new_dtb, new_ramdisk = unpack(target)
    shim_size = len(original) - firmware.stat().st_size
    assert new_image[:shim_size] == original[:shim_size]
    assert new_image[shim_size:] == firmware.read_bytes()
    assert new_dtb == dtb and new_ramdisk == ramdisk
    assert struct.unpack_from('<I', target.read_bytes(), 1580)[0] == 0
    assert target.stat().st_size < 100663296
    previous = json.loads((ROOT / 'artifacts/b5q-esp-adt-v7/package.manifest.json').read_text())
    status = previous['build_status'].copy()
    status.update(delivery_version='boot-memory-v8', esp_install_required=False,
                  scope='b5q live high-memory reservation correction')
    verification = {
        'baseline_boot_sha256': sha256(baseline),
        'firmware_sha256': sha256(firmware),
        'original_firmware_dtb_sha256': hashlib.sha256(dtb).hexdigest(),
        'bootstrap_sha256': hashlib.sha256(ramdisk).hexdigest(),
        'shim_bytes': shim_size,
        'shim_matches_deployed': True,
        'dtb_matches_deployed': True,
        'bare_fat_bootstrap_matches_deployed': True,
    }
    manifest = {
        'device': 'b5q',
        'os_profile': 'macos-27.3-26C5035r',
        'build_status': status,
        'outputs': {'boot.img': record(target)},
        'verification': verification,
        'runtime_memory': json.loads((ROOT / 'UniXNU-b5q/reports/runtime-memory-v8.json').read_text()),
    }
    (output / 'package.manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    shutil.copyfile(ROOT / 'scripts/b5q-install/install-firstboot.py', output / 'install-firstboot.py')
    print(json.dumps({'directory': str(output), 'outputs': manifest['outputs'], 'verification': verification}, indent=2))


if __name__ == '__main__':
    main()
