#!/usr/bin/env python3
"""Inspect startup entry and execute returned log request builder up to submit.

All execution is local. Locks, bzero, DMA and HC memory are fixtures; submission
is intercepted before any controller or device access. PAuth is not tested.
"""
import argparse,hashlib,json,re,struct,subprocess,sys,tempfile
from pathlib import Path
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
from unicorn.arm64_const import *
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'sources/UniXNU/kits/XnuPrelink'))
from kc_image import Image
p=argparse.ArgumentParser(description=__doc__);p.add_argument('kernel',type=Path);p.add_argument('--out',type=Path,required=True);p.add_argument('--expect-old',action='store_true');a=p.parse_args()
raw=a.kernel.read_bytes();outer=Image(raw);im=Image(raw,outer.entries['com.apple.kernel'][1])if outer.entries else outer;names={n:v for v,ns in im.symbols().items()for n in ns}
def one(part):
 hits=[n for n in names if part in n];assert len(hits)==1,(part,hits);return names[hits[0]],hits[0]
entry,entry_name=one('entry_b5q_console_capture_init');subsystem,rank,callback,arg=struct.unpack('<IIQQ',im.read(entry,24))
assert (subsystem,rank)==((6,0xffffffff)if a.expect_old else(13,0)),(subsystem,rank)
callback=outer.base+(callback&0x3fffffff)if outer.entries else callback;assert callback==names['_b5q_console_capture_init']
# Compute ABI layout from the unchanged production structure; no guessed host
# member offsets. Pointer/scalar sizes are identical for the host and ARM64.
source=(ROOT/'UniXNU-b5q/package/B5qUfs/B5qUfs.cpp').read_text();transport=re.search(r'struct Transport \{.*?\n\};',source,re.S)[0]
with tempfile.TemporaryDirectory(prefix='b5q-log-abi-')as temp:
 temp=Path(temp);cpp=temp/'offsets.cpp';cpp.write_text('''#include <cstdio>
#include <cstddef>
#include "B5qUfsProtocol.h"
#include "B5qLogVolume.h"
struct IOMemoryMap;struct IOBufferMemoryDescriptor;struct IOLock;
using namespace B5qUfsProtocol;
'''+transport+'''
int main(){
#define O(t,f) printf(#t "." #f " %zu\\n",offsetof(t,f))
O(Transport,hc);O(Transport,dma);O(Transport,physical);O(Transport,lock);O(Transport,lun);O(Transport,selected);O(Transport,poisoned);O(Transport,capacity);
O(nb_log_volume,file_first);O(nb_log_volume,validated);
printf("volume.bytes %zu\\n",sizeof(nb_log_volume));
}
''');exe=temp/'offsets';subprocess.run(['c++','-std=c++17','-I'+str(ROOT/'UniXNU-b5q/package/B5qUfs'),str(cpp),'-o',str(exe)],check=True)
 layout={n:int(v)for n,v in (line.split()for line in subprocess.check_output([str(exe)],text=True).splitlines())}
host,_=one('4hostE');volptr,_=one('nabu_log_volume_ptrE');io,io_name=one('nabuLogIo');submit,_=one('6submitEv')
base=0xfffffff030000000;hc=base+0x1000;dma=base+0x10000;vol=base+0x100000;stack=base+0x3f0000;stop=base
u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);lo=min(s['va']for s in im.segments if s['size'])&~4095;hi=(max(s['va']+s['size']for s in im.segments if s['size'])+4095)&~4095;u.mem_map(lo,hi-lo)
for s in im.segments:
 if s['filesize']:u.mem_write(s['va'],raw[s['fileoff']:s['fileoff']+s['filesize']])
u.mem_map(base,0x400000);u.reg_write(UC_ARM64_REG_CPACR_EL1,3<<20);md=Cs(CS_ARCH_ARM64,CS_MODE_ARM)
def put64(at,val):u.mem_write(at,struct.pack('<Q',val))
for name,val in {'hc':hc,'dma':dma,'physical':0x900000000,'lock':base+0x800,'capacity':62275584}.items():
 if name=='capacity':put64(host+layout['Transport.capacity']+3*8,val)
 else:put64(host+layout['Transport.'+name],val)
u.mem_write(host+layout['Transport.lun'],b'\x03');u.mem_write(host+layout['Transport.selected'],b'\x01');u.mem_write(host+layout['Transport.poisoned'],b'\x00');put64(volptr,vol)
first=3203656;put64(vol+layout['nb_log_volume.file_first'],first);u.mem_write(vol+layout['nb_log_volume.validated'],struct.pack('<I',1))
requests=[];busy=False

def hook(e,pc,size,context):
 if pc==submit:
  requests.append({'cdb':bytes(e.mem_read(dma+0x1010,16)).hex(),'lun':e.mem_read(dma+0x1002,1)[0],'flags':e.mem_read(dma+0x1001,1)[0],'descriptor':struct.unpack('<I',e.mem_read(dma,4))[0],'bytes':struct.unpack('>I',e.mem_read(dma+0x100c,4))[0]});e.emu_stop();return
 if pc in (names['_IOLockTryLock'],names['_IOLockUnlock']):
  e.reg_write(UC_ARM64_REG_X0,0 if busy and pc==names['_IOLockTryLock']else 1);e.reg_write(UC_ARM64_REG_PC,e.reg_read(UC_ARM64_REG_X30));return
 if pc==names['_bzero']:
  e.mem_write(e.reg_read(UC_ARM64_REG_X0),bytes(e.reg_read(UC_ARM64_REG_X1)));e.reg_write(UC_ARM64_REG_PC,e.reg_read(UC_ARM64_REG_X30));return
 ins=next(md.disasm(bytes(e.mem_read(pc,4)),pc))
 if ins.mnemonic in ('pacibsp','paciasp','autibsp','autiasp'):e.reg_write(UC_ARM64_REG_PC,pc+4)
 elif ins.mnemonic in ('retab','retaa'):e.reg_write(UC_ARM64_REG_PC,e.reg_read(UC_ARM64_REG_X30))
u.hook_add(UC_HOOK_CODE,hook)
def run(lba,blocks,write=0,sync=1):
 before=len(requests);u.reg_write(UC_ARM64_REG_SP,stack);u.reg_write(UC_ARM64_REG_X30,stop)
 for reg,val in [(UC_ARM64_REG_X0,write),(UC_ARM64_REG_X1,lba),(UC_ARM64_REG_X2,blocks),(UC_ARM64_REG_X3,base+0x80000 if write else 0),(UC_ARM64_REG_X4,sync)]:u.reg_write(reg,val)
 u.emu_start(io,stop,count=50000)
 return len(requests)>before
for slot in [0,1]:
 assert run(first+1+slot*1025,1025);req=requests[-1];assert req['lun']==3 and req['flags']==0 and req['descriptor']&(3<<25)==0 and req['bytes']==0
 cdb=bytes.fromhex(req['cdb']);assert cdb[0]==0x35
 assert (any(cdb[1:])if a.expect_old else cdb==b'\x35'+bytes(15))
for lba,blocks in [(0,0),(first,1),(first+2050,2),(49692663,1)]:assert not run(lba,blocks)
busy=True;assert not run(first+1,1025);busy=False
assert run(first+1,1,write=1,sync=0);req=requests[-1];cdb=bytes.fromhex(req['cdb']);assert cdb[:2]==b'\x2a\x08' and req['lun']==3 and req['flags']==0x20 and req['descriptor']&(3<<25)==1<<25
assert struct.unpack_from('>I',cdb,2)[0]==first+1 and req['bytes']==4096
result={'result':'PASS','scope':'Actual compiled startup record and log I/O function before submission; host/lock/DMA fixtures; no device I/O','kernel_sha256':hashlib.sha256(raw).hexdigest(),'startup_symbol':entry_name,'subsystem':subsystem,'rank':rank,'startup_phase_during_callback':subsystem-1,'sync_requests':requests[:2],'readonly_root_and_unvalidated_ranges_rejected':True,'TryLock_busy_emits_nothing':True,'WRITE10_FUA_unchanged':True,'wire_expectation':'old ranged CDB reproduced'if a.expect_old else'zero range CDB verified','PAuth_not_tested':True,'hardware_tested':False}
a.out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
