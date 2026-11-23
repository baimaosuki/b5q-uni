#!/usr/bin/env python3
"""User-run installer for the exact b5q first-boot package; never repartitions."""
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

PARTITIONS = {
    'macosroot': ('macosroot.img', 49692663 * 4096, 51539607552),
    'esp': ('esp.img', 3162880 * 4096, 838860800),
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


def esp_sector_size(image):
    """Read the FAT BPB; a filesystem cluster is not a device sector."""
    with image.open('rb') as stream:
        bpb = stream.read(512)
    if len(bpb) != 512 or bpb[510:512] != b'\x55\xaa' or bpb[82:90] != b'FAT32   ':
        raise SystemExit('esp.img: expected a FAT32 boot sector')
    size = int.from_bytes(bpb[11:13], 'little')
    if size != 4096 or bpb[13] != 1:
        raise SystemExit('esp.img: b5q physical ESP requires 4096 bytes per sector and one sector per cluster')
    return size


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument('--serial', help='ADB serial when more than one device is connected')
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--check', action='store_true', help='verify local files and device layout only (default)')
    action.add_argument('--root', action='store_true', help='write macosroot.img and verify readback')
    action.add_argument('--boot', action='store_true', help='write boot.img and verify readback')
    action.add_argument('--esp', action='store_true', help='replace the dedicated ESP with esp.img and verify readback')
    action.add_argument('--repair', action='store_true', help='update ESP then boot; keep the already written macosroot')
    action.add_argument('--all', action='store_true', help='write and verify macosroot, ESP, then boot')
    args = parser.parse_args()
    directory = args.directory.resolve()
    manifest = json.loads((directory / 'package.manifest.json').read_text())
    if manifest['os_profile'] != 'macos-27.3-26C5035r':
        raise SystemExit('Unexpected OS profile')
    status = manifest['build_status']
    persistent = status.get('data_persistent') is True
    if not status['flash_candidate_ready'] or not status['root_read_only']:
        raise SystemExit('Package is not a validated read-only-root candidate')
    if persistent:
        # First-install Data has its own GPT/window-locked tool. This package
        # can only update ESP, and can never select root, boot or bulk repair.
        if status.get('data_volatile') is not False or set(manifest['outputs']) != {'esp.img'}:
            raise SystemExit('Persistent Data package must contain only the ESP deployment')
        if args.root or args.boot or args.repair or args.all:
            raise SystemExit('Persistent Data update permits --check or --esp only')
    elif not status.get('data_volatile'):
        raise SystemExit('Package has no recognized Data mode')
    writing = args.root or args.boot or args.esp or args.repair or args.all
    if args.repair:
        chosen = ['esp', 'boot']
    elif args.all:
        chosen = ['macosroot', 'esp', 'boot']
    elif not writing:
        chosen = [name for name, (file, _, _) in PARTITIONS.items() if file in manifest['outputs']]
    else:
        chosen = ['macosroot' if args.root else 'esp' if args.esp else 'boot']
    for name in chosen:
        if PARTITIONS[name][0] not in manifest['outputs']:
            raise SystemExit(f'{name}: image is not included in this package; choose --esp for the ESP-only update')
    if not chosen:
        raise SystemExit('No supported partition images in this package')
    if 'esp' in chosen and not status.get('esp_install_required'):
        raise SystemExit('This installer requires a package manifest with explicit ESP delivery')
    esp_bpb_size = esp_sector_size(directory / 'esp.img') if 'esp' in chosen else None
    adb = ['adb'] + (['-s', args.serial] if args.serial else [])

    def shell(text):
        return subprocess.check_output(adb + ['shell', '-T', text], text=True).strip()

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
    if shell('id -u') != '0' or not shell('getprop ro.twrp.version'):
        raise SystemExit('Run with the phone already in TWRP with root ADB')
    device = shell('getprop ro.product.device').lower()
    model = shell('getprop ro.product.model').upper()
    if not (device.startswith('b5q') or model.startswith('SM-F731')):
        raise SystemExit('Connected device is not identified as b5q/SM-F731')
    for name in chosen:
        filename, expected_start, expected_size = PARTITIONS[name]
        rows = shell(partition_probe(name)).splitlines()
        if len(rows) != 4 or not re.fullmatch(r'[A-Za-z0-9_.-]+', rows[0]):
            raise SystemExit(f'{name}: invalid block geometry response')
        # Linux sysfs start/size are always expressed in 512-byte sectors.
        if int(rows[1]) * 512 != expected_start or int(rows[2]) * 512 != expected_size or int(rows[3]) != expected_size:
            raise SystemExit(f'{name}: device layout differs from supplied GPT')
        print(f'PASS {name}: offset={expected_start} capacity={expected_size}', flush=True)
    if 'esp' in chosen:
        device_sector = int(shell('blockdev --getss /dev/block/by-name/esp'))
        if device_sector != esp_bpb_size:
            raise SystemExit(f'esp: device logical block {device_sector} differs from FAT sector {esp_bpb_size}')
        print(f'PASS esp: device and FAT logical sectors both {device_sector} bytes', flush=True)
    if not writing:
        print('CHECK PASS; no writes performed')
        return
    # Only unmount the explicitly selected dedicated ESP before replacing it.
    # Do not attempt to unmount or access any protected Samsung partition.
    if 'esp' in chosen:
        shell('''set -e
real=$(readlink -f /dev/block/by-name/esp)
while read -r dev point type options dump pass; do
    if [ "$(readlink -f "$dev")" = "$real" ]; then
        umount "$point" || exit 1
    fi
done < /proc/mounts
''')
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
    print('INSTALL PASS; ESP + boot deployment verified when selected; reboot manually after reviewing the guide')


if __name__ == '__main__':
    main()
