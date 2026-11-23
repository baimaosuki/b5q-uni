#!/usr/bin/env python3
"""Require complete Bluetooth/Wi-Fi and reviewed P0/P1 fixes before CI."""
import hashlib,json,os,subprocess,sys,tomllib
from pathlib import Path
R=Path(__file__).resolve().parents[2];out=R/'artifacts/b5q-p3-work/pre-ci';out.mkdir(exist_ok=True)
checks=[]
def run(name,command):
    with (out/(name+'.log')).open('w')as f:r=subprocess.run(list(map(str,command)),cwd=R,stdout=f,stderr=subprocess.STDOUT)
    if r.returncode:print((out/(name+'.log')).read_text()[-5000:]);raise SystemExit('FAIL '+name)
    checks.append(dict(name=name,passed=True,command=list(map(str,command))));print('PASS',name,flush=True)
run('P0-P1-all-preserved-baselines',[sys.executable,R/'scripts/b5q-install/pre-ci-p0-p1.py'])
for name in ['bt-fifo','bt-wcn6855','bt-string-compat','wcn-power','wifi-platform','wifi-diagnostics','pcie-controller','pcie-firmware-dma','ath11k-qca6490','wireless-review-fixes','wireless-source-pins']:
    run(name,[sys.executable,R/'tests/b5q-ufs'/('test-'+name+'.py')])
run('native-userland-and-firmware-identities',[sys.executable,R/'scripts/b5q-install/check-wireless-userland.py'])
run('Bluetooth-target',[sys.executable,R/'scripts/b5q-install/check-bt-target.py'])
command=[sys.executable,R/'UniXNU-b5q/scripts/build-b5q-wifi.py','--module',R/'sources/UniXNU-sheng/drivers/Ath12kWifi','--out',R/'artifacts/b5q-p3-work/target',
    '--compiler',R/'tools/llvm21/usr/lib/llvm-21/bin/clang','--llvm',R/'tools/llvm21/usr/lib/llvm-21/bin','--jobs','4']
envLibrary=os.environ.get('LD_LIBRARY_PATH');os.environ['LD_LIBRARY_PATH']=str(R/'tools/llvm21/usr/lib/x86_64-linux-gnu')
run('ath11k-full-shared-target',command)
if envLibrary is None:os.environ.pop('LD_LIBRARY_PATH',None)
else:os.environ['LD_LIBRARY_PATH']=envLibrary
for name,script in [('WiFi-board-and-network-target','check-wifi-target.py'),('original-network-ABI','check-wifi-ethernet-abi.py'),
    ('shared-production-runtime-regressions','test-wireless-shared-host.py'),('firmware-and-loader-target','check-pcie-uefi-target.py'),
    ('joint-symbol-PAC-zero-apps-smmu','check-wireless-target-closure.py')]:run(name,[sys.executable,R/'scripts/b5q-install'/script])
run('all-XNU-patches',[sys.executable,R/'UniXNU-b5q/scripts/check-xnu-patches.py','--unixnu',R/'UniXNU','--source',R/'sources/UniXNU/out/feeds/xnu-3199e8bc'])
board=tomllib.loads((R/'UniXNU-b5q/board.toml').read_text());args=board['payload']['kernel_args']
assert 'wifi=5'in args and 'bluetooth=1'in args and len(' '.join(args).encode())<=1000
assert 'offline-mobile-graphics-client=1'not in args and len(board['payload']['text_fixups'])==2
assert board['adt']['chosen']['asmb']['u64']['lp-sip0']==2
assert board['adt']['chosen']['u32']['b5q-pcie-dma-ready']==0
assert bytes.fromhex(board['adt']['chosen']['bytes']['b5q-pcie-dma-state'])==bytes(88)
source=[*sorted((R/'UniXNU-b5q/package').rglob('*.[ch]')),*sorted((R/'UniXNU-b5q/package').rglob('*.cpp')),
    *sorted((R/'UniXNU-b5q/scripts').glob('*.py')),*sorted((R/'patches/uefi-b5q').glob('*.patch')),R/'UniXNU-b5q/board.toml',R/'.github/workflows/b5q-p0-p5.yml']
report=dict(passed=True,checks=checks,hardware_verified=False,P2_P3_joint_required=True,
    completed_local_only=True,full_CI_signing_and_returned_images_required=True,
    source_sha256={str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest()for p in source})
(out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print('PASS complete P2+P3 local gate; next: one joint CI and actual-image acceptance')
