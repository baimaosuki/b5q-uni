#!/usr/bin/env python3
"""Audit returned Batch2 object instructions, storage ABI and platform PAC."""
import argparse,importlib.util,json,struct,subprocess,sys,hashlib,re,os
from pathlib import Path
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'UniXNU-b5q/scripts'))
from b5q_abi import macho,object_symbols,object_vtable
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--objects',type=Path,required=True);p.add_argument('--baseline',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
s=importlib.util.spec_from_file_location('pacscan',R/'scripts/b5q-install/check-proctop-pac.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
files=list(a.objects.glob('*.o'));assert len(files)>=6
reports={}
objdump=R/'tools/llvm21/usr/lib/llvm-21/bin/llvm-objdump'
for f in files:
 d=m.scan(f);values={}
 for i in d['instructions']:
  op=i.op_str.replace(' ','').split(',')
  if i.mnemonic in ('mov','movz','movn','movk')and len(op)>=2 and op[1].startswith('#'):
   reg='x'+op[0][1:];imm=int(op[1][1:],0);shift=int(op[2].removeprefix('lsl#'),0)if len(op)>2 else 0
   v=(values.get(reg,0)&~(65535<<shift))|(imm<<shift)if i.mnemonic=='movk'else ~(imm<<shift)if i.mnemonic=='movn'else imm<<shift
   values[reg]=v&((1<<(32 if op[0][0]=='w'else 64))-1)
   assert not 0x15000000<=values[reg]<0x150d0000,(f,i.address,i.mnemonic,i.op_str)
  elif i.mnemonic in ('ret','retab','bl','blr','blraa','braa')or i.mnemonic.startswith('b.'):values.clear()
 assert not any('smmu_configure_bypass' in n or 'smmu_plan_bypass' in n for n,_,_ in d['symbols'])
 if objdump.is_file():
  env=dict(os.environ,LD_LIBRARY_PATH=str(objdump.parents[3]/'lib/x86_64-linux-gnu'))
  with (a.out.parent/(f.stem+'.disasm')).open('w')as out:subprocess.run([str(objdump),'--macho','--disassemble',str(f)],stdout=out,check=True,env=env)
 reports[f.name]=dict(sha256=d['sha256'],instructions=len(d['instructions']),apps_smmu_materializations=0)
power=m.scan(a.objects/'B5qPower.o');core=m.scan(a.baseline/'IOPlatformExpert.cpo')
site=power['signed']['__ZL16b5qPlatformPowerj'];assert all(x['key']==0 and x['diversity']==0xba5 and not x['address_diversity']for x in site)
consumer=[]
for n,i in enumerate(core['instructions']):
 if i.mnemonic in ('braa','blraa')and n and core['instructions'][n-1].op_str=='x17, #0xba5':consumer.append(hex(i.address))
assert consumer
raw=(a.objects/'B5qUfs.o').read_bytes();sy=object_symbols(raw)
def vtable(name):
 va=next(v for n,v,k in sy if n==name);end=min(v for n,v,k in sy if v>va and k&0xe)
 return object_vtable(raw,sy,name,(end-va)//8-2)
dt,root=vtable('__ZTV12B5qDataBlock'),vtable('__ZTV12B5qRootBlock');assert len(dt)==len(root)
checked=0
for idx,(x,y)in enumerate(zip(dt,root)):
 if x is not None and y is not None:
  assert x[1]>>32==y[1]>>32,(idx,x,y);checked+=1
assert checked>200
ufs=m.scan(a.objects/'B5qUfs.o');completion=[c for c in ufs['calls']if c['diversity']==0xe90c];assert len(completion)>=2
result=dict(passed=True,objects=reports,platform_power_PAC=dict(key='IA',diversity='0x0ba5',producer=site,core_consumer_sites=consumer),data_root_shared_virtual_slots_verified=checked,Data_and_root_completion_PAC=dict(diversity='0xe90c',calls=completion),hardware_execution_tested=False)
a.out.write_text(json.dumps(result,indent=2)+'\n');print('PASS',len(files),'objects: zero EL1 apps_smmu; power PAC IA0ba5; storage virtual slots',checked,'and completion PAC match')
