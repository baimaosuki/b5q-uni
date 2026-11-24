#!/usr/bin/env python3
"""Compile shared SM8550 operations with generated Samsung b5q inputs."""
import hashlib,json,subprocess,os,shutil
from b5q_compile import ROOT,compile,archive,report
from pathlib import Path
out=ROOT/'build/adreno740';out.mkdir(parents=True,exist_ok=True)
reuse=os.environ.get('B5Q_REUSE_ADRENO')
if reuse:
 # The pinned completed archive and its inputs are qualified locally before
 # submission. This is archive reuse, not a claim that it was recompiled.
 source=Path(reuse)
 shutil.copyfile(source,out/'libAdreno740.a')
 # Reuse every GPU/GMU/Turnip binary except this one register-map helper.
 # Explicit Inhibit replaces its ambiguous default; replay the real core
 # C++ record and verify that ar changed exactly the intended member.
 from b5q_adreno_mmio import prepare
 original=ROOT/'drivers/Adreno740/NativeAdrenoGmuService.cpp'
 adapted=prepare(original,out/original.name)
 member='NativeAdrenoGmuService.o';target=out/member;path=out/'libAdreno740.a'
 names=subprocess.check_output(['xcrun','ar','t',str(path)],text=True).splitlines();assert names.count(member)==1
 before={n:hashlib.sha256(subprocess.check_output(['xcrun','ar','p',str(path),n])).hexdigest()for n in names}
 compile(adapted,target,['-iquote',str(original.parent),'-I',str(ROOT/'.cache/xnu-work/osfmk')])
 subprocess.run(['xcrun','ar','r',str(path),str(target)],check=True)
 assert subprocess.check_output(['xcrun','ar','t',str(path)],text=True).splitlines()==names,'GPU archive member list changed'
 after={n:hashlib.sha256(subprocess.check_output(['xcrun','ar','p',str(path),n])).hexdigest()for n in names}
 assert set(before)==set(after)and all(before[n]==after[n]for n in names if n!=member)and before[member]!=after[member]
 (out/'mmio-helper.json').write_text(json.dumps(dict(passed=True,only_recompiled_member=member,
     original_source_sha256=hashlib.sha256(original.read_bytes()).hexdigest(),adapted_source_sha256=hashlib.sha256(adapted.read_bytes()).hexdigest(),
     source_archive_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),members_before=before,members_after=after),indent=2)+'\n')
 (out/'reuse.json').write_text(json.dumps({'source_run':44837528408,'archive_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'source_archive_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'recompiled_members':[member],'other_members_unchanged':True},indent=2)+'\n')
 print('Reused qualified Adreno archive; only register-map cache helper recompiled')
 raise SystemExit(0)
# These are shared SoC protocol types, not Xiaomi power votes or physical reservations.
includes=[]
for path in ['kits/Sm8550Platform','kits/AdrenoFirmware','kits/AdrenoPM4','kits/ArmSmmu4K','drivers/Adreno740','.cache/xnu-work/osfmk']:
 includes+=['-I',str(ROOT/path)]
sources=sorted(p for p in (ROOT/'drivers/Adreno740').glob('NativeAdreno*.cpp') if p.name!='NativeAdrenoAccelerator.cpp')
sources += [ROOT/'kits/Sm8550Platform'/name for name in ['ShengGmu.c','ShengGpuSmmu.c','ShengGmuCommandDb.c']]
sources += [ROOT/'kits/b5q/B5qGmuVotes.c']
sources += [ROOT/'kits/AdrenoFirmware'/name for name in ['AdrenoHfi.c','AdrenoHfiStartup.c','AdrenoHfiVotes.c','AdrenoFirmware.c']]
sources += sorted((ROOT/'kits/ArmSmmu4K').glob('ArmSmmu4K*.c'))+[ROOT/'kits/AdrenoPM4/AdrenoPM4.c']
sources += [ROOT/'kits/b5q/B5qGpu.cpp']
includes += ['-I',str(ROOT/'kits/b5q'),'-I',str(ROOT/'kits/b5q/Sm8550Inputs')]
# Keep upstream source intact. The service's fence helper must use b5q's GMU
# register-window origin, matching the generated SM8550 kit input.
for name in ['NativeAdrenoService.cpp','NativeAdrenoTimer.cpp','NativeAdrenoGmuService.cpp']:
 source=ROOT/'drivers/Adreno740'/name;adapted=out/name;text=source.read_text()
 if name=='NativeAdrenoService.cpp':
  text=text.replace('0x23b14u*4u-0x6a000u','0x23b14u*4u-SHENG_GMU_CORE_GPU_DELTA').replace('0x23b13u*4u-0x6a000u','0x23b13u*4u-SHENG_GMU_CORE_GPU_DELTA')
 elif name=='NativeAdrenoGmuService.cpp':
  text=text.replace('memory->map(kIOMapAnywhere)','memory->map(kIOMapAnywhere|kIOMapInhibitCache)')
 else:
  text='#include "ShengGmuSource.h"\n'+text.replace('TimerGmuLow = 0x14220','TimerGmuLow = (0x1f888u*4u)-SHENG_GMU_CORE_GPU_DELTA').replace('TimerGmuHigh = 0x14224','TimerGmuHigh = (0x1f889u*4u)-SHENG_GMU_CORE_GPU_DELTA')
 adapted.write_text(text);sources=[adapted if p==source else p for p in sources]
trace=hashlib.sha256()
for p in sources:trace.update(p.name.encode());trace.update(p.read_bytes())
trace_id=trace.hexdigest()[:16]
objects=[compile(p,out/(p.stem+('.kit.o' if p.suffix=='.c' else '.o')),includes,['-DNATIVE_GPU_BUILD_ID=0x'+trace_id+'ULL']) for p in sources]
path=archive(out/'libAdreno740.a',objects)
# The original macOS IOAccelerator ABI is bound by the shared audited builder.
subprocess.run(['python3',str(ROOT/'scripts/build-adreno740-accelerator.py')],check=True)
report(path,objects,sources,dict(board_power_votes='Samsung common OPP intersection',signed_firmware_embedded=False,firmware_input='validated original Samsung ADT properties',accelerator_abi='shared audited macOS binder'))
print('Built shared SM8550 GMU/HFI/SMMU/command-db and b5q platform archive')
