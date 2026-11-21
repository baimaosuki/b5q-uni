#!/usr/bin/env python3
"""Compare actual producer auth relocations and C indirect-call discriminators."""
from pathlib import Path
import argparse,json,struct,sys,hashlib
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'UniXNU-b5q/scripts'))
from b5q_abi import macho,object_symbols
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--objects',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--producer',default='B5qTouch.o');a=p.parse_args()
producer=(a.objects/a.producer).read_bytes();symbols=object_symbols(producer);found={}
for segment in macho(producer)['segments']:
 for sec in segment['sections']:
  ro,rc=struct.unpack_from('<II',producer,sec['command_offset']+56)
  for i in range(rc):
   offset,bits=struct.unpack_from('<II',producer,ro+8*i)
   if bits>>28!=11 or not bits>>27&1:continue
   name=symbols[bits&0xffffff][0]
   if name not in ['__ZN12_GLOBAL__N_12rdEPvj','__ZN12_GLOBAL__N_12wrEPvjj','__ZN12_GLOBAL__N_16seReadEPvj','__ZN12_GLOBAL__N_17seWriteEPvjj']:continue
   word=struct.unpack_from('<Q',producer,sec['fileoff']+offset)[0]
   assert word>>63 and word>>49&3==0 and not word>>48&1
   found['read' if '2rdE' in name or '6seReadE' in name else 'write']=word>>32&0xffff
if a.producer=='B5qUsbBoard.o':
 # A stack-created GeniIo uses PACIA instructions instead of constant-pool
 # authenticated relocations. Resolve their actual target relocations.
 md=Cs(CS_ARCH_ARM64,CS_MODE_ARM)
 for segment in macho(producer)['segments']:
  for sec in segment['sections']:
   if sec['name']!='__text':continue
   ro,rc=struct.unpack_from('<II',producer,sec['command_offset']+56)
   reloc={}
   for i in range(rc):
    off,bits=struct.unpack_from('<II',producer,ro+8*i)
    if bits>>27&1:reloc[sec['va']+off]=symbols[bits&0xffffff][0]
   instructions=list(md.disasm(producer[sec['fileoff']:sec['fileoff']+sec['size']],sec['va']))
   for i,ins in enumerate(instructions):
    if ins.mnemonic!='pacia' or i<2:continue
    move=instructions[i-1];target=reloc.get(instructions[i-2].address,'')
    if target not in ['__ZN12_GLOBAL__N_16seReadEPvj','__ZN12_GLOBAL__N_17seWriteEPvjj']:continue
    assert ins.op_str=='x16, x17' and move.mnemonic=='mov' and move.op_str.startswith('x17, #')
    found['read' if 'seRead' in target else 'write']=int(move.op_str.split('#')[1],0)
assert found=={'read':0x50c7,'write':0xc120},found
consumer=(a.objects/'GeniI2c.o').read_bytes();cs=Cs(CS_ARCH_ARM64,CS_MODE_ARM);calls=[]
for segment in macho(consumer)['segments']:
 for sec in segment['sections']:
  if sec['name']!='__text':continue
  regs={}
  for ins in cs.disasm(consumer[sec['fileoff']:sec['fileoff']+sec['size']],sec['va']):
   if ins.mnemonic=='mov' and ', #' in ins.op_str:
    reg,value=ins.op_str.split(', #');regs[reg]=int(value,0)
   if ins.mnemonic in ('blraaz','blraz','blr'):raise AssertionError('Unqualified/zero-diversity C callback: '+ins.mnemonic)
   if ins.mnemonic=='blraa':
    target,modifier=ins.op_str.split(', ');value=regs.get(modifier)
    assert value in found.values(),(hex(ins.address),value)
    calls.append({'object_offset':hex(ins.address),'key':'IA','discriminator':hex(value)})
assert calls and {int(c['discriminator'],16)for c in calls}==set(found.values())
report={'passed':True,'producer_type_discriminators':{k:hex(v)for k,v in found.items()},'consumer_indirect_calls':calls,'zero_discriminator_calls':0,'C_CPP_callback_ABI_matches':True,'PAuth_enabled':True,'hardware_PAuth_execution_tested':False,'object_sha256':{n:hashlib.sha256((a.objects/n).read_bytes()).hexdigest()for n in [a.producer,'GeniI2c.o']}}
a.out.write_text(json.dumps(report,indent=2)+'\n');print('PASS actual C/C++ GENI callback PAC: read50c7/writec120,',len(calls),'typed IA calls; no zero-discriminator calls')
