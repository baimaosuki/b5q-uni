#!/usr/bin/env python3
"""User-run installer for the exact b5q first-boot package; never repartitions."""
import argparse
import hashlib
import json
import re
import shlex
import subprocess
from pathlib import Path

PARTITIONS = {
    'macosroot': ('macosroot.img', 49692663 * 4096, 51539607552),
    'boot': ('boot.img', 152448 * 4096, 100663296),
}


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 << 20), b''):
            result.update(block)
    return result.hexdigest()


def partition_probe(name):
    # Both the block name and the sysfs paths come from this fixed allowlist.
    if name not in PARTITIONS:
        raise ValueError('unsupported partition')
    return f'''set -e
p=/dev/block/by-name/{name}
test -b "$p"
b=$(basename "$(readlink -f "$p")")
test -r /sys/class/block/"$b"/partition
printf '%s\\n' "$b"
cat /sys/class/block/"$b"/start
cat /sys/class/block/"$b"/size
blockdev --getsize64 "$p"
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--serial', help='ADB serial when more than one device is connected')
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--check', action='store_true', help='verify local files and device layout only (default)')
    action.add_argument('--root', action='store_true', help='write macosroot.img and verify readback')
    action.add_argument('--boot', action='store_true', help='write boot.img and verify readback')
    action.add_argument('--all', action='store_true', help='write and verify macosroot, then boot')
    args = parser.parse_args()
    directory = args.directory.resolve()
    manifest = json.loads((directory / 'package.manifest.json').read_text())
    if manifest['os_profile'] != 'macos-27.3-26C5035r':
        raise SystemExit('Unexpected OS profile')
    status = manifest['build_status']
    if not status['flash_candidate_ready'] or not status['root_read_only'] or not status['data_volatile']:
        raise SystemExit('Package is not the expected read-only-root/RAM-Data candidate')
    chosen = ['macosroot', 'boot'] if args.all or args.check or not (args.root or args.boot) else ['macosroot' if args.root else 'boot']
    adb = ['adb'] + (['-s', args.serial] if args.serial else [])

    def shell(text):
        return subprocess.check_output(adb + ['shell', '-T', text], text=True).strip()

    if shell('id -u') != '0' or not shell('getprop ro.twrp.version'):
        raise SystemExit('Run with the phone already in TWRP with root ADB')
    device = shell('getprop ro.product.device').lower()
    model = shell('getprop ro.product.model').upper()
    if not (device.startswith('b5q') or model.startswith('SM-F731')):
        raise SystemExit('Connected device is not identified as b5q/SM-F731')
    # Validate every selected image and partition before the first write.
    for name in chosen:
        filename, expected_start, expected_size = PARTITIONS[name]
        image = directory / filename
        record = manifest['outputs'][filename]
        if image.stat().st_size != record['bytes'] or record['bytes'] > expected_size:
            raise SystemExit(f'{filename}: size mismatch')
        print(f'Checking {filename} SHA256...', flush=True)
        if digest(image) != record['sha256']:
            raise SystemExit(f'{filename}: SHA256 mismatch')
        rows = shell(partition_probe(name)).splitlines()
        if len(rows) != 4 or not re.fullmatch(r'[A-Za-z0-9_.-]+', rows[0]):
            raise SystemExit(f'{name}: invalid block geometry response')
        # Linux sysfs start/size are always expressed in 512-byte sectors.
        if int(rows[1]) * 512 != expected_start or int(rows[2]) * 512 != expected_size or int(rows[3]) != expected_size:
            raise SystemExit(f'{name}: device layout differs from supplied GPT')
        print(f'PASS {name}: offset={expected_start} capacity={expected_size}', flush=True)
    if not (args.root or args.boot or args.all):
        print('CHECK PASS; no writes performed')
        return
    for name in chosen:
        filename, _, _ = PARTITIONS[name]
        record = manifest['outputs'][filename]
        image = directory / filename
        print(f'Writing {filename} -> {name} ({record["bytes"]} bytes)...', flush=True)
        with image.open('rb') as source:
            subprocess.run(adb + ['shell', '-T', f'dd of=/dev/block/by-name/{name} bs=4194304 conv=fsync'], stdin=source, check=True)
        print(f'Verifying {name} readback...', flush=True)
        expected = record['sha256']
        # Read exactly the image extent, not the unused tail of the partition.
        text = shell(f'set -o pipefail; head -c {record["bytes"]} /dev/block/by-name/{name} | sha256sum')
        if not text or text.split()[0] != expected:
            raise SystemExit(f'{name}: readback SHA256 mismatch; installation stopped')
        print(f'PASS {name}: {expected}', flush=True)
    print('INSTALL PASS; reboot manually after reviewing the guide')


if __name__ == '__main__':
    main()
