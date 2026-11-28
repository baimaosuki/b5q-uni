#!/usr/bin/env python3
"""Complete New Batch2 local checks before its cached-core CI build."""
import hashlib,json,os,subprocess,sys,tempfile,tomllib,plistlib,importlib.util
from pathlib import Path
R=Path(__file__).resolve().parents[2];W=R/'artifacts/b5q-batch2-work';W.mkdir(exist_ok=True)
checks=[]
env=dict(os.environ,PATH='/usr/lib/llvm-17/bin:'+os.environ['PATH'])
def run(name,cmd,extra=None):
 e=dict(env);e.update(extra or {})
 with (W/(name+'.log')).open('w')as f:r=subprocess.run(list(map(str,cmd)),cwd=R,stdout=f,stderr=subprocess.STDOUT,env=e)
 if r.returncode:print((W/(name+'.log')).read_text()[-5000:]);raise SystemExit('FAIL '+name)
 checks.append(dict(name=name,passed=True));print('PASS '+name,flush=True)
run('records',[sys.executable,'UniXNU/scripts/porting-record.py','check','--device','UniXNU-b5q'])
run('memory-model',[sys.executable,'scripts/b5q-install/check-batch2-memory.py'],{'LD_PRELOAD':'/usr/lib/llvm-17/lib/clang/17/lib/linux/libclang_rt.ubsan_standalone-x86_64.so'})
for name in ('batch2-contract','data-queue','data-installer','data-partition','data-grow','installer','absentd-v33','data-account','log-startup','log-writer'):
 run(name,[sys.executable,'tests/b5q-ufs/test-'+name+'.py'])
with tempfile.TemporaryDirectory(prefix='b5q-batch2-host-')as td:
 for name in ('pointer-batch2','proctop'):
  exe=Path(td)/name
  run(name+'-compile',['c++','-std=c++17','-Wall','-Wextra','-Werror','-pthread','-fsanitize=address,undefined','-I',R/'UniXNU-b5q/package',R/('tests/b5q-ufs/test-'+name+'.cpp'),'-o',exe])
  run(name+'-ASan-UBSan',[exe])
S=R/'artifacts/b5q-runtime-v33-work'
run('native-launchd',[sys.executable,'scripts/b5q-install/check-macos-launchd-policy.py','--launchd',S/'root/sbin/launchd','--rootless',S/'root/System/Library/Sandbox/com.apple.xpc.launchd.rootless.plist','--policy',R/'UniXNU-b5q/package/b5q-launchd-lite.json','--report',W/'native-launchd.json'])
run('native-XPC-five-jobs',[sys.executable,'scripts/b5q-install/check-absentd-lifecycle.py','--root',S/'root','--cache',R/'inputs/macos-27.3-26C5035r/shared-cache/dyld_shared_cache_arm64e','--report',W/'absent-lifecycle.json'])
run('target',[sys.executable,'scripts/b5q-install/check-peripheral-target.py','--sources','NativeHidInput.cpp,HidInputProbe.cpp,B5qProcTop.c,B5qRamStorage.cpp,B5qPower.cpp,B5qUfs.cpp','--reference','artifacts/b5q-esp-batch1-final/esp.img','--objects-out',W/'objects'])
run('objects',[sys.executable,'scripts/b5q-install/check-batch2-objects.py','--objects',W/'objects','--baseline',W/'pac','--out',W/'batch2-objects.json'])
run('proctop-PAC',[sys.executable,'scripts/b5q-install/check-proctop-pac.py','--object',W/'objects/B5qProcTop.o','--core-objects',S/'pac','--out',W/'proctop-pac.json'])
# The producer is the newly compiled HID object; every other endpoint is
# extracted from the unchanged source cache, not recompiled for this audit.
import shutil
shutil.copyfile(W/'objects/NativeHidInput.o',W/'pac/NativeHidInput.o')
run('cross-object-PAC',[sys.executable,'scripts/b5q-install/check-usb-gmu-pac.py','--usb',W/'pac/QcomDwc3.o','--armcpu',W/'pac/ArmCpu.o','--gpu',W/'pac/B5qGpu.o','--gmu',W/'pac/ShengGmu.kit.o','--extended-dir',W/'pac','--out',W/'full-pac.json'])
b=tomllib.loads((R/'UniXNU-b5q/board.toml').read_text());assert b['adt']['chosen']['asmb']=={'u64':{'lp-sip0':2}}
assert b['payload']['adt']['persistent_data'] and int(b['payload']['adt']['owned_memory_size'],0)==6<<30
args=b['payload']['kernel_args'];assert any(x in args for x in ('b5q-data-ufs=1','b5q-data-ufs=2')) and 'b5q-psci-reset=1'in args and not any(x.startswith('offline-mobile-graphics-client=')for x in args)
assert (R/'UniXNU-b5q/scripts/package.sh').read_bytes()==(R/'UniXNU/templates/package.sh').read_bytes()
assert hashlib.sha256((R/'UniXNU-b5q/inputs/DarwinBoot-v30.efi').read_bytes()).hexdigest()=='100080919035179c86c1f4b1eee16e6a8a46166beee95234dc2c842995009cde'
import yaml
workflow=yaml.safe_load((R/'.github/workflows/b5q-new-batch2.yml').read_text());commands='\n'.join(x.get('run','')for x in workflow['jobs']['incremental']['steps'])
assert '--version batch2'in commands and '45047962341'in commands and 'build-persistent-data.py'in commands and 'package-batch2-esp.py'in commands
assert not any(x in commands for x in ('unixnu build xnu','unixnu build firmware','build-mesa','44983031320'))
checks.append(dict(name='Batch1-inheritance-v30-loader-dedicated-incremental-workflow',passed=True))
report=dict(passed=True,checks=checks,core_recompiled=False,GPU_recompiled=False,UEFI_recompiled=False,board_objects=6,persistent_APFS='grow existing Batch1 volume; native CI result and final readback still required',hardware_qualified=False)
(W/'pre-ci.json').write_text(json.dumps(report,indent=2)+'\n');print('PASS New Batch2 complete local preflight',len(checks),'groups')
