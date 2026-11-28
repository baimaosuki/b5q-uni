#!/usr/bin/env python3
"""P0 production touch regression and preserved desktop baseline gates."""
import hashlib,json,os,shutil,subprocess,sys,tempfile,tomllib
from pathlib import Path
R=Path(__file__).resolve().parents[2];W=R/'artifacts/b5q-p0-work';W.mkdir(exist_ok=True)
checks=[]
def run(name,args,extra=None):
 env=dict(os.environ);env.update(extra or {})
 with (W/(name+'.log')).open('w') as f:
  r=subprocess.run(list(map(str,args)),cwd=R,env=env,stdout=f,stderr=subprocess.STDOUT)
 if r.returncode:
  print((W/(name+'.log')).read_text()[-6000:]);raise SystemExit('FAIL '+name)
 checks.append(dict(name=name,passed=True));print('PASS '+name,flush=True)
run('records',[sys.executable,'UniXNU/scripts/porting-record.py','check','--device','UniXNU-b5q'])
for name in ['touch-p0','touch','touch-wait','data-volume-seed','data-queue','data-installer','data-partition',
             'userdata-installer','data-stream','image-hash-receipt','batch2-contract','installer','data-grow',
             'absentd-v33','data-account','log-startup','log-writer','shared-gpu','read-status','verified-read',
             'ethernet-lifecycle','ethernet-start','buttons-irq','ws-signal','v25-usb','v26-geni']:
 run(name,[sys.executable,'tests/b5q-ufs/test-'+name+'.py'])
run('memory-model',[sys.executable,'scripts/b5q-install/check-batch2-memory.py'],
    dict(PATH='/usr/lib/llvm-17/bin:'+os.environ['PATH'],LD_PRELOAD='/usr/lib/llvm-17/lib/clang/17/lib/linux/libclang_rt.ubsan_standalone-x86_64.so'))
with tempfile.TemporaryDirectory(prefix='b5q-p0-host-') as td:
 for name in ['pointer-batch2','proctop','touch-bus','touch-power']:
  exe=Path(td)/name
  run(name+'-compile',['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-pthread',
                     '-fsanitize=address,undefined','-I',R/'UniXNU-b5q/package',R/('tests/b5q-ufs/test-'+name+'.cpp'),'-o',exe])
  run(name+'-ASan-UBSan',[exe])
S=R/'artifacts/b5q-runtime-v33-work'
run('native-launchd',[sys.executable,'scripts/b5q-install/check-macos-launchd-policy.py',
 '--launchd',S/'root/sbin/launchd','--rootless',S/'root/System/Library/Sandbox/com.apple.xpc.launchd.rootless.plist',
 '--policy',R/'UniXNU-b5q/package/b5q-launchd-lite.json','--report',W/'native-launchd.json'])
run('native-XPC-five-jobs',[sys.executable,'scripts/b5q-install/check-absentd-lifecycle.py','--root',S/'root',
 '--cache',R/'inputs/macos-27.3-26C5035r/shared-cache/dyld_shared_cache_arm64e','--report',W/'absent-lifecycle.json'])
run('full-board-target',[sys.executable,'scripts/b5q-install/check-peripheral-target.py',
 '--reference',R/'artifacts/b5q-esp-data-mount-fix/esp.img','--objects-out',W/'objects','--native-recount'])
pac=W/'pac';pac.mkdir(exist_ok=True)
for src in (R/'artifacts/b5q-batch2-work/pac').iterdir():
 if src.is_file():shutil.copyfile(src,pac/src.name)
for src in (W/'objects').glob('*.o'):shutil.copyfile(src,pac/src.name)
run('all-cross-object-PAC',[sys.executable,'scripts/b5q-install/check-usb-gmu-pac.py',
 '--usb',pac/'QcomDwc3.o','--armcpu',pac/'ArmCpu.o','--gpu',pac/'B5qGpu.o','--gmu',pac/'ShengGmu.kit.o',
 '--extended-dir',pac,'--out',W/'full-PAC.json'])
run('storage-PAC-zero-apps-smmu',[sys.executable,'scripts/b5q-install/check-batch2-objects.py',
 '--objects',W/'objects','--baseline',pac,'--out',W/'objects-PAC.json'])
board=tomllib.loads((R/'UniXNU-b5q/board.toml').read_text())
assert board['adt']['chosen']['asmb']=={'u64':{'lp-sip0':2}}
assert board['payload']['adt']['persistent_data'] and int(board['payload']['adt']['owned_memory_size'],0)==6<<30
assert 'b5q-data-ufs=2' in board['payload']['kernel_args']
assert 'offline-mobile-graphics-client=1' not in board['payload']['kernel_args']
assert len(board['payload']['text_fixups'])==2
assert (R/'UniXNU-b5q/scripts/package.sh').read_bytes()==(R/'UniXNU/templates/package.sh').read_bytes()
checks.append(dict(name='preserved-SIP-memory-persistent-Data-GPU-boot-policy-template',passed=True))
import yaml
workflow=yaml.safe_load((R/'.github/workflows/b5q-p0-p5.yml').read_text())
assert set(workflow['jobs'])=={'kernel','firmware'}
commands='\n'.join(s.get('run','') for j in workflow['jobs'].values() for s in j['steps'])
for required in ['build kernel','build firmware','build-b5q-payload.py','shutil.rmtree(reused.parent/\'kernel\')']:
 assert required in commands,required
assert 'package-batch2-esp.py' not in commands,'Final ESP must wait for local returned-binary gates'
assert 'build-persistent-data.py' not in commands and 'Create fresh' not in commands
for job in workflow['jobs'].values():
 for step in job['steps']:
  if 'run' in step:subprocess.run(['bash','-n'],input=step['run'],text=True,check=True)
checks.append(dict(name='full-kernel-UEFI-builds-with-preserved-seed-and-no-initialization',passed=True))
report=dict(passed=True,checks=checks,hardware_qualified=False,full_kernel_UEFI_and_returned_images='pending',
 source_sha256={str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest() for p in
 [*sorted((R/'UniXNU-b5q/package').rglob('*.[ch]')),*sorted((R/'UniXNU-b5q/package').rglob('*.cpp')),R/'UniXNU-b5q/board.toml']})
(W/'pre-ci.json').write_text(json.dumps(report,indent=2)+'\n')
print('PASS P0 local preflight',len(checks),'groups; full kernel/UEFI and returned image gates remain')
