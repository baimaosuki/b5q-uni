#!/usr/bin/env python3
"""Repair firstboot menu delivery using a real physical ESP and a bare FAT bootstrap.

No firmware or XNU compilation. Preserves the old package and transport kernel.
Never opens a connected phone. Explicit local emulation remains a separate step.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tarfile
import tomllib

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--source', type=Path, required=True)
p.add_argument('--out', type=Path, required=True)
a = p.parse_args()
workspace = Path(__file__).resolve().parents[2]
source, out = a.source.resolve(), a.out.resolve()
out.mkdir(parents=True, exist_ok=False)

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 << 20), b''):
            h.update(block)
    return h.hexdigest()

def run(args):
    subprocess.run([str(x) for x in args], check=True)

manifest = json.loads((source / 'package.manifest.json').read_text())
for name in ['kernel.macho', 'macosroot.img']:
    item = manifest['outputs'][name]
    assert (source / name).stat().st_size == item['bytes']
    assert sha(source / name) == item['sha256']
    os.link(source / name, out / name)
for name in ['build-verification.json', 'data-seed.json', 'macosroot.json', 'ci-data-seed.json']:
    shutil.copyfile(source / name, out / name)
shutil.copytree(source / 'policies', out / 'policies')
stage = out / 'esp-files'
shutil.copytree(source / 'esp-files', stage)
config_path = stage / 'EFI/UniXNU/unixnu.toml'
config = config_path.read_text()
assert '[[driver]]' not in config
config = config.replace('[[entry]]', '[[driver]]\npath = "Drivers/DarwinBoot.efi"\n\n[[entry]]', 1)
# A unique title makes it possible to distinguish the new configuration from
# both the old HelloPayload menu and the first broken delivery.
config = config.replace('title = "UniXNU b5q macOS 27.3"', 'title = "b5q macOS 27.3 - ESP v2"')
config = config.replace('version = 1\n', 'version = 1\n[ui]\ntitle = "b5q macOS - ESP v2"\n', 1)
config_path.write_text(config)
parsed = tomllib.loads(config)
assert parsed['driver'][0]['path'] == 'Drivers/DarwinBoot.efi'
entry = next(x for x in parsed['entry'] if x.get('type') == 'xnu')
assert (stage / 'EFI/UniXNU' / entry['path']).is_file()
assert (stage / 'EFI/UniXNU' / entry['initrd']).is_file()
for suffix in ['.adt', '.trustcache']:
    assert (stage / 'EFI/UniXNU' / (entry['path'] + suffix)).is_file()
# Give manual EFI-shell users a direct entry point; no on-device assumptions.
(stage / 'startup.nsh').write_text('\\EFI\\BOOT\\BOOTAA64.EFI\r\n')
esp = out / 'esp.img'
with esp.open('wb') as stream:
    stream.truncate(838860800)
run(['mkfs.fat', '--invariant', '-F', '32', '-S', '4096', '-s', '1', '-n', 'B5QMACOS', esp])
run(['mcopy', '-s', '-i', esp, stage / 'EFI', '::/'])
run(['mcopy', '-i', esp, stage / 'startup.nsh', '::/startup.nsh'])
run(['fsck.fat', '-n', esp])
# The normal FAT payload is useful on its own but is no longer the only carrier
# of the new configuration. esp.img is the explicit deployment target.
shutil.copyfile(esp, out / 'payload.img')

# Preserve exactly the existing Android kernel/firmware/DTB transport. Use a
# small plain FAT ramdisk with the menu application but no menu configuration.
# Thus it cannot shadow the real ESP's macOS configuration with a Hello entry.
bootstrap = out / 'bootstrap-files'
(bootstrap / 'EFI/BOOT').mkdir(parents=True)
shutil.copyfile(stage / 'EFI/BOOT/BOOTAA64.EFI', bootstrap / 'EFI/BOOT/BOOTAA64.EFI')
(bootstrap / 'README.txt').write_text('b5q ESP v2 bootstrap. Configuration and macOS files are on physical ESP. No HelloPayload or unixnu.toml on this bootstrap.\n')
fat = out / 'bootstrap.fat'
with fat.open('wb') as stream:
    stream.truncate(16 * 1024 * 1024)
run(['mkfs.fat', '--invariant', '-F', '16', '-S', '512', '-n', 'B5QBOOT', fat])
run(['mcopy', '-s', '-i', fat, bootstrap / 'EFI', '::/'])
run(['mcopy', '-i', fat, bootstrap / 'README.txt', '::/README.txt'])
run(['fsck.fat', '-n', fat])
old_boot = (source / 'boot.img').read_bytes()
assert old_boot[:8] == b'ANDROID!' and struct.unpack_from('<I', old_boot, 40)[0] == 4
kernel_size = struct.unpack_from('<I', old_boot, 8)[0]
ramstart = 4096 + ((kernel_size + 4095) // 4096) * 4096
header = bytearray(old_boot[:ramstart])
struct.pack_into('<I', header, 12, fat.stat().st_size)
struct.pack_into('<I', header, 1580, 0)
boot = out / 'boot.img'
with boot.open('wb') as stream:
    stream.write(header)
    with fat.open('rb') as data:
        shutil.copyfileobj(data, stream)
assert boot.stat().st_size <= 100663296
assert boot.read_bytes()[4096:4096 + kernel_size] == old_boot[4096:4096 + kernel_size]
with tarfile.open(out / 'boot-b5q-esp-v2.tar', 'w', format=tarfile.USTAR_FORMAT) as tar:
    tar.add(boot, arcname='boot.img')
shutil.copyfile(workspace / 'scripts/b5q-install/install-firstboot.py', out / 'install-firstboot.py')
shutil.copyfile(workspace / 'scripts/b5q-install/ESP-REPAIR.zh-CN.md', out / 'ESP修复与刷入指南.md')
# Read the exact new FAT image back independently; file names alone are not enough.
checks = {}
for path in sorted(stage.rglob('*')):
    if not path.is_file():
        continue
    rel = path.relative_to(stage).as_posix()
    readback = subprocess.check_output(['mtype', '-i', str(esp), '::/' + rel])
    assert hashlib.sha256(readback).hexdigest() == sha(path), rel
    checks[rel] = {'bytes': len(readback), 'sha256': sha(path)}
assert not subprocess.run(['mtype', '-i', str(fat), '::/EFI/UniXNU/unixnu.toml'], capture_output=True).returncode == 0
with fat.open('rb') as stream:
    bpb = stream.read(512)
assert bpb[510:512] == b'\x55\xaa' and bpb[:8] != b'UNXNFAT1'
status = manifest['build_status'].copy()
status.update(delivery_version='ESP-v2', firstboot_v1_superseded=True,
              menu_source='physical esp partition', esp_install_required=True,
              ramdisk_encoding='plain FAT16', boot_configuration_on_ramdisk=False,
              loader_explicitly_declared=True, hardware_boot_verified=False,
              payload_chunk_roundtrip_verified=False, payload_chunk_codec_used=False,
              flash_candidate_ready=True)
status['limitations'].append('The physical 800MiB ESP must be updated; boot/macOS-root hashes alone do not establish menu deployment.')
manifest['build_status'] = status
manifest['scope'] = 'First hardware boot candidate; repaired physical ESP delivery, no XNU recompile'
manifest['outputs'] = {name: {'bytes': (out / name).stat().st_size, 'sha256': sha(out / name)} for name in ['kernel.macho', 'macosroot.img', 'esp.img', 'payload.img', 'boot.img', 'boot-b5q-esp-v2.tar']}
manifest['esp_files'] = checks
(out / 'package.manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
(out / 'BUILD-STATUS.json').write_text(json.dumps(status, indent=2) + '\n')
report = {'scope': 'local package/contents audit, no hardware boot assertion',
          'origin': str(source), 'xnu_recompiled': False, 'ci_started': False,
          'old_boot_ramdisk_magic': old_boot[ramstart:ramstart + 8].decode(),
          'new_boot_ramdisk_magic_hex': bpb[:11].hex(),
          'transport_kernel_identical': True, 'boot_ramdisk_has_no_shadow_config': True,
          'physical_esp_bytes': esp.stat().st_size, 'fat_member_readback': checks,
          'loader_declaration': parsed['driver'], 'default_entry': parsed['boot']['default'],
          'menu_title': parsed['ui']['title'], 'hardware_verified': False}
(out / 'esp-package-verification.json').write_text(json.dumps(report, indent=2) + '\n')
(out / 'SHA256SUMS').write_text(''.join(sha(path) + '  ' + path.relative_to(out).as_posix() + '\n' for path in sorted(out.rglob('*')) if path.is_file() and path.name != 'SHA256SUMS'))
print(json.dumps({'directory': str(out), 'outputs': manifest['outputs'], 'hardware_verified': False}, indent=2))
