#!/usr/bin/env python3
"""Verify final sysctl registration and execute its production ARM64 handler."""
from pathlib import Path
import argparse,json,struct,hashlib,sys
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
from unicorn.arm64_const import *
b=Path(__file__).resolve().parents[2];sys.path.insert(0,str(b/'sources/UniXNU/kits/XnuPrelink'));from kc_image import Image
p=argparse.ArgumentParser();p.add_argument('image',type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args();raw=a.image.read_bytes();outer=Image(raw);fileset=bool(outer.entries);im=Image(raw,outer.entries['com.apple.kernel'][1]) if fileset else outer;names={n:v for v,ns in im.symbols().items() for n in ns}
def ptr(value):return outer.base+(value&0x3fffffff) if fileset else value
new=names['_sysctl__security_mac_lockdown_mode_state_public'];old=names['_sysctl__security_mac_lockdown_mode_state'];data=im.read(new,80)
parent,link,number,kind,arg1,arg2,name,handler,fmt,descr,version,refcount=struct.unpack('<QQiiQi4xQQQQii',data)
assert ptr(parent)==names['_sysctl__security_mac_children'];assert kind&15==4 and kind&0x80000000 and not kind&0x40000000
assert im.read(ptr(name),len('lockdown_mode_state_public')+1)==b'lockdown_mode_state_public\0'
assert im.read(ptr(fmt),2)==b'Q\0';assert ptr(handler)==names['_sysctl_lockdown_mode_state_public']
assert names.get('___startup_SYSCTL_entry_sysctl__security_mac__lockdown_mode_state_public'), 'missing early registration'
assert im.read(old+20,4)!=im.read(new+20,4), 'public query must use its own quad type'
uc=Uc(UC_ARCH_ARM64,UC_MODE_ARM);lo=min(v['va'] for v in im.segments if v['size'])&~4095;hi=(max(v['va']+v['size'] for v in im.segments if v['size'])+4095)&~4095;uc.mem_map(lo,hi-lo)
for v in im.segments:
 if v['filesize']:uc.mem_write(v['va'],raw[v['fileoff']:v['fileoff']+v['filesize']])
base=0xfffffff030000000;uc.mem_map(base,0x10000);return_at=base;output_fn=base+4;req=base+0x1000;state=0;failure=0;copies=[];md=Cs(CS_ARCH_ARM64,CS_MODE_ARM)
# The handler and native state getter run unchanged. Mock only sleeping lock
# primitives and the request's copyout callback, outside the query logic.
noop={names[n] for n in ('_lck_mtx_lock','_lck_mtx_unlock') if n in names}
def hook(e,pc,size,context):
 if pc in noop:e.reg_write(UC_ARM64_REG_X0,0);e.reg_write(UC_ARM64_REG_PC,e.reg_read(UC_ARM64_REG_X30));return
 if pc==output_fn:
  n=e.reg_read(UC_ARM64_REG_X2);payload=bytes(e.mem_read(e.reg_read(UC_ARM64_REG_X1),n));copies.append(payload);e.reg_write(UC_ARM64_REG_X0,failure);e.reg_write(UC_ARM64_REG_PC,e.reg_read(UC_ARM64_REG_X30));return
 ins=next(md.disasm(bytes(e.mem_read(pc,4)),pc))
 if ins.mnemonic in ('blraa','blrab'):
  assert e.reg_read(UC_ARM64_REG_X8)==output_fn, 'only the mocked copyout callback may bypass PAuth in this host harness'
  e.reg_write(UC_ARM64_REG_X30,pc+4);e.reg_write(UC_ARM64_REG_PC,output_fn)
 elif ins.mnemonic in ('pacibsp','paciasp','autibsp','autiasp'):e.reg_write(UC_ARM64_REG_PC,pc+4)
 elif ins.mnemonic in ('retab','retaa'):e.reg_write(UC_ARM64_REG_PC,e.reg_read(UC_ARM64_REG_X30))
uc.hook_add(UC_HOOK_CODE,hook);uc.reg_write(UC_ARM64_REG_CPACR_EL1,3<<20)
getter=list(md.disasm(im.read(names['_get_lockdown_mode_state'],0x80),names['_get_lockdown_mode_state']))
init=None
for left,right in zip(getter,getter[1:]):
 if left.mnemonic=='adrp' and left.op_str.startswith('x19, #') and right.mnemonic=='add' and right.op_str.startswith('x19, x19, #'):
  init=int(left.op_str.split('#')[1],16)+int(right.op_str.split('#')[1],0);break
assert init is not None, 'native getter initialization location not identified'
uc.mem_write(init,struct.pack('<I',1));cases=[]
for state,failure in ((0,0),(1,0),(0,0),(1,12),(1,14)):
 uc.mem_write(names['_lockdown_mode_state'],struct.pack('<I',state));uc.mem_write(req,bytes(88));uc.mem_write(req+40,struct.pack('<Q',output_fn));uc.reg_write(UC_ARM64_REG_SP,base+0xf000);uc.reg_write(UC_ARM64_REG_X30,return_at)
 for reg,value in ((UC_ARM64_REG_X0,new),(UC_ARM64_REG_X1,0),(UC_ARM64_REG_X2,0),(UC_ARM64_REG_X3,req)):uc.reg_write(reg,value)
 before=len(copies);uc.emu_start(names['_sysctl_lockdown_mode_state_public'],return_at,count=10000)
 assert uc.reg_read(UC_ARM64_REG_PC)==return_at and len(copies)==before+1
 assert copies[-1]==struct.pack('<Q',state) and uc.reg_read(UC_ARM64_REG_X0)&0xffffffff==failure
 cases.append(dict(native_state=state,returned_bytes=len(copies[-1]),copyout_error=failure,handler_result=uc.reg_read(UC_ARM64_REG_X0)&0xffffffff))
result=dict(passed=True,image=str(a.image),sha256=hashlib.sha256(raw).hexdigest(),fileset=fileset,public_query='security.mac.lockdown_mode_state_public',width=8,read_only=True,native_parent=True,original_integer_query_preserved=True,early_registration_present=True,actual_compiled_handler_executed=True,locks_and_copyout_mocked=True,cases=cases,PAuth_not_tested=True,device_tested=False)
a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
