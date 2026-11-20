#!/usr/bin/env python3
"""Execute final ARM64 root dispatch and vr_verify_block; mock I/O and SHA service."""
import argparse,hashlib,json,struct,subprocess,sys,tempfile
from pathlib import Path
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
from unicorn.arm64_const import *
root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root/'sources/UniXNU/kits/XnuPrelink'))
from kc_image import Image
p=argparse.ArgumentParser(description=__doc__);p.add_argument('kernel',type=Path);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
raw=a.kernel.read_bytes();outer=Image(raw);im=Image(raw,outer.entries['com.apple.kernel'][1])if outer.entries else outer
names={n:v for v,rows in im.symbols().items()for n in rows};md=Cs(CS_ARCH_ARM64,CS_MODE_ARM)
def one(s):
 hits=[v for n,v in names.items()if s in n];assert len(hits)==1,(s,hits);return hits[0]
dispatch=one('B5qRootBlock16doAsyncReadWrite');read=one('7readLbaE');verify=names['_vr_verify_block']
# The deployed getter identifies the actual private-member start after its base.
getter_ins=list(md.disasm(im.read(one('B5qRootBlock16getProductString'),20),one('B5qRootBlock16getProductString')))
loads=[i for i in getter_ins if i.mnemonic=='ldr'and '[x0, #'in i.op_str];assert len(loads)==1
member=int(loads[0].op_str.split('#')[1].split(']')[0],0)
# Entry and vr_view contain only ordinary fixed-width data; obtain host offsets.
with tempfile.TemporaryDirectory(prefix='b5q-read-layout-')as t:
 t=Path(t);(t/'o.cpp').write_text('#include <cstdio>\n#include <cstddef>\n#include "B5qRootFormat.h"\n#include "verified_root.h"\nusing namespace B5qFormat;\nstruct R{Entry image,table;vr_view policy;};\nint main(){printf("%zu %zu %zu %zu %zu %zu\\n",offsetof(R,policy),offsetof(Entry,offset),offsetof(Entry,bytes),offsetof(vr_view,hashes),offsetof(vr_view,image_bytes),offsetof(vr_view,block_count));}\n')
 subprocess.run(['c++','-I'+str(root/'UniXNU-b5q/package/B5qUfs'),'-I'+str(root/'sources/UniXNU/kits/VerifiedRoot/include'),str(t/'o.cpp'),'-o',str(t/'o')],check=True)
 policy,imageOffset,imageBytes,hashesOffset,sizeOffset,countOffset=map(int,subprocess.check_output([str(t/'o')],text=True).split())
u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);lo=min(s['va']for s in im.segments if s['size'])&~4095;hi=(max(s['va']+s['size']for s in im.segments if s['size'])+4095)&~4095;u.mem_map(lo,hi-lo)
for s in im.segments:
 if s['filesize']:u.mem_write(s['va'],raw[s['fileoff']:s['fileoff']+s['filesize']])
base=0xfffffff030000000;u.mem_map(base,0x800000);u.reg_write(UC_ARM64_REG_CPACR_EL1,3<<20)
stop=base;disk=base+0x1000;desc=base+0x2000;vt=base+0x3000;rt=base+0x4000;completion=base+0x5000
scratch=base+0x10000;table=base+0x40000;output=base+0x100000;stack=base+0x7f0000
getLength=base+0x6000;getDirection=base+0x6100;copy=base+0x6200;done=base+0x6300;sha=base+0x6400
media=bytes((i*29+i//4096)&255 for i in range(2<<20));size=len(media)
def q(at,v):u.mem_write(at,struct.pack('<Q',v))
q(disk+member,rt);q(disk+member+8,base+0x8000);q(disk+member+16,scratch);u.mem_write(disk+member+24,b'\1')
q(rt+imageOffset,1048576);q(rt+imageBytes,size);q(rt+policy+hashesOffset,table);q(rt+policy+sizeOffset,size);q(rt+policy+countOffset,size//4096)
u.mem_write(table,b''.join(hashlib.sha256(media[i:i+4096]).digest()for i in range(0,size,4096)))
q(desc,vt);q(completion,base+0x9000);q(completion+8,done);q(completion+16,base+0xa000)
# Recover descriptor virtual slot offsets from actual deployed vtable entries.
vtable=names['__ZTV18IOMemoryDescriptor'];targets={'getLength':getLength,'getDirection':getDirection,'writeBytes':copy};found=set()
for at in range(16,0x380,8):
 word=struct.unpack('<Q',im.read(vtable+at,8))[0];addr=outer.base+(word&0x3fffffff)if outer.entries else word
 for n in im.symbols().get(addr,[]):
  for key,value in targets.items():
   if 'IOMemoryDescriptor' in n and key in n:q(vt+at-16,value);found.add(key)
assert found==set(targets)
q(names['_vr_xnu_crypto'],sha);q(names['_vr_xnu_crypto']+8,0)
calls=[];verified=[];copies=[];finish=[];corrupt=-1;failure=0;short=0;length=0;direction=1;locked=False
registers={f'x{i}':getattr(__import__('unicorn.arm64_const',fromlist=['*']),f'UC_ARM64_REG_X{i}')for i in range(31)}
def ret(value):u.reg_write(UC_ARM64_REG_X0,value&0xffffffffffffffff);u.reg_write(UC_ARM64_REG_PC,u.reg_read(UC_ARM64_REG_X30))
def hook(e,pc,n,c):
 global locked
 x=lambda i:e.reg_read(registers[f'x{i}'])
 if pc==read:
  assert locked and x(0)==3 and 0<x(2)<=32
  at=(x(1)-49692663)*4096-1048576;bytes_=x(2)*4096;assert at>=0 and at+bytes_<=size
  calls.append((at,bytes_))
  if failure and len(calls)==failure:ret(0);return
  buf=bytearray(media[at:at+bytes_])
  if corrupt>=0 and at<=corrupt*4096<at+bytes_:buf[corrupt*4096-at]^=1
  e.mem_write(x(3),bytes(buf));ret(1);return
 if pc==verify:verified.append(x(1)) # execute actual vr_verify_block, not a replacement
 if pc==sha:
  assert locked and x(1)==4096;e.mem_write(x(2),hashlib.sha256(bytes(e.mem_read(x(0),x(1)))).digest());ret(1);return
 if pc==names['_IOLockLock']:assert not locked;locked=True;ret(0);return
 if pc==names['_IOLockUnlock']:assert locked;locked=False;ret(0);return
 if pc==getLength:ret(length);return
 if pc==getDirection:ret(direction);return
 if pc==copy:
  assert locked;count=min(short,x(3))if short else x(3);assert x(1)+count<=length
  e.mem_write(output+x(1),bytes(e.mem_read(x(2),count)));copies.append((x(1),count));ret(count);return
 if pc==done:
  assert not locked;finish.append((x(2)&0xffffffff,x(3)));ret(0);return
 ins=next(md.disasm(bytes(e.mem_read(pc,4)),pc))
 if ins.mnemonic.startswith(('pac','aut','xpac')):e.reg_write(UC_ARM64_REG_PC,pc+4)
 elif ins.mnemonic in ('retab','retaa'):e.reg_write(UC_ARM64_REG_PC,x(30))
 elif ins.mnemonic.startswith(('blraa','blrab')):
  target=e.reg_read(registers[ins.op_str.split(',')[0]]);e.reg_write(UC_ARM64_REG_X30,pc+4);e.reg_write(UC_ARM64_REG_PC,target)
 elif ins.mnemonic.startswith(('braa','brab')):e.reg_write(UC_ARM64_REG_PC,e.reg_read(registers[ins.op_str.split(',')[0]]))
u.hook_add(UC_HOOK_CODE,hook);results=[]
def run(label,first,count,expected_status,expected_bytes,expected_commands):
 global length
 calls.clear();verified.clear();copies.clear();finish.clear();length=count*512;u.mem_write(output,b'\xcc'*length)
 u.reg_write(UC_ARM64_REG_SP,stack);u.reg_write(UC_ARM64_REG_X30,stop)
 for i,v in enumerate([disk,desc,first,count,0,completion]):u.reg_write(registers[f'x{i}'],v)
 u.emu_start(dispatch,stop,count=1000000);assert u.reg_read(UC_ARM64_REG_PC)==stop
 assert finish==[(expected_status,expected_bytes)],(label,finish)
 assert len(calls)==expected_commands,(label,len(calls));assert not locked
 assert bytes(u.mem_read(output,expected_bytes))==media[first*512:first*512+expected_bytes]
 assert bytes(u.mem_read(output+expected_bytes,length-expected_bytes))==b'\xcc'*(length-expected_bytes)
 results.append(dict(case=label,UFS_commands=len(calls),verified_blocks=len(verified),completed_bytes=expected_bytes,status=expected_status))
# readLba is intercepted above; its LUN argument is loaded from the production host.
source=(root/'UniXNU-b5q/package/B5qUfs/B5qUfs.cpp').read_text()
import re
transport=re.search(r'struct Transport \{.*?\n\};',source,re.S)[0]
with tempfile.TemporaryDirectory()as t:
 t=Path(t);(t/'h.cpp').write_text('#include <cstdio>\n#include <cstddef>\n#include "B5qUfsProtocol.h"\nstruct IOMemoryMap;struct IOBufferMemoryDescriptor;struct IOLock;using namespace B5qUfsProtocol;\n'+transport+'\nint main(){printf("%zu\\n",offsetof(Transport,lun));}')
 subprocess.run(['c++','-I'+str(root/'UniXNU-b5q/package/B5qUfs'),str(t/'h.cpp'),'-o',str(t/'h')],check=True)
 lunOffset=int(subprocess.check_output([str(t/'h')],text=True))
u.mem_write(one('4hostE')+lunOffset,b'\3')
run('one-MiB',0,2048,0,1048576,8)
run('unaligned',1,2048,0,1048576,9)
run('last-sector',size//512-1,1,0,512,1)
corrupt=2;run('bad-hash',1,2048,0xe00002ca,7680,1);corrupt=-1
failure=2;run('second-batch-fails',0,2048,0xe00002ca,131072,2);failure=0
short=23;run('short-copy',0,8,0xe00002ca,23,1);short=0
a.out.write_text(json.dumps(dict(passed=True,kernel_sha256=hashlib.sha256(raw).hexdigest(),actual_ARM64_dispatch_and_block_verifier=True,SCSI_locks_descriptor_and_SHA_service_mocked=True,SHA256_real_hashlib=True,PAuth_not_tested=True,hardware_tested=False,cases=results),indent=2)+'\n');print('PASS final ARM64 batch dispatch and actual block verifier:',len(results),'cases')
