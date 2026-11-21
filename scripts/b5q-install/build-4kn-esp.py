#!/usr/bin/env python3
"""Restore the completed official payload member on a native-4K physical ESP.

This narrowly scoped local assembly keeps every ESP-v2 member byte-identical.
It does not replace the deployment copy with the intermediate kernel, run a
patcher, regenerate the ADT/Data seed, change boot arguments, or build firmware.
The source kernel and completed CI payload are separate, verified inputs.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[2]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--source', type=Path, required=True, help='original ESP-v2 delivery')
p.add_argument('--raw-kernel', type=Path, required=True, help='intermediate source kernel; provenance only')
p.add_argument('--ci-payload', type=Path, required=True, help='completed official CI FAT payload')
p.add_argument('--out', type=Path, required=True)
a = p.parse_args()
source, raw, ci_payload, out = (path.resolve() for path in (a.source, a.raw_kernel, a.ci_payload, a.out))


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def record(path):
    return {'bytes': path.stat().st_size, 'sha256': sha(path)}


original = json.loads((source / 'package.manifest.json').read_text())
assert original['os_profile'] == 'macos-27.3-26C5035r'
assert sha(raw) == '12515af5f800b1f2ce0b6cd80446c4c3da6b8ed09124341197db10666bf975df'
assert sha(ci_payload) == 'b22b57038460c16ee87deff5763dd9613dad8a29edd1afe2d1995d8a9b1b61e7'
for path, expected in original['esp_files'].items():
    assert record(source / 'esp-files' / path) == expected, path
config_path = source / 'esp-files/EFI/UniXNU/unixnu.toml'
config = tomllib.loads(config_path.read_text())
assert config['boot'] == {'timeout': 3, 'default': 'xnu'}
assert [entry['id'] for entry in config['entry']] == ['xnu', 'reset', 'shutdown', 'tools']
assert config['driver'] == [{'path': 'Drivers/DarwinBoot.efi'}]
entry = next(item for item in config['entry'] if item.get('type') == 'xnu')
deploy_path = source / 'esp-files/EFI/UniXNU' / entry['path']
expected_deploy = '7ea22869a35061a45d00221d503442a3d58b6f845c6d1d7fbecd7f49ff18cacf'
assert sha(deploy_path) == expected_deploy
# Verify the deployable bytes against the real completed payload, not an
# inferred patch result. There is no patcher invocation in this assembly.
with tempfile.TemporaryDirectory(prefix='b5q-official-payload-') as temp:
    extracted = Path(temp) / 'kernel.macho'
    subprocess.run(['mcopy', '-i', str(ci_payload), '::/EFI/UniXNU/' + entry['path'], str(extracted)], check=True)
    assert sha(extracted) == expected_deploy
out.mkdir(parents=True, exist_ok=False)
stage = out / 'esp-files'
shutil.copytree(source / 'esp-files', stage)
# Payload generation legitimately uses a different deployment kernel from the
# intermediate kernel. Preserve both identities and the original file roles.
shutil.copyfile(raw, out / 'kernel.macho')
deployed = stage / 'EFI/UniXNU' / entry['path']
assert sha(deployed) == expected_deploy
for file in ['payload-patch.log', 'payload-seal.log']:
    shutil.copyfile(ci_payload.parent.parent / 'logs' / file, out / file)
esp = out / 'esp.img'
with esp.open('wb') as stream:
    stream.truncate(838860800)
with (out / 'fat-verification.log').open('w') as log:
    def run(command):
        subprocess.run([str(x) for x in command], stdout=log, stderr=subprocess.STDOUT, check=True)
    run(['mkfs.fat', '--invariant', '-F', '32', '-S', '4096', '-s', '1', '-n', 'B5QMACOS', esp])
    run(['mcopy', '-s', '-i', esp, stage / 'EFI', '::/'])
    run(['mcopy', '-i', esp, stage / 'startup.nsh', '::/startup.nsh'])
    run(['fsck.fat', '-n', esp])
    with tempfile.TemporaryDirectory(prefix='b5q-restored-fat-') as temp:
        target = Path(temp) / 'member'
        for path in sorted(stage.rglob('*')):
            if not path.is_file():
                continue
            target.unlink(missing_ok=True)
            run(['mcopy', '-i', esp, f'::/{path.relative_to(stage).as_posix()}', target])
            assert record(target) == record(path), str(path)
with esp.open('rb') as stream:
    bpb = stream.read(512)
assert struct.unpack_from('<H', bpb, 11)[0] == 4096 and bpb[13] == 1
assert bpb[82:90] == b'FAT32   ' and bpb[510:512] == b'\x55\xaa'
assert struct.unpack_from('<I', bpb, 32)[0] * 4096 == esp.stat().st_size
shutil.copyfile(esp, out / 'payload.img')
shutil.copyfile(ROOT / 'scripts/b5q-install/install-firstboot.py', out / 'install-firstboot.py')
shutil.copyfile(ROOT / 'scripts/b5q-install/ESP-4KN.zh-CN.md', out / 'README.zh-CN.md')
manifest = original
manifest.update(scope='Restore original completed CI payload deployment; physical ESP sector correction only',
                hardware_tested=False,
                supersedes='Withdraw custom v3 reset diagnostics and v4 intermediate-kernel substitution',
                deploy_kernel_sha256=sha(deployed),
                outputs={name: record(out / name) for name in ['esp.img', 'payload.img', 'kernel.macho']},
                esp_files={path.relative_to(stage).as_posix(): record(path)
                           for path in sorted(stage.rglob('*')) if path.is_file()})
# All ESP files, including the exact menu, loader, kernel and sidecars, must
# match the previously deployed ESP-v2 tree. Only the FAT container changes.
assert manifest['esp_files'] == json.loads((source / 'package.manifest.json').read_text())['esp_files']
manifest['build_status'].update(delivery_version='ESP-guide-restored-v5', esp_fat_sector_bytes=4096,
                               esp_device_logical_sector_bytes=4096, esp_sectors_per_cluster=1,
                               scope='Prior payload baseline restored; no Samsung runtime fix claimed')
manifest['restoration'] = {
    'guide_revision': '563595abedfdfa413ad583b66b6176d82007e633',
    'guide': 'docs/guide/debugging.md:202-230 and docs/porting/bring-up.md:1-8',
    'source_kernel_role': 'Intermediate compiled/prelinked kernel; not substituted into completed ESP',
    'deployment_role': 'Exact already-generated CI payload member, including original panic-screen/no-reset processing',
    'deployment_matches_ci_payload': True,
    'every_esp_member_matches_v2': True,
    'new_probe_code_applied': False,
    'custom_reset_entries': [],
    'kernel_arguments_changed': False,
    'adt_changed': False,
    'data_seed_changed': False,
    'firmware_or_boot_changed': False,
    'fat_members_roundtrip': 'PASS',
    'physical_fat_format': 'FAT32, 4096 bytes per sector, one sector per cluster',
}
(out / 'package.manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
(out / 'SHA256SUMS').write_text(''.join(f'{sha(path)}  {path.relative_to(out).as_posix()}\n'
                                     for path in sorted(out.rglob('*')) if path.is_file() and 'esp-files' not in path.parts))
print(json.dumps({'directory': str(out), 'outputs': manifest['outputs'],
                  'deployment_sha256': sha(deployed), 'all_esp_members_unchanged': True}, indent=2))
