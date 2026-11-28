#!/usr/bin/env python3
"""Read back the final ESP, including all checks previously run by hand."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import struct
import subprocess
import sys
import tempfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def verify(esp, ci, fd, config, output, package_metadata=None):
    sys.path[:0] = [str(ROOT / 'UniXNU/scripts'), str(ROOT / 'UniXNU-b5q/scripts')]
    from unixnu import ramdisk
    from unixnu.boot_template import loader_pe
    from b5q_gpu_adt import verify as gpu_verify
    from b5q_menu import profiles
    from b5q_codesign import inspect_code_directories, inspect_trust_entry

    fs = module('release_fs', ROOT / 'scripts/b5q-install/package-usb-dma-esp.py')
    addon = module('release_addon', ROOT / 'UniXNU/scripts/addon-add-dir.py')
    output.parent.mkdir(parents=True, exist_ok=True)
    fs.image_format(esp)
    metadata = json.loads((package_metadata or ci / 'batch2-package.json').read_text())
    image_record = fs.record(esp)
    assert image_record == metadata['esp'], 'ESP differs from producer hash'
    subprocess.run(['fsck.fat', '-n', str(esp)], check=True)
    subprocess.run([sys.executable, str(ROOT / 'scripts/b5q-install/verify-esp-log.py'),
                    '--esp', str(esp), '--out', str(output.parent / 'log-allocation.json')], check=True)
    with tempfile.TemporaryDirectory(prefix='esp-readback-', dir=os.environ['TMPDIR']) as td:
        temp = Path(td)
        members = fs.members(esp, temp / 'esp')
        assert members == metadata['members'], 'FAT members differ from producer map'
        payload = ci / 'payload/payload.img'
        if ramdisk.packed(payload):
            fat = temp / 'payload.fat'
            ramdisk.decode(payload, fat)
        else:
            fat = payload
        original = fs.members(fat, temp / 'ci')
        for name, record in original.items():
            if name.startswith('EFI/UniXNU/Payloads/') and not name.endswith('.adt'):
                assert members[name] == record, name
        boot = temp / 'esp/EFI/UniXNU'
        assets = boot / 'Payloads'
        board = tomllib.loads((ROOT / 'UniXNU-b5q/board.toml').read_text())
        menu = tomllib.loads((boot / 'unixnu.toml').read_text())
        entries = [entry for entry in menu['entry'] if entry.get('type') == 'xnu']
        assert menu['boot']['default'] == 'xnu'
        assert entries == profiles(board['payload']['kernel_args'])
        adt_proofs = {}
        for path in assets.rglob('*.adt'):
            nodes = fs.adt_nodes(path.read_bytes())
            adt_proofs[str(path.relative_to(assets))] = gpu_verify(nodes['/chosen'][2])
            assert '/arm-io/wlan' in nodes and '/arm-io/bluetooth' in nodes
            assert nodes['/chosen/asmb'][2]['lp-sip0'] == (2).to_bytes(8, 'little')
        assert len(adt_proofs) == 2
        for name, guid in [('EFI/BOOT/BOOTAA64.EFI', '9b665204-a133-47a2-9396-9e2b370a4e25'),
                           ('EFI/UniXNU/Drivers/DarwinBoot.efi', '1b64af87-8415-4b57-9b16-680d70913b9f')]:
            assert (temp / 'esp' / name).read_bytes() == loader_pe(fd.read_bytes(), guid)
        content = {name: body for name, mode, body in addon.read(assets / 'kernel.macho.gpuaddon')}
        daemon, = [body for name, body in content.items() if name.endswith('/bluetoothd')]
        signatures = inspect_code_directories(daemon)
        trust = [inspect_trust_entry((assets / 'kernel.macho.trustcache').read_bytes(), s['cdhash'])
                 for s in signatures]
        assert all(s['platform'] == 27 and s['page_hashes_valid'] for s in signatures)
        assert all(s['constraint_category'] == 1 for s in trust)
        le_mask = None
        if config['bluetooth_le_mask']:
            import b5q_bt_le_mask as le
            assert le._validate_macho(daemon) == le.B5Q_UUID
            assert daemon[le.SITE1_OFFSET:le.SITE1_OFFSET + 8] == le.SITE1_NEW
            assert struct.unpack_from('<I', daemon, le.SITE2_OFFSET)[0] == le.SITE2_NEW
            le_mask = le.B5Q_LE_EVENT_MASK
        job = plistlib.loads(content['Library/LaunchDaemons/org.unixnu.wifi.supplicant.plist'])
        assert job['RunAtLoad'] is False and job['ThrottleInterval'] >= 60
        assert job['KeepAlive'] == {'PathState': {'/private/var/run/b5q-wifi-ready': True}}
        raw = (assets / 'kernel.macho').read_bytes()
        for marker in config['kernel_markers']:
            assert marker.encode() in raw, marker
        armcpu, = ci.rglob('ArmCpu.o')
        env = dict(os.environ, LD_LIBRARY_PATH=str(ROOT / 'tools/llvm21/usr/lib/x86_64-linux-gnu'))
        symbols = subprocess.check_output([str(ROOT / 'tools/llvm21/usr/lib/llvm-21/bin/llvm-nm'),
                                           '--defined-only', str(armcpu)], env=env)
        assert b'gDistLock' in symbols and b'gSmpStartLock' in symbols
        with (output.parent / 'POST.log').open('w') as log:
            subprocess.run([sys.executable, str(ROOT / 'tests/b5q-ufs/test-post-seal.py'),
                            '--kernel', str(assets / 'kernel.macho'),
                            '--out', str(output.parent / 'POST.json')],
                           stdout=log, stderr=subprocess.STDOUT, check=True)
        proof = dict(passed=True, hardware_verified=False, esp=image_record,
                     FAT='FAT32', sector_bytes=4096, members=members,
                     CI_payload_assets_byte_identical=True, paired_EFI=True,
                     profile_GPU_ADT_verified=adt_proofs, bluetooth_LE_mask=le_mask,
                     bluetooth_signatures=signatures, bluetooth_trust=trust,
                     wifi_readiness_policy=True, POST_HMAC='PASS', XNU2LOG_allocation='PASS',
                     kernel_args_bytes=len(entries[0]['args'].encode()),
                     kernel_markers=config['kernel_markers'],
                     patched_ArmCpu_sha256=hashlib.sha256(armcpu.read_bytes()).hexdigest())
        output.write_text(json.dumps(proof, indent=2) + '\n')
    print('PASS final ESP readback:', esp, image_record['sha256'], flush=True)
    return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['esp', 'ci', 'fd', 'out']:
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--config', type=Path, default=ROOT / 'scripts/b5q-release.json')
    parser.add_argument('--package-metadata', type=Path)
    args = parser.parse_args()
    verify(args.esp.resolve(), args.ci.resolve(), args.fd.resolve(),
           json.loads(args.config.read_text()), args.out.resolve(), args.package_metadata)


if __name__ == '__main__':
    main()
