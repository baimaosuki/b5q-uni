#!/usr/bin/env python3
"""Execute actual final root-read retry instructions with SCSI transport mocked."""
import argparse,hashlib,json,re,struct,subprocess,sys,tempfile
from pathlib import Path
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
from unicorn.arm64_const import *
root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root/'sources/UniXNU/kits/XnuPrelink'));from kc_image import Image
p=argparse.ArgumentParser(description=__doc__);p.add_argument('kernel',type=Path);p.add_argument('--out',required=True,type=Path);a=p.parse_args();raw=a.kernel.read_bytes();outer=Image(raw);im=Image(raw,outer.entries['com.apple.kernel'][1])if outer.entries else outer;names={n:v for v,ns in im.symbols().items()for n in ns}
def one(part):
 n=[n for n in names if part in n];assert len(n)==1,(part,n);return names[n[0]]
entry=one('7readLbaE');command=one('7commandEh');host=one('4hostE');source=(root/'UniXNU-b5q/package/B5qUfs/B5qUfs.cpp').read_text();transport=re.search(r'struct Transport \{.*?\n\};',source,re.S)[0]
with tempfile.TemporaryDirectory(prefix='b5q-read-layout-')as t:
 t=Path(t);(t/'offset.cpp').write_text('#include <cstdio>\n#include <cstddef>\n#include "B5qUfsProtocol.h"\nstruct IOMemoryMap;struct IOBufferMemoryDescriptor;struct IOLock;using namespace B5qUfsProtocol;\n'+transport+'''\nint main(){
#define O(t,f) printf(#t "." #f " %zu\\n",offsetof(t,f))
O(Transport,lun);O(Transport,selected);O(Transport,poisoned);O(Transport,capacity);O(Status,scsi);O(Status,sense);O(Status,senseKnown);O(Status,exact);printf("Status.bytes %zu\\n",sizeof(Status));}
''');subprocess.run(['c++','-std=c++17','-I'+str(root/'UniXNU-b5q/package/B5qUfs'),str(t/'offset.cpp'),'-o',str(t/'offset')],check=True);layout={n:int(v)for n,v in(line.split()for line in subprocess.check_output([str(t/'offset')],text=True).splitlines())}
u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);lo=min(s['va']for s in im.segments if s['size'])&~4095;hi=(max(s['va']+s['size']for s in im.segments if s['size'])+4095)&~4095;u.mem_map(lo,hi-lo)
for s in im.segments:
 if s['filesize']:u.mem_write(s['va'],raw[s['fileoff']:s['fileoff']+s['filesize']])
base=0xfffffff030000000;u.mem_map(base,0x10000);out=base+0x1000;stop=base;md=Cs(CS_ARCH_ARM64,CS_MODE_ARM);u.reg_write(UC_ARM64_REG_CPACR_EL1,3<<20)
mode='';calls=0;delays=0
def hook(e,pc,size,context):
 global calls,delays
 if pc==command:
  assert e.reg_read(UC_ARM64_REG_X0)==3 and e.reg_read(UC_ARM64_REG_X2)==4096
  cdb=bytes(e.mem_read(e.reg_read(UC_ARM64_REG_X1),16));assert cdb[0]==0x28 and int.from_bytes(cdb[2:6],'big')==49692663 and cdb[8]==1
  status=e.reg_read(UC_ARM64_REG_X4);assert status!=0;calls+=1;state=bytearray(layout['Status.bytes'])
  if mode=='good' or (mode in ('busy','full','ua','not-ready')and calls==3):ret=0;state[layout['Status.scsi']]=0;state[layout['Status.exact']]=1;e.mem_write(e.reg_read(UC_ARM64_REG_X3),b'Z'*4096)
  else:
   ret={'busy':8,'full':0x28,'ua':2,'not-ready':2,'exhausted':8,'illegal':2,'short':-2,'transport':-1,'poisoned':8}[mode]
   state[layout['Status.scsi']]=ret if ret>=0 else 0
   if ret==2:state[layout['Status.senseKnown']]=1;struct.pack_into('<I',state,layout['Status.sense'],0x052000 if mode=='illegal'else 0x020401 if mode=='not-ready'else 0x062900)
  e.mem_write(status,bytes(state))
  if mode=='poisoned':e.mem_write(host+layout['Transport.poisoned'],b'\1')
  e.reg_write(UC_ARM64_REG_X0,ret&0xffffffff);e.reg_write(UC_ARM64_REG_PC,e.reg_read(UC_ARM64_REG_X30));return
 if pc==names.get('_IOSleep'):
  assert e.reg_read(UC_ARM64_REG_X0)==10;delays+=1;e.reg_write(UC_ARM64_REG_PC,e.reg_read(UC_ARM64_REG_X30));return
 i=next(md.disasm(bytes(e.mem_read(pc,4)),pc))
 if i.mnemonic in ('pacibsp','paciasp','autibsp','autiasp'):e.reg_write(UC_ARM64_REG_PC,pc+4)
 elif i.mnemonic in ('retab','retaa'):e.reg_write(UC_ARM64_REG_PC,e.reg_read(UC_ARM64_REG_X30))
u.hook_add(UC_HOOK_CODE,hook);cases=[]
for mode in ['good','busy','full','ua','not-ready','exhausted','illegal','short','transport','poisoned']:
 calls=delays=0;u.mem_write(host+layout['Transport.lun'],b'\3');u.mem_write(host+layout['Transport.selected'],b'\1');u.mem_write(host+layout['Transport.poisoned'],b'\0');u.mem_write(host+layout['Transport.capacity']+3*8,struct.pack('<Q',62275584));u.mem_write(out,b'\xcc'*4096);u.reg_write(UC_ARM64_REG_SP,base+0xf000);u.reg_write(UC_ARM64_REG_X30,stop)
 for reg,val in [(UC_ARM64_REG_X0,3),(UC_ARM64_REG_X1,49692663),(UC_ARM64_REG_X2,1),(UC_ARM64_REG_X3,out),(UC_ARM64_REG_X4,0)]:u.reg_write(reg,val)
 u.emu_start(entry,stop,count=5000);assert u.reg_read(UC_ARM64_REG_PC)==stop
 success=mode in ['good','busy','full','ua','not-ready'];assert bool(u.reg_read(UC_ARM64_REG_X0))==success
 expected=1 if mode in ['good','illegal','short','transport','poisoned']else 3;assert calls==expected and delays==(2 if calls==3 else 0),(mode,calls,delays)
 assert bytes(u.mem_read(out,4096))==(b'Z'if success else b'\xcc')*4096
 cases.append(dict(case=mode,attempts=calls,delays=delays,success=success))
a.out.write_text(json.dumps(dict(passed=True,kernel_sha256=hashlib.sha256(raw).hexdigest(),actual_readLba_instructions=True,SCSI_and_sleep_mocked=True,PAuth_not_tested=True,hardware_tested=False,cases=cases),indent=2)+'\n');print('PASS actual final readLba retry instructions:',len(cases),'cases')
