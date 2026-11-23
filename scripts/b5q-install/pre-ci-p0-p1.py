#!/usr/bin/env python3
"""Mandatory joint P0+P1 source, hardware-input, production and ABI gates."""
import hashlib,json,os,subprocess,sys,tempfile
from pathlib import Path
R=Path(__file__).resolve().parents[2];W=R/'artifacts/b5q-p1-work';W.mkdir(exist_ok=True)
checks=[]
def run(name,args):
 with (W/(name+'.log')).open('w')as f:
  result=subprocess.run(list(map(str,args)),cwd=R,stdout=f,stderr=subprocess.STDOUT)
 if result.returncode:print((W/(name+'.log')).read_text()[-6000:]);raise SystemExit('FAIL '+name)
 checks.append(dict(name=name,passed=True));print('PASS '+name,flush=True)
run('P0-and-all-desktop-baselines',[sys.executable,'scripts/b5q-install/pre-ci-p0.py'])
for name in ['usb-p1','v32-boot-typec','usb-inputs-v24','usb-irq','usb-families','v25-usb','v26-geni']:
 run(name,[sys.executable,'tests/b5q-ufs/test-'+name+'.py'])
run('firmware-input-closure',[sys.executable,'scripts/b5q-install/check-stage-firmware-inputs.py','--out',W/'firmware-inputs.json'])
with tempfile.TemporaryDirectory(prefix='b5q-p1-firmware-test-')as td:
 exe=Path(td)/'usb-dma'
 includes=[R/'uefi-b5q/Platforms/Samsung/b5qPkg/Include',R/'uefi-b5q/Platforms/Samsung/b5qPkg/Drivers/B5qHandoffDxe',R/'UniXNU/drivers/DarwinBoot/DarwinBootPkg/Driver']
 run('firmware-DMA-compile',['cc','-std=gnu11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',*[x for p in includes for x in ['-I',p]],R/'tests/b5q-ufs/test-usb-firmware-dma.c','-o',exe])
 run('firmware-DMA-ASan-UBSan',[exe])
previous=json.loads((R/'artifacts/b5q-p0-work/pre-ci.json').read_text())
report=dict(passed=True,P0_baseline_checks=previous['checks'],joint_checks=checks,
 hardware_qualification='HOST_VERIFIED_PENDING_HARDWARE',P0_P1_both_required_before_CI=True,
 input_sha256={str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest()for p in
 [R/'UniXNU-b5q/package/QcomDwc3.cpp',R/'UniXNU-b5q/package/B5qUsbBoard.cpp',R/'UniXNU-b5q/package/B5qMax77705.h',
  *sorted((R/'patches/uefi-b5q').glob('*.patch')),R/'UniXNU-b5q/scripts/check-b5q-uefi.py',R/'.github/workflows/b5q-p0-p5.yml']})
(W/'pre-ci.json').write_text(json.dumps(report,indent=2)+'\n')
print('PASS mandatory P0+P1 joint preflight:',len(previous['checks']),'baseline groups +',len(checks)-1,'P1 groups; next gate is one joint CI and actual images')
