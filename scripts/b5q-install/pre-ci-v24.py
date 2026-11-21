#!/usr/bin/env python3
"""Run the complete native v24 local checks before dispatching any CI."""
from pathlib import Path
import subprocess,json,tempfile,sys,tomllib,hashlib,shutil,yaml
root=Path(__file__).resolve().parents[2];work=root/'artifacts/b5q-runtime-v24-work';work.mkdir(exist_ok=True);checks=[]
def run(name,cmd):
 result=subprocess.run([str(x)for x in cmd],cwd=root,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
 (work/(name+'.log')).write_text(result.stdout)
 checks.append({'name':name,'exit_code':result.returncode,'log_sha256':hashlib.sha256(result.stdout.encode()).hexdigest()})
 print(('PASS 'if not result.returncode else'FAIL ')+name,flush=True)
 if result.returncode:print(result.stdout[-5000:]);(work/'pre-ci-v24.json').write_text(json.dumps({'passed':False,'checks':checks},indent=2)+'\n');raise SystemExit(result.returncode)
board=tomllib.loads((root/'UniXNU-b5q/board.toml').read_text());args=board['payload']['kernel_args']
for v in ['usb=1','buttons=1','touch=1','touch-hid=1','offline-hid-input=1','cpufreq=4','armcpu-edge=1','ci-mps=0','offline-mobile-graphics-client=1']:assert v in args,v
assert board['payload']['runtime']['data_gib']==4 and len(board['payload']['text_fixups'])==1
assert not any('cpufreq-cap='in x or'b5q-usb='in x or'b5q-usb-delay'in x for x in args)
for p in ['B5qUsbHost.cpp','B5qSpmi.cpp','B5qSpmi.h']:assert not(root/'UniXNU-b5q/package'/p).exists()
assert not any(x in (root/'UniXNU-b5q/package/QcomDwc3.cpp').read_text()for x in ['retimerInit','0x7fd','QcomUcsi'])
assert(root/'UniXNU-b5q/scripts/package.sh').read_bytes()==(root/'UniXNU/templates/package.sh').read_bytes()
yaml.safe_load((root/'.github/workflows/b5q-stage123.yml').read_text())
run('records',[sys.executable,'UniXNU/scripts/porting-record.py','check','--device','UniXNU-b5q'])
run('full-patch-sequence',[sys.executable,'UniXNU-b5q/scripts/check-xnu-patches.py','--unixnu','UniXNU','--source','sources/UniXNU/out/feeds/xnu-3199e8bc'])
for name in ['source-contract','lockdown-public','log-startup','log-writer','runtime-gates','ethernet-lifecycle','ethernet-start','read-status','log-read','verified-read','ws-signal','peripheral-policy','shared-gpu','v24-core','usb-irq','usb-delay','peripheral-steps','touch','touch-wait','volatile-data-4g','usb-inputs-v24','data-account']:
 run(name,[sys.executable,'tests/b5q-ufs/test-'+name+'.py'])
for name in ['test-v24-usb','test-touch-power']:
 with tempfile.TemporaryDirectory(prefix='b5q-native-preci-')as td:
  exe=Path(td)/name
  run(name+'-compile',['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-g','-IUniXNU-b5q/package','tests/b5q-ufs/'+name+'.cpp','-o',exe])
  run(name,[exe])
run('target-objects',[sys.executable,'scripts/b5q-install/check-peripheral-target.py','--native-recount','--objects-out',work/'objects'])
for n in ['B5qTouch.o','NativeHidInput.o','BoardClock.o','ButtonProbe.o','ThermalLevel.o']:shutil.copyfile(work/'objects'/n,work/'callback-objects'/n)
run('all-cross-object-PAC',[sys.executable,'scripts/b5q-install/check-usb-gmu-pac.py','--usb',work/'objects/QcomDwc3.o','--armcpu',work/'callback-objects/ArmCpu.o','--gpu',work/'objects/B5qGpu.o','--gmu',work/'callback-objects/ShengGmu.kit.o','--extended-dir',work/'callback-objects','--out',work/'cross-object-pac.json'])
for producer,name in [('B5qTouch.o','touch-geni-PAC'),('B5qUsbBoard.o','SE6-SE8-geni-PAC')]:run(name,[sys.executable,'scripts/b5q-install/check-geni-pac.py','--objects',work/'objects','--producer',producer,'--out',work/(name+'.json')])
compiled=json.loads((work/'target-objects.log').read_text().splitlines()[-1]);assert compiled['passed'] and compiled['new_core_linkage_pending']
expected=json.loads((work/'usb-dual-bindings.json').read_text());actual=json.loads((root/'UniXNU-b5q/scripts/usb-dual-bindings-26C5035r.json').read_text());assert actual==expected
run('POST-existing-binary',[sys.executable,'tests/b5q-ufs/test-post-seal.py','--kernel',root/'artifacts/b5q-runtime-v23-work/completed-cache/kernel/kernel.macho','--out',work/'post-seal-baseline.json'])
# Binary hashes bind the private, already-extracted Samsung inputs. No firmware
# bytes or environment secrets are included in these logs or in Git sources.
inputs=json.loads((root/'UniXNU-b5q/reports/samsung-gpu-inputs.json').read_text())
for n in ['gmu_gen70200.bin','a740_sqe.fw','a740_zap.mbn']:
 data=(root/'artifacts/firmware-b5q/F7310ZCS7EYF3/gpu'/n).read_bytes();assert len(data)==inputs['files'][n]['bytes']and hashlib.sha256(data).hexdigest()==inputs['files'][n]['sha256']
r={'passed':True,'checks':checks,'new_core_final_link_and_device_validation_pending':True,'target_objects':compiled,'ci_started':False}
(work/'pre-ci-v24.json').write_text(json.dumps(r,indent=2)+'\n');print('PASS complete native v24 local batch:',len(checks),'checks; final new XNU link is the CI build step')
