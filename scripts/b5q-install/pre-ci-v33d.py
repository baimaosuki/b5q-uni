#!/usr/bin/env python3
"""Local-only v33d P0 review gate. Never builds an ESP, pushes, or calls GitHub."""
from pathlib import Path
import hashlib,json,os,subprocess,sys
R=Path(__file__).resolve().parents[2];W=Path(os.environ.get('B5Q_GATE_WORK',R/'artifacts/b5q-v33d-review2')).resolve();W.mkdir(parents=True,exist_ok=True);os.environ['B5Q_GATE_WORK']=str(W);checks=[]
def run(name,command):
 log=W/(name+'.log')
 with log.open('w')as out:r=subprocess.run(list(map(str,command)),cwd=R,stdout=out,stderr=subprocess.STDOUT)
 if r.returncode:raise SystemExit('FAIL '+name+'; '+str(log))
 checks.append(dict(name=name,passed=True,command=list(map(str,command)),log_sha256=hashlib.sha256(log.read_bytes()).hexdigest()));print('PASS',name,flush=True)
def py(name,path,*args):run(name,[sys.executable,R/path,*args])
baseline=R/'artifacts/b5q-p4-work/pre-ci/report.json'
x=json.loads(baseline.read_text())if baseline.is_file()else {}
if not x.get('passed')or any(not(R/n).is_file()or hashlib.sha256((R/n).read_bytes()).hexdigest()!=sha for n,sha in x.get('source_sha256',{}).items()):
 py('Bluetooth-provider','scripts/b5q-install/check-bt-target.py')
 py('wireless-mutex-provider','scripts/b5q-install/check-wifi-target.py')
 py('pre-ci-all','scripts/b5q-install/pre-ci-p4.py')
else:
 if not(W/'pre-ci-all.log').is_file():
  (W/'pre-ci-all.log').write_text('PASS complete P4 local gate; reused exact source-bound receipt '+str(baseline)+'\n')
 assert 'PASS complete P4 local gate'in(W/'pre-ci-all.log').read_text()
 checks.append(dict(name='complete-P0-P4-retained-regressions',passed=True,receipt_sha256=hashlib.sha256(baseline.read_bytes()).hexdigest(),source_bound=True))
# This gate has its own preserved assertions; do not alter them for a pass.
py('pre-ci-v33b','scripts/b5q-install/pre-ci-v33b.py')
for name in ['touch-p0','v33d-dma','v33d-usb-device','v33d-review2','v33d-wcn-init','v33d-packaging','v33d-review3','v33d-review4','v33d-reclaim-dma','review5','review5-firmware','review7','review8','review9','review11','review12','dp-loader','dp-dpu','review13']:py(name,'tests/b5q-ufs/test-'+name+'.py')
py('review14','scripts/b5q-install/test-review14.py')
py('review15','scripts/b5q-install/test-review15.py')
py('review16','scripts/b5q-install/test-review16.py')
run('loader-inputs',[
 'env','PATH=/usr/lib/llvm-17/bin:'+os.environ['PATH'],
 'LD_PRELOAD=/usr/lib/llvm-17/lib/clang/17/lib/linux/libclang_rt.ubsan_standalone-x86_64.so',
 sys.executable,R/'UniXNU/drivers/DarwinBoot/Test/test-loader-inputs.py'])
py('original-binaries','scripts/b5q-install/check-v33d-original-binaries.py')
py('target-compile','scripts/b5q-install/check-peripheral-target.py','--sources','QcomDwc3.cpp,NativeHidInput.cpp,B5qTouch.cpp,UsbProbe.cpp,QcomRpmh.c,SoftwareAesProbe.cpp,KeyStoreProbe.cpp,ThermalLevel.cpp,B5qPower.cpp,B5qGpu.cpp,ButtonProbe.cpp,GeniI2c.c,B5qUfs.cpp','--objects-out',W/'target','--reference',R/'artifacts/b5q-esp-v33b-repair2/esp.img')
py('firmware-reconstruction','scripts/b5q-install/check-stage-firmware-inputs.py','--media','--dp','--out',W/'firmware-inputs.json')
py('firmware-target','scripts/b5q-install/check-pcie-uefi-target.py','--media','--dp')
py('review4-target-proof','tests/b5q-ufs/test-v33d-review4-target.py')
base=R/'artifacts/b5q-p0-work/pac'
# The complete baseline compiled these same current board sources. Prove that
# its cross-object participants are the just-built objects, not older copies.
for name in ['QcomDwc3.o','NativeHidInput.o','B5qTouch.o']:assert (base/name).read_bytes()==(W/'target'/name).read_bytes(),name
py('wireless-all-callbacks','scripts/b5q-install/check-wireless-target-closure.py','--out',W/'wireless-closure.json')
py('wireless-ADSP-joint','scripts/b5q-install/check-wireless-target-closure.py','--with-adsp','--out',W/'wireless-ADSP-closure.json')
py('all-cross-object-PAC','scripts/b5q-install/check-usb-gmu-pac.py','--usb',W/'target/QcomDwc3.o','--armcpu',base/'ArmCpu.o','--gpu',base/'B5qGpu.o','--gmu',base/'ShengGmu.kit.o','--extended-dir',base,'--out',W/'all-PAC.json')
py('hid-timer-workloop-PAC','scripts/b5q-install/check-media-callback-pac.py','--dp','--hid',W/'target/NativeHidInput.o','--out',W/'hid-timer-PAC.json')
py('all-board-zero-EL1-SMMU','scripts/b5q-install/check-batch2-objects.py','--objects',R/'artifacts/b5q-p0-work/objects','--baseline',base,'--out',W/'zero-EL1-SMMU.json')
receipt=dict(passed=True,hardware_verified=False,checks=checks,push_performed=False,CI_triggered=False,ESP_created=False)
(W/'v33d-local-gates.json').write_text(json.dumps(receipt,indent=2)+'\n')
print('PASS local-only v33d P0 gate; STOP for owner review, no push/CI/ESP')
