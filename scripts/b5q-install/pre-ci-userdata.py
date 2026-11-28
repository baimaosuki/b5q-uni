#!/usr/bin/env python3
"""Local gates for minimum-change userdata Data; compile exactly two objects."""
import hashlib,importlib.util,json,os,shutil,subprocess,sys,tomllib
from pathlib import Path
R=Path(__file__).resolve().parents[2];W=R/'artifacts/b5q-userdata-work';W.mkdir(exist_ok=True)
checks=[]
def run(name,args,env=None):
 with (W/(name+'.log')).open('w')as f:result=subprocess.run(list(map(str,args)),cwd=R,stdout=f,stderr=subprocess.STDOUT,env=env)
 if result.returncode:print((W/(name+'.log')).read_text()[-4000:]);raise SystemExit('FAIL '+name)
 checks.append(dict(name=name,passed=True));print('PASS '+name,flush=True)
run('records',[sys.executable,'UniXNU/scripts/porting-record.py','check','--device','UniXNU-b5q'])
for name in ['data-partition','data-queue','data-installer','userdata-installer','batch2-contract','installer','data-grow']:
 run(name,[sys.executable,'tests/b5q-ufs/test-'+name+'.py'])
run('layout',[sys.executable,'scripts/b5q-install/plan-macos-only.py'])
run('two-storage-target',[sys.executable,'scripts/b5q-install/check-peripheral-target.py','--sources','B5qRamStorage.cpp,B5qUfs.cpp','--reference','artifacts/b5q-esp-new-batch2/esp.img','--objects-out',W/'objects'])
base=R/'artifacts/b5q-batch2-work/ci45108577992';combined=W/'combined-objects';combined.mkdir(exist_ok=True)
for name in ['NativeHidInput.o','HidInputProbe.o','B5qProcTop.o','B5qPower.o']:
 source,=base.rglob(name);shutil.copyfile(source,combined/name)
for source in (W/'objects').glob('*.o'):shutil.copyfile(source,combined/source.name)
run('storage-PAC-zero-SMMU',[sys.executable,'scripts/b5q-install/check-batch2-objects.py','--objects',combined,'--baseline','artifacts/b5q-batch2-work/pac','--out',W/'objects-PAC.json'])
board=tomllib.loads((R/'UniXNU-b5q/board.toml').read_text());args=board['payload']['kernel_args'];assert 'b5q-data-ufs=2'in args and len(' '.join(args).encode('ascii'))==981
assert board['adt']['chosen']['asmb']=={'u64':{'lp-sip0':2}} and int(board['payload']['adt']['owned_memory_size'],0)==6<<30
import yaml
workflow=yaml.safe_load((R/'.github/workflows/b5q-macos-only-userdata.yml').read_text());commands='\n'.join(s.get('run','')for s in workflow['jobs']['incremental']['steps'])
assert '--version userdata'in commands and '--changed B5qRamStorage.cpp,B5qUfs/B5qUfs.cpp'in commands and '--blocks 44188919'in commands
assert not any(x in commands for x in ['build xnu','build firmware','build-mesa','sgdisk','sfdisk','parted'])
for s in workflow['jobs']['incremental']['steps']:
 if 'run'in s:subprocess.run(['bash','-n'],input=s['run'],text=True,check=True)
assert hashlib.sha256((R/'UniXNU-b5q/inputs/DarwinBoot-v30.efi').read_bytes()).hexdigest()=='100080919035179c86c1f4b1eee16e6a8a46166beee95234dc2c842995009cde'
layout=json.loads((R/'UniXNU-b5q/reports/macos-only-layout.json').read_text());assert layout['GPT_write_count']==0 and layout['GPT_entries_unchanged']==37 and not layout['root']['reflash_required']
# Exactly three package input files differ from the successfully linked Batch2.
record,=base.rglob('incremental-relink.json');previous=json.loads(record.read_text());changed={p for p,d in previous['source_sha256'].items()if hashlib.sha256((R/'UniXNU-b5q/package'/p).read_bytes()).hexdigest()!=d}
assert changed=={'B5qRamStorage.cpp','B5qUfs/B5qUfs.cpp','B5qUfs/B5qDataFormat.h'},changed
checks.append(dict(name='fixed-GPT-existing-root-Batch1-inheritance-981B-two-object-cache-workflow',passed=True))
result=dict(passed=True,checks=checks,package_source_changes=sorted(changed),board_objects=2,core_GPU_Mesa_UEFI_recompiled=False,device_access=False,final_CI_and_image_acceptance='pending')
(W/'pre-ci.json').write_text(json.dumps(result,indent=2)+'\n')
print('PASS userdata local preflight',len(checks),'groups; finalCI/IMGacceptance still required')
