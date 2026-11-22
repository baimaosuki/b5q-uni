#!/usr/bin/env python3
"""Batch 1 local checks; CI only compiles/relinks and packages afterwards."""
from pathlib import Path
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import tomllib
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / 'artifacts/b5q-runtime-v33-work'
WORK.mkdir(exist_ok=True)
checks = []


def run(name, command):
    result = subprocess.run([str(x) for x in command], cwd=ROOT, capture_output=True, text=True)
    (WORK / (name + '.log')).write_text(result.stdout + result.stderr)
    if result.returncode:
        print(result.stdout + result.stderr)
        raise SystemExit('FAIL ' + name)
    checks.append(dict(name=name, command=list(map(str, command)), passed=True))
    print('PASS ' + name, flush=True)


run('records', [sys.executable, 'UniXNU/scripts/porting-record.py', 'check', '--device', 'UniXNU-b5q'])
run('native-launchd', [sys.executable, 'scripts/b5q-install/check-macos-launchd-policy.py',
    '--launchd', WORK / 'root/sbin/launchd', '--rootless', WORK / 'root/System/Library/Sandbox/com.apple.xpc.launchd.rootless.plist',
    '--report', ROOT / 'UniXNU-b5q/reports/launchd-26C5035r-policy.json'])
run('absentd-ASan-UBSan', [sys.executable, 'tests/b5q-ufs/test-absentd-v33.py'])
with tempfile.TemporaryDirectory(prefix='b5q-proctop-preci-') as temp:
    exe = Path(temp) / 'proctop'
    run('proctop-compile', ['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-pthread',
        '-fsanitize=address,undefined', '-I', ROOT / 'UniXNU-b5q/package', ROOT / 'tests/b5q-ufs/test-proctop.cpp', '-o', exe])
    run('proctop-ASan-UBSan', [exe])
run('target', [sys.executable, 'scripts/b5q-install/check-peripheral-target.py', '--sources', 'B5qProcTop.c,B5qBootPolicy.c',
    '--objects-out', WORK / 'objects', '--reference', ROOT / 'artifacts/b5q-esp-runtime-v32/esp.img'])
run('proctop-PAC', [sys.executable, 'scripts/b5q-install/check-proctop-pac.py', '--object', WORK / 'objects/B5qProcTop.o',
    '--core-objects', WORK / 'pac', '--out', WORK / 'proctop-pac.json'])
for name in ('data-account', 'log-startup', 'log-writer', 'installer'):
    run(name, [sys.executable, 'tests/b5q-ufs/test-' + name + '.py'])
board = tomllib.loads((ROOT / 'UniXNU-b5q/board.toml').read_text())
assert board['adt']['chosen']['asmb'] == {'u64': {'lp-sip0': 2}}
sys.path.insert(0, str(ROOT / 'UniXNU/scripts'))
from unixnu.devicetree import typed_properties
assert typed_properties(board['adt']['chosen']['asmb']) == [('lp-sip0', b'\2' + bytes(7))]
assert len(' '.join(board['payload']['kernel_args']).encode()) == 949
assert 'offline-mobile-graphics-client=1' not in board['payload']['kernel_args']
assert (ROOT / 'UniXNU-b5q/scripts/package.sh').read_bytes() == (ROOT / 'UniXNU/templates/package.sh').read_bytes()
workflow = yaml.safe_load((ROOT / '.github/workflows/b5q-v33-incremental.yml').read_text())
commands = '\n'.join(s.get('run', '') for s in workflow['jobs']['incremental']['steps'])
assert '--version v33' in commands and '--baseline v32' in commands
assert not any(s in commands for s in ['unixnu build xnu', 'unixnu build firmware', 'build-mesa'])
plan = json.loads((WORK / 'relink-plan/incremental-inputs.json').read_text())
assert plan['core_translation_units_compiled'] == 0 and not plan['gpu_recompiled']
assert set(plan['changed_board_sources']) == {'B5qBootPolicy.c', 'B5qProcTop.c'}
core = ROOT / 'artifacts/b5q-runtime-v32-work/completed-cache/tree/build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837.link/mach.development.bcm2837.a'
assert hashlib.sha256(core.read_bytes()).hexdigest() == plan['expected_core_sha256']
checks.append(dict(name='ADT-codec-cache-workflow-template', passed=True))
report = dict(passed=True, checks=checks, hardware_verified=False,
    core_translation_units_compiled=0, source_cache_run=45016691051,
    statistical_cases='160000 concurrent exits plus signal/status/full-table/reset cases',
    absentd_cases=8, launchd_instruction_cases=19)
(WORK / 'pre-ci-v33.json').write_text(json.dumps(report, indent=2) + '\n')
print('PASS Batch1 local pre-CI:', len(checks), 'checks; real image and device acceptance remain separate')
