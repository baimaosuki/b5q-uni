#!/usr/bin/env python3
"""Regenerate only the official ADT and menu around an existing verified ESP."""
import argparse
import copy
import hashlib
import importlib.util
import json
import re
import struct
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'UniXNU/scripts'))
from unixnu.devicetree import generate
from unixnu.profiles import merge


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def record(path):
    return dict(bytes=path.stat().st_size, sha256=digest(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--version', type=int, required=True)
    args = parser.parse_args()
    source, out = args.source.resolve(), args.out.resolve()
    old = json.loads((source / 'package.manifest.json').read_text())
    assert old['os_profile'] == 'macos-27.3-26C5035r'
    assert record(source / 'esp.img') == old['outputs']['esp.img']
    board = tomllib.loads((ROOT / 'UniXNU-b5q/board.toml').read_text())
    assert board['payload']['panic_screen'] is True
    spec = importlib.util.spec_from_file_location('esp', ROOT / 'scripts/b5q-install/build-ci-esp.py')
    esp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(esp)
    out.mkdir(parents=True, exist_ok=False)
    with (out / 'verification.log').open('w') as log:
        def run(command):
            subprocess.run(list(map(str, command)), check=True, stdout=log, stderr=subprocess.STDOUT)

        with tempfile.TemporaryDirectory(prefix='b5q-adt-repack-') as temp:
            temp = Path(temp)
            stage = temp / 'stage'
            stage.mkdir()
            run(['mcopy', '-s', '-i', source / 'esp.img', '::/EFI', stage])
            for name in ['startup.nsh', 'XNU2LOG.BIN']:
                run(['mcopy', '-i', source / 'esp.img', '::/' + name, stage / name])
            members = {p.relative_to(stage).as_posix(): record(p)
                       for p in stage.rglob('*') if p.is_file()}
            assert members == old['esp_files']
            boot = stage / 'EFI/UniXNU'
            sidecar = boot / 'Payloads/kernel.macho.adt'
            original = esp.adt_decode(sidecar.read_bytes())
            config = {}
            inputs = ['UniXNU/profiles/arch/arm64e/profile.toml',
                      'sources/UniXNU-sm8550-common/soc.toml',
                      'UniXNU/profiles/os/macos-27.3-26C5035r/profile.toml',
                      'UniXNU-b5q/board.toml']
            for name in inputs:
                config = merge(config, tomllib.loads((ROOT / name).read_text()))
            dtb = temp / 'hardware.dtb'
            run(['dtc', '-I', 'dts', '-O', 'dtb', '-i', ROOT / 'sources/UniXNU-sm8550-common/dts',
                 '-o', dtb, ROOT / 'UniXNU-b5q/dts/b5q.dts'])
            memory = original['/chosen/memory-map']
            identity = int.from_bytes(original['/chosen']['unique-chip-id'], 'little')
            data = generate(dtb, config, unique_chip_id=f'{identity:x}',
                            data='PackedRAMDisk' in memory or 'RAMDisk' in memory,
                            trust='TrustCache' in memory, addon='GpuAddon' in memory,
                            root_policies='RootPolicies' in memory)
            actual = esp.adt_decode(data)
            assert actual.keys() == original.keys()
            changes = []
            for name in original:
                assert actual[name].keys() == original[name].keys()
                for key in original[name]:
                    if actual[name][key] != original[name][key]:
                        changes.append((name, key))
            assert set(changes) == {('/chosen', 'random-seed'), ('/chosen', 'text-fixups')}, changes
            assert actual['/chosen']['text-fixups'] == b''.join(
                rule.encode() + b'\0' for rule in board['payload']['text_fixups'])
            sidecar.write_bytes(data)
            menu = boot / 'unixnu.toml'
            prior = tomllib.loads(menu.read_text())
            entry = next(e for e in prior['entry'] if e.get('type') == 'xnu')
            assert entry['args'] == ' '.join(board['payload']['kernel_args'])
            title = prior['ui']['title']
            new_title, count = re.subn(r'ESP v\d+', f'ESP v{args.version}', title)
            assert count == 1 and title != new_title
            text = menu.read_text().replace(json.dumps(title), json.dumps(new_title))
            menu.write_text(text)
            check = copy.deepcopy(prior)
            check['ui']['title'] = new_title
            assert tomllib.loads(text) == check
            updated = {p.relative_to(stage).as_posix(): record(p)
                       for p in stage.rglob('*') if p.is_file()}
            changed = sorted(name for name in members if updated[name] != members[name])
            assert changed == ['EFI/UniXNU/Payloads/kernel.macho.adt', 'EFI/UniXNU/unixnu.toml']
            image = out / 'esp.img'
            with image.open('wb') as stream:
                stream.truncate(800 * 2**20)
            run(['mkfs.fat', '--invariant', '-F', '32', '-S', '4096', '-s', '1', '-n', 'B5QMACOS', image])
            run(['mcopy', '-s', '-i', image, stage / 'EFI', '::/'])
            for name in ['startup.nsh', 'XNU2LOG.BIN']:
                run(['mcopy', '-i', image, stage / name, '::/' + name])
            run(['fsck.fat', '-n', image])
            for name, expected in updated.items():
                target = temp / 'readback'
                target.unlink(missing_ok=True)
                run(['mcopy', '-i', image, '::/' + name, target])
                assert record(target) == expected, name
            with image.open('rb') as stream:
                bpb = stream.read(512)
            assert struct.unpack_from('<H', bpb, 11)[0] == 4096 and bpb[13] == 1
            assert struct.unpack_from('<I', bpb, 32)[0] * 4096 == image.stat().st_size
            run([sys.executable, ROOT / 'scripts/b5q-install/verify-esp-log.py',
                 '--esp', image, '--out', out / 'log-allocation.json'])
            manifest = copy.deepcopy(old)
            manifest.update(scope=f'v{args.version} local ADT-only software session update', ci_run=None,
                            kernel_source_ci_run=old.get('ci_run') or old.get('kernel_source_ci_run'),
                            outputs={'esp.img': record(image)}, esp_files=updated, hardware_tested=False,
                            log_journal=json.loads((out / 'log-allocation.json').read_text()))
            manifest['build_status'].update(delivery_version=f'b5q-esp-runtime-v{args.version}',
                                             hardware_boot_verified=False)
            manifest['adt_update'] = dict(source=str(source.relative_to(ROOT)),
                source_esp=old['outputs']['esp.img'], changed_members=changed,
                changed_properties=[list(v) for v in changes], policy_count=len(board['payload']['text_fixups']),
                kernel_unchanged=True, Data_unchanged=True, addon_and_trust_unchanged=True,
                new_kernel_build=False, new_ci_run=False, new_firmware_build=False,
                official_generator_sha256=digest(ROOT / 'UniXNU/scripts/unixnu/devicetree.py'),
                config_inputs={name: digest(ROOT / name) for name in inputs},
                hardware_dtb_sha256=digest(dtb), fat_roundtrip=True)
            (out / 'package.manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(dict(out=str(out), outputs=manifest['outputs'], update=manifest['adt_update']), indent=2))


if __name__ == '__main__':
    main()
