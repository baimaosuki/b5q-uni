#!/usr/bin/env python3
"""Compile the complete shared Adreno implementation; do not import sheng board tables."""
import hashlib,json,subprocess
from b5q_compile import ROOT,compile,archive,report
out=ROOT/'build/adreno740';out.mkdir(parents=True,exist_ok=True)
# These are shared SoC protocol types, not Xiaomi power votes or physical reservations.
includes=[]
for path in ['kits/Sm8550Platform','kits/AdrenoFirmware','kits/AdrenoPM4','kits/ArmSmmu4K','drivers/Adreno740','.cache/xnu-work/osfmk']:
 includes+=['-I',str(ROOT/path)]
sources=sorted(p for p in (ROOT/'drivers/Adreno740').glob('NativeAdreno*.cpp') if p.name!='NativeAdrenoAccelerator.cpp')
# Do not compile ShengGmu.c: it requires Xiaomi-generated register rules.
# Without those headers the shared GPU service excludes cold-start code.
# All generic C++ implementation and firmware/PM4/SMMU parsers remain real.
sources += [ROOT/'kits/AdrenoFirmware'/name for name in ['AdrenoHfi.c','AdrenoHfiStartup.c','AdrenoHfiVotes.c','AdrenoFirmware.c']]
sources += sorted((ROOT/'kits/ArmSmmu4K').glob('ArmSmmu4K*.c'))+[ROOT/'kits/AdrenoPM4/AdrenoPM4.c']
sources += [ROOT/'kits/b5q/B5qGpu.cpp']
includes += ['-I',str(ROOT/'kits/b5q')]
# No generated board address/rate headers and no Xiaomi signed firmware.
for forbidden in ['ShengGmuSource.h','ShengGmuVotesSource.h','ShengGmuCommandDbSource.h']:
 if any((ROOT/path/forbidden).exists() for path in ['kits/b5q','build/adreno740']):raise SystemExit('Unexpected board-specific generated header '+forbidden)
trace=hashlib.sha256()
for p in sources:trace.update(p.name.encode());trace.update(p.read_bytes())
trace_id=trace.hexdigest()[:16]
objects=[compile(p,out/(p.stem+('.kit.o' if p.suffix=='.c' else '.o')),includes,['-DNATIVE_GPU_BUILD_ID=0x'+trace_id+'ULL']) for p in sources]
path=archive(out/'libAdreno740.a',objects)
# The original macOS IOAccelerator ABI is bound by the shared audited builder.
subprocess.run(['python3',str(ROOT/'scripts/build-adreno740-accelerator.py')],check=True)
report(path,objects,sources,dict(board_power_votes=False,signed_firmware_embedded=False,accelerator_abi='shared audited macOS binder'))
print('PASS: complete shared Adreno archive; absent board inputs remain explicit runtime refusal')
