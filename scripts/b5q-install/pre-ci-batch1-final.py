#!/usr/bin/env python3
"""Require complete local Batch 1 source proofs before its final package run."""
from pathlib import Path
import hashlib
import importlib.util
import json
import plistlib
import subprocess
import sys
import tempfile
import tomllib
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / 'artifacts/b5q-batch1-final-work'
SOURCE = ROOT / 'artifacts/b5q-runtime-v33-work'
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
    '--launchd', SOURCE / 'root/sbin/launchd', '--rootless', SOURCE / 'root/System/Library/Sandbox/com.apple.xpc.launchd.rootless.plist',
    '--policy', ROOT / 'UniXNU-b5q/package/b5q-launchd-lite.json', '--report', WORK / 'native-launchd.json'])
run('native-XPC-and-five-job-audit', [sys.executable, 'scripts/b5q-install/check-absentd-lifecycle.py',
    '--root', SOURCE / 'root', '--cache', ROOT/'inputs/macos-27.3-26C5035r/shared-cache/dyld_shared_cache_arm64e',
    '--report', WORK / 'absent-lifecycle.json'])
run('absentd-ASan-UBSan', [sys.executable, 'tests/b5q-ufs/test-absentd-v33.py'])
with tempfile.TemporaryDirectory(prefix='b5q-proctop-final-preci-') as temp:
    exe = Path(temp) / 'proctop'
    run('proctop-compile', ['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-pthread',
        '-fsanitize=address,undefined', '-I', ROOT / 'UniXNU-b5q/package', ROOT / 'tests/b5q-ufs/test-proctop.cpp', '-o', exe])
    run('proctop-ASan-UBSan', [exe])
run('baseline-proctop-PAC-contract', [sys.executable, 'scripts/b5q-install/check-proctop-pac.py', '--object', SOURCE / 'ci-files/kernel/incremental-objects/B5qProcTop.o',
    '--core-objects', SOURCE / 'pac', '--out', WORK / 'proctop-pac.json'])
for name in ('data-account', 'log-startup', 'log-writer', 'installer'):
    run(name, [sys.executable, 'tests/b5q-ufs/test-' + name + '.py'])
board = tomllib.loads((ROOT / 'UniXNU-b5q/board.toml').read_text())
assert board['adt']['chosen']['asmb'] == {'u64': {'lp-sip0': 2}}
assert len(' '.join(board['payload']['kernel_args']).encode()) == 949
assert (ROOT / 'UniXNU-b5q/scripts/package.sh').read_bytes() == (ROOT / 'UniXNU/templates/package.sh').read_bytes()
spec = importlib.util.spec_from_file_location('seed', ROOT / 'UniXNU-b5q/scripts/update-b5q-launchd-seed.py')
seed = importlib.util.module_from_spec(spec); spec.loader.exec_module(seed)
for labels in seed.policies().values():
    encoded = seed.merge(plistlib.dumps({'com.apple.endpointsecurity.endpointsecurityd': True}), labels)
    assert encoded.startswith(b'bplist00') and plistlib.loads(encoded) == (dict(labels) if isinstance(labels,dict) else dict.fromkeys(labels,True))
    assert not set(labels) & {'com.apple.WindowServer', 'com.apple.loginwindow', 'com.apple.Dock.agent', 'com.apple.Finder', 'com.apple.endpointsecurity.endpointsecurityd'}
    assert {'com.apple.geod', 'com.apple.ReportCrashService', 'com.apple.wallpaper.extension.aerials'} <= set(labels)
workflow = yaml.safe_load((ROOT / '.github/workflows/b5q-batch1-final.yml').read_text())
commands = '\n'.join(s.get('run', '') for s in workflow['jobs']['incremental']['steps'])
assert '45047962341' in commands and '45041019820' in commands
assert '--version batch1-proctop' in commands and '--changed B5qProcTop.c' in commands
assert 'B5qBootPolicy.c' not in commands
assert not any(s in commands for s in ['unixnu build xnu', 'unixnu build firmware', 'build-mesa'])
uploads = [step for step in workflow['jobs']['incremental']['steps']
           if step.get('uses', '').startswith('actions/upload-artifact@')]
assert len(uploads) == 2 and uploads[0]['with']['path'] == 'UniXNU/out/b5q/**/esp.img'
assert '.img' not in uploads[1]['with']['path'] and 'capstone' in commands
checks.append(dict(name='ADT-binary-plist-desktop-exclusions-cache-only-workflow', passed=True))
report = dict(passed=True, checks=checks, hardware_verified=False, core_and_board_objects_recompiled=0,
    existing_v33_kernel_and_4GiB_volume_reused=True, native_launchd_instruction_cases=89,
    actual_libxpc_transaction_cases=3, source_jobs_audited=5, production_absentd_cases=21,
    concurrency='160000 events plus signal/status/reset/overflow',
    final_ci_board_objects_to_compile=['B5qProcTop.c'], data_seed_regenerated=False,
    local_arm64e_compile='LLVM21 is incompatible with the pinned 26.5 SDK four-argument __ptrauth macro; CI Xcode26.6 compiles and PAC-checks the final object')
(WORK / 'pre-ci.json').write_text(json.dumps(report, indent=2) + '\n')
print('PASS complete Batch1 local source preflight:', len(checks), 'checks; final CI/image checks remain required')
