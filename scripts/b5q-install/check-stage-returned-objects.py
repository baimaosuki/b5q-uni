#!/usr/bin/env python3
"""Check CI-built callbacks/zero-apps_smmu against actual new core objects."""
import argparse,hashlib,importlib.util,json,shutil,subprocess,sys
from pathlib import Path
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'UniXNU-b5q/scripts'))
p=argparse.ArgumentParser(description=__doc__)
for key in ['ci','out']:p.add_argument('--'+key,type=Path,required=True)
a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
baseline=R/'artifacts/b5q-batch2-work/pac';origins={}
names=['QcomDwc3.o','ArmCpu.o','BoardClock.o','ArmDTPlatform.o','ButtonProbe.o','NativeHidInput.o','B5qTouch.o','ThermalLevel.o','IOUserClient.cpo']
for name in names:
 matches=list(a.ci.rglob(name));assert len(matches)==1,(name,matches)
 src=matches[0];shutil.copyfile(src,a.out/name);origins[name]=dict(source='actual new CI',path=str(src),sha256=hashlib.sha256(src.read_bytes()).hexdigest())
for name in ['B5qGpu.o','ShengGmu.kit.o']:
 src=baseline/name;shutil.copyfile(src,a.out/name);origins[name]=dict(source='unchanged reused GPU archive, prior qualified object',path=str(src),sha256=hashlib.sha256(src.read_bytes()).hexdigest())
subprocess.run([sys.executable,str(R/'scripts/b5q-install/check-usb-gmu-pac.py'),'--usb',str(a.out/'QcomDwc3.o'),
 '--armcpu',str(a.out/'ArmCpu.o'),'--gpu',str(a.out/'B5qGpu.o'),'--gmu',str(a.out/'ShengGmu.kit.o'),
 '--extended-dir',str(a.out),'--out',str(a.out/'callbacks.json')],check=True)
spec=importlib.util.spec_from_file_location('pacscan',R/'scripts/b5q-install/check-proctop-pac.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
checks={}
for path in sorted(a.ci.rglob('*.o')):
 # Core/platform objects legitimately contain other unrelated addresses;
 # apply this boundary to every newly returned b5q board/USB object.
 if not any(part in str(path)for part in ['/native-legacy-display/','/qcom-dwc3/']):continue
 scan=m.scan(path);values={}
 for ins in scan['instructions']:
  op=ins.op_str.replace(' ','').split(',')
  if ins.mnemonic in ('mov','movz','movn','movk')and len(op)>=2 and op[1].startswith('#'):
   reg='x'+op[0][1:];imm=int(op[1][1:],0);shift=int(op[2].removeprefix('lsl#'),0)if len(op)>2 else 0
   value=((values.get(reg,0)&~(65535<<shift))|(imm<<shift))if ins.mnemonic=='movk'else ~(imm<<shift)if ins.mnemonic=='movn'else imm<<shift
   values[reg]=value&((1<<(32 if op[0][0]=='w'else 64))-1)
   assert not 0x15000000<=values[reg]<0x150d0000,(str(path),hex(ins.address),ins.op_str)
  elif ins.mnemonic in ('ret','retab','bl','blr','blraa','braa')or ins.mnemonic.startswith('b.'):values.clear()
 assert not any('smmu_configure_bypass'in n or 'smmu_plan_bypass'in n for n,_,_ in scan['symbols'])
 checks[str(path.relative_to(a.ci))]=dict(sha256=scan['sha256'],instructions=len(scan['instructions']),apps_smmu_materializations=0)
assert len(checks)>=20
result=dict(passed=True,origins=origins,actual_new_board_objects=checks,hardware_PAuth_execution_tested=False)
(a.out/'report.json').write_text(json.dumps(result,indent=2)+'\n')
print('PASS actual CI callback PAC and',len(checks),'new board objects zero apps_smmu; GPU endpoints remain explicit cache reuse')
