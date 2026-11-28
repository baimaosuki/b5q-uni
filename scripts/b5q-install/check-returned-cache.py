#!/usr/bin/env python3
"""Prove Normal-WB mapping arguments in the actual arm64e machine code."""
import argparse,hashlib,importlib.util,json,struct,sys
from pathlib import Path
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'UniXNU-b5q/scripts'))
from b5q_abi import macho,object_symbols
spec=importlib.util.spec_from_file_location('pac',R/'scripts/b5q-install/check-proctop-pac.py');pac=importlib.util.module_from_spec(spec);spec.loader.exec_module(pac)
p=argparse.ArgumentParser();p.add_argument('--ci',type=Path);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
paths={}
for name,folder in [('B5qAudioDma.o','b5q-p4-work/target'),('B5qVideoMemory.o','b5q-p4-work/target'),('B5qWifiBoard.o','b5q-p3-work/board-target'),('B5qDpLink.o','b5q-p5-work/target')]:
 if a.ci:paths[name],=a.ci.rglob(name)
 else:paths[name]=R/'artifacts'/folder/name
proof={}
for name,path in paths.items():
 scan=pac.scan(path);ins=scan['instructions'];direct=[]
 for i,x in enumerate(ins):
  if x.mnemonic=='mov'and x.op_str in ('w1, #0x301','x1, #0x301'):
   window=ins[i+1:i+10]
   if any(k.mnemonic=='movk'and k.op_str.split(', ',1)[-1]=='#0x3ed6, lsl #48'for k in window)and any(k.mnemonic=='blraa'for k in window):
    direct.append(dict(options_site=hex(x.address),options='0x301 = Anywhere | Copyback',map_slot_PAC='IA3ed6',instructions=[k.mnemonic+' '+k.op_str for k in ins[i:i+10]]))
 if name!='B5qDpLink.o':assert direct,(name,'missing actual NormalWB map argument')
 else:
  # The non-inlined Window.open(base,bytes,cache) must receive0x300,
  # then pass cache|Anywhere to the same authenticated map slot.
  symbols=scan['symbols'];windows=[(n,v)for n,v,k in symbols if 'Window4openEyjj'in n and k&14]
  if direct:proof[name]=dict(sha256=scan['sha256'],direct=direct);continue
  assert len(windows)==1;symbol,start=windows[0];end=min(v for _,v,k in symbols if k&14 and v>start)
  body=[x for x in ins if start<=x.address<end];regs={'x3':'cache'};mapped=False
  for i,x in enumerate(body):
   op=x.op_str.replace(' ','').split(',');norm=lambda v:'x'+v[1:]if v.startswith(('x','w'))else v
   if x.mnemonic=='mov'and len(op)==2:regs[norm(op[0])]=regs.get(norm(op[1]),op[1])
   elif x.mnemonic=='orr'and len(op)==3:
    regs[norm(op[0])]=('cache|1'if regs.get(norm(op[1]))=='cache'and op[2]in ['#1','#0x1']else None)
   if x.mnemonic=='blraa'and any(k.mnemonic=='movk'and '#0x3ed6'in k.op_str for k in body[max(0,i-4):i]):
    assert regs.get('x1')=='cache|1',regs;mapped=True
   if x.mnemonic in ['bl','blr','blraa']:
    for reg in range(19):regs.pop('x'+str(reg),None)
  assert mapped,(name,'Window.open map does not preserve explicit cache')
  calls=[]
  for i,x in enumerate(ins):
   if x.mnemonic=='mov'and x.op_str in ['w3, #0x300','x3, #0x300']and any(k.mnemonic=='bl'for k in ins[i+1:i+4]):calls.append(hex(x.address))
  assert calls,(name,'pool call does not supply Copyback')
  direct=[dict(caller_options_sites=calls,cache='0x300 Copyback',callee=symbol,map_options='cache|1',map_slot_PAC='IA3ed6')]
 proof[name]=dict(sha256=scan['sha256'],direct=direct)
a.out.write_text(json.dumps(dict(passed=True,hardware_verified=False,actual_CI_objects=bool(a.ci),objects=proof),indent=2)+'\n');print('PASS actual arm64e Audio/Video/WiFi/DP NormalWB map arguments and authenticated IOMemoryDescriptor.map call')
