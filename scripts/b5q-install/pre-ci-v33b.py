#!/usr/bin/env python3
"""Bind the five requested offline gates to actual source and test receipts."""
import hashlib,json,subprocess,sys
from pathlib import Path
R=Path(__file__).resolve().parents[2];W=R/'artifacts/b5q-v33b-fix-work';checks=[]
def run(name,script,*args):
 path=W/(name+'.log')
 with path.open('w')as f:r=subprocess.run([sys.executable,str(R/script),*map(str,args)],cwd=R,stdout=f,stderr=subprocess.STDOUT)
 if r.returncode:raise SystemExit('FAIL '+name+'; see '+str(path))
 checks.append(dict(name=name,passed=True,log_sha256=hashlib.sha256(path.read_bytes()).hexdigest()));print('PASS',name,flush=True)
# Reuse the already-executed complete retained regression only when every
# production input it qualified still has the same SHA. Never reuse stalePASS.
baseline=json.loads((R/'artifacts/b5q-p4-work/pre-ci/report.json').read_text());assert baseline['passed']
for n,digest in baseline['source_sha256'].items():assert hashlib.sha256((R/n).read_bytes()).hexdigest()==digest,('baseline source changed',n)
assert 'PASS complete P4 local gate'in(W/'pre-ci-all.log').read_text()
checks.append(dict(name='full-P0-P4-retained-production-regressions',passed=True,checks=len(baseline['checks'])))
run('causal','tests/b5q-ufs/test-v33b-causal.py')
run('dyld-upl','tests/b5q-ufs/test-v33b-dyld-upl.py')
run('firmware-reservations','tests/b5q-ufs/test-v33b-reservations.py')
run('addon-reuse-policy','tests/b5q-ufs/test-addon-reuse-policy.py')
run('policy-migration','tests/b5q-ufs/test-v33b-policy.py')
run('host-abi','tests/b5q-ufs/test-v33b-host-abi.py')
run('static-gates','scripts/b5q-install/check-v33b-static.py')
run('failure-gates','scripts/b5q-install/check-v33b-failures.py')
run('dp-local','scripts/b5q-install/check-dp-local.py')
run('dp-target','scripts/b5q-install/check-dp-target.py')
run('hid-target','scripts/b5q-install/check-peripheral-target.py','--sources','NativeHidInput.cpp,Sm8550Gcc.c,B5qLaunchdPolicy.c,UsbProbe.cpp','--objects-out',W/'hid-target','--reference',R/'artifacts/b5q-esp-p5/esp.img')
run('keyprobe-target','scripts/b5q-install/check-peripheral-target.py','--sources','KeyStoreProbe.cpp,NativeKeyStoreEvents.cpp','--objects-out',W/'keyprobe-target','--reference',R/'artifacts/b5q-esp-p5/esp.img')
run('hid-callback-pac','scripts/b5q-install/check-media-callback-pac.py','--dp','--hid',W/'hid-target/NativeHidInput.o','--out',W/'hid-callback-pac.json')
files=[*sorted((R/'UniXNU-b5q/package').rglob('*.c')),*sorted((R/'UniXNU-b5q/package').rglob('*.h')),*sorted((R/'UniXNU-b5q/package').rglob('*.cpp')),*sorted((R/'UniXNU-b5q/scripts').glob('*.py')),*sorted((R/'UniXNU-b5q/patches/xnu').glob('*.patch')),R/'UniXNU-b5q/patches/xnu/series',R/'UniXNU-b5q/dts/b5q.dts',R/'UniXNU-b5q/board.toml',R/'UniXNU-b5q/package/b5q-launchd-lite.json',R/'.github/workflows/b5q-p0-p5.yml',*sorted((R/'patches/uefi-b5q').glob('*.patch')),*sorted((R/'uefi-b5q/Platforms/Samsung/b5qPkg/Drivers/B5qHandoffDxe').glob('*.[ch]')),R/'uefi-b5q/Platforms/Samsung/b5qPkg/Include/B5qReservedMemory.h',R/'uefi-b5q/Platforms/Samsung/b5qPkg/Library/MemoryMapLib/MemoryMapLib.c']
files+=sorted((R/'scripts/b5q-install').glob('*.py'))+sorted((R/'tests/b5q-ufs').glob('*v33b*.py'))+[R/'tests/b5q-ufs/test-addon-reuse-policy.py']
receipt=dict(passed=True,hardware_verified=False,checks=checks,source_sha256={str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest()for p in files},
 gates={'physical_cause_models':'PASS','memory_ABI_real_DTB_ADT':'PASS','sheng_macos_diff_accounted':'PASS','silent_failure_inventory':'PASS','existing_Data_idempotent_migration':'PASS'},
 native_CI_returned_binary_APFS_verification='Required before final ESP assembly; check-v33b-returned.py',ESP_created=False)
(W/'local-gates.json').write_text(json.dumps(receipt,indent=2)+'\n');print('PASS local gates source-bound; CI payload/object return next, finalESP still gated')
