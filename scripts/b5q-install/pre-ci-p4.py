#!/usr/bin/env python3
"""Complete production P4A/B/C and retained baseline gates before one CI."""
from pathlib import Path
import hashlib,json,os,subprocess,sys,tomllib
R=Path(__file__).resolve().parents[2];out=R/'artifacts/b5q-p4-work/pre-ci';out.mkdir(exist_ok=True);checks=[]
def run(name,cmd):
 with(out/(name+'.log')).open('w')as f:p=subprocess.run(list(map(str,cmd)),cwd=R,stdout=f,stderr=subprocess.STDOUT)
 if p.returncode:print((out/(name+'.log')).read_text()[-4000:]);raise SystemExit('FAIL '+name)
 checks.append(dict(name=name,passed=True,command=list(map(str,cmd))));print('PASS',name,flush=True)
for name in ['fuel-gauge','panel-lid','p4-pmic-sharing','media-dma','media-loader','media-producer','media-firmware','tfa-container','tfa9878','audio-tdm','audio-queue','audio-math','audio-lifecycle','audio-hal','media-runtime','video-pool','feature-selection','feature-menu']:
 run(name,[sys.executable,R/'tests/b5q-ufs'/('test-'+name+'.py')])
run('production-target',[sys.executable,R/'scripts/b5q-install/check-p4a-target.py','--adsp','--video','--audio-protocol','--audio-service'])
for name,cmd in [('joint-symbol-vtable-zeroMMIO',['check-media-target-closure.py']),('all-callback-PAC',['check-media-callback-pac.py']),('firmware-tenpatch-reconstruction',['check-stage-firmware-inputs.py','--media','--out',str(out/'firmware-inputs.json')]),('actual-EDK2-target',['check-pcie-uefi-target.py','--media'])]:
 run(name,[sys.executable,R/'scripts/b5q-install'/cmd[0],*cmd[1:]])
run('all-retained-P0-P1-P2-P3-baselines',[sys.executable,R/'scripts/b5q-install/pre-ci-p2-p3.py'])
b=tomllib.loads((R/'UniXNU-b5q/board.toml').read_text());chosen=b['adt']['chosen'];assert chosen['u32']['b5q-feature-mask']==61
for name in ['audio','video']:
 assert chosen['u32']['b5q-'+name+'-dma-ready']==0
 assert bytes.fromhex(chosen['bytes']['b5q-'+name+'-dma-state'])==bytes(104)
assert b['payload']['runtime']['tool']=='scripts/build-b5q-media-runtime.py'
assert not any(x.split('=')[0]in ['audio','adsp','sheng-video','battery','backlight','lid','b5q-f']for x in b['payload']['kernel_args'])
files=[*sorted((R/'UniXNU-b5q/package').rglob('*.[ch]')),*sorted((R/'UniXNU-b5q/package').rglob('*.cpp')),*sorted((R/'UniXNU-b5q/scripts').glob('*.py')),*sorted((R/'patches/uefi-b5q').glob('*.patch')),R/'UniXNU-b5q/board.toml',R/'.github/workflows/b5q-p0-p5.yml']
(out/'report.json').write_text(json.dumps(dict(passed=True,hardware_verified=False,checks=checks,native_Apple_link_sign_and_returned_CI_images_required=True,source_sha256={str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest()for p in files}),indent=2)+'\n')
print('PASS complete P4 local gate; nativeApplelink/sign/fullCI/returnedimage acceptance next')
