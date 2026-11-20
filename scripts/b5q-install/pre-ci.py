#!/usr/bin/env python3
"""Run added b5q integrity/source tests locally before a CI submission."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tomllib

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--root-dir', type=Path)
a = parser.parse_args()
workspace = Path(__file__).resolve().parents[2]
os.chdir(workspace)
device = workspace / 'UniXNU-b5q'
root_dir = (a.root_dir or workspace / 'artifacts/b5q-full-27.3-26C5035r').resolve()
out = workspace / 'artifacts/b5q-firstboot/local-pre-ci'
out.mkdir(parents=True, exist_ok=True)
checks = []

def run(name, arguments):
    result = subprocess.run([str(item) for item in arguments], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    (out / (name + '.log')).write_text(result.stdout)
    if result.returncode:
        print(result.stdout)
        raise SystemExit(f'Local pre-CI failed: {name}')
    checks.append(name)
    print('PASS', name, flush=True)

assert (device / 'scripts/package.sh').read_bytes() == (workspace / 'UniXNU/templates/package.sh').read_bytes()
checks.append('upstream-package-template')
board = tomllib.loads((device / 'board.toml').read_text())
assert board['board']['os_profile'] == 'macos-27.3-26C5035r'
assert 'b5q-root=1' in board['payload']['kernel_args']
assert len(board['components']['include']) == 13
run('porting-record', [sys.executable, 'UniXNU/scripts/porting-record.py', 'check', '--device', device])
run('source-contract', [sys.executable, 'tests/b5q-ufs/test-source-contract.py'])
run('lockdown-public', [sys.executable, 'tests/b5q-ufs/test-lockdown-public.py'])
run('log-startup', [sys.executable, 'tests/b5q-ufs/test-log-startup.py'])
run('log-writer', [sys.executable, 'tests/b5q-ufs/test-log-writer.py'])
run('runtime-gates', [sys.executable, 'tests/b5q-ufs/test-runtime-gates.py'])
run('ethernet-lifecycle', [sys.executable, 'tests/b5q-ufs/test-ethernet-lifecycle.py'])
run('ethernet-start', [sys.executable, 'tests/b5q-ufs/test-ethernet-start.py'])
run('read-status', [sys.executable, 'tests/b5q-ufs/test-read-status.py'])
run('log-read', [sys.executable, 'tests/b5q-ufs/test-log-read.py'])
run('verified-read', [sys.executable, 'tests/b5q-ufs/test-verified-read.py'])
run('ws-signal', [sys.executable, 'tests/b5q-ufs/test-ws-signal.py'])
run('peripheral-policy', [sys.executable, 'tests/b5q-ufs/test-peripheral-policy.py'])
run('shared-gpu', [sys.executable, 'tests/b5q-ufs/test-shared-gpu.py'])
run('peripheral-target', [sys.executable, 'scripts/b5q-install/check-peripheral-target.py', '--reference',workspace/'artifacts/b5q-esp-runtime-v20/esp.img','--objects-out',workspace/'artifacts/b5q-runtime-v21-work/objects'])
run('touch', [sys.executable, 'tests/b5q-ufs/test-touch.py'])
run('data-account', [sys.executable, 'tests/b5q-ufs/test-data-account.py'])
run('v21-inputs', [sys.executable, 'tests/b5q-ufs/test-v21-contract.py'])
run('installer-errors', [sys.executable, 'tests/b5q-ufs/test-installer.py'])
flags = ['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-Wno-misleading-indentation', '-fsanitize=address,undefined', '-I', device / 'package/B5qUfs']
for name in ['root-format', 'smmu', 'protocol']:
    executable = out / name
    run(name + '-compile', [*flags, 'tests/b5q-ufs/' + name + '.cpp', '-o', executable])
    run(name + '-runtime', [executable, *([root_dir / 'delivery/macosroot.img'] if name == 'root-format' else [])])

policy = (device / 'package/B5qUfs/B5qRootPolicies.h').read_text()
anchor = bytes(map(int, re.search(r'b5q_root_key\[\d+\]=\{([^}]+)\}', policy).group(1).split(',')))
headers = [bytes(map(int, row.split(','))) for row in re.findall(r'\{([^{}]+)\}', policy.split('b5q_root_headers[3][544]=', 1)[1])]
assert len(headers) == 3
for name, header in zip(['OS', 'SystemOS', 'App'], headers):
    assert (root_dir / 'delivery/policies' / name / 'manifest.header.bin').read_bytes() == header
    assert (root_dir / 'delivery/policies' / name / 'trusted-key.bin').read_bytes() == anchor
checks.append('exact-local-root-policies')
root_record=json.loads((root_dir/'delivery/macosroot.json').read_text());root_hash=hashlib.sha256()
with (root_dir/'delivery/macosroot.img').open('rb') as stream:
    for block in iter(lambda:stream.read(8<<20),b''):root_hash.update(block)
assert root_hash.hexdigest()==root_record['image_sha256']
assert (root_dir/'delivery/macosroot.img').stat().st_size==root_record['image_bytes']
checks.append('full-root-image-sha256')
sys.path.insert(0, str(workspace / 'UniXNU/kits/XnuPrelink'))
from kc_image import Image
fixture = json.loads((device / 'scripts/pmgr-26C5035r.json').read_text())
original = (root_dir / 'official/ipsw/26C5035r/kernelcache.decompressed').read_bytes()
assert hashlib.sha256(original).hexdigest() == fixture['kernelcache_sha256']
image = Image(original)
for record in fixture['bindings'].values():
    assert image.read(int(record['address'], 16), 32).hex() == record['first_32_bytes']
checks.append('original-pmgr-fixture')
common=sorted((workspace/'sources/UniXNU/out/feeds').glob('UniXNU-sm8550-common-*/dts/sm8550.dtsi'))
assert len(common)==1
run('device-tree-syntax',['dtc','-I','dts','-O','dtb','-i',common[0].parent,'-o',out/'b5q.dtb',device/'dts/b5q.dts'])

paths = [*device.glob('scripts/*.py'), *workspace.glob('scripts/b5q-install/*.py'), *workspace.glob('tests/b5q-ufs/*.py')]
for path in paths:
    compile(path.read_text(), str(path), 'exec')
checks.append('python-syntax')
workflow = (workspace / '.github/workflows/b5q-stage123.yml').read_text()
assert 'Check device record and upstream template' not in workflow
assert 'Report and verify runner tools' not in workflow
assert 'actual FAT members against' not in (device / 'scripts/build-b5q-payload.py').read_text()
checks.append('no-added-ci-integrity-gates')
source_paths = sorted(set([*device.glob('package/**/*.cpp'), *device.glob('package/**/*.h'), *device.glob('scripts/*.py'), device / 'board.toml', device / 'porting.toml', device / 'configs/b5q_macos_defconfig', device / 'dts/b5q.dts', workspace / '.github/workflows/b5q-stage123.yml', *workspace.glob('scripts/b5q-install/*.py')]))
report = {'scope': 'Local source/input checks before submission; target compiler/linker runs in macOS CI', 'checks': checks, 'result': 'PASS', 'source_sha256': {str(path.relative_to(workspace)): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}, 'hardware_tested': False}
(out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
print('LOCAL PRE-CI PASS:', len(checks), 'checks;', out / 'report.json')
