#!/usr/bin/env python3
"""26C5035r IOHIDDevice address binding, copied by interface from Sheng's binder."""
from b5q_abi import object_symbols,object_vtable,discriminator,require

def bindings(raw,abi):
 found=object_symbols(raw);slots=[(int(t,16),int(d,16))for t,d in abi['slots']];slide=int(abi['collection_slide'],16)
 result={n:int(v,16)+slide for n,v in abi['bindings'].items()};by_div={};slot_of={}
 for i,(_,d)in enumerate(slots):by_div.setdefault(d,[]).append(i)
 vtables=[n for n,_,k in found if n.startswith('__ZTV')and k!=1 and '9MetaClassE'not in n]
 for name in vtables:
  entries=object_vtable(raw,found,name,len(slots))
  require(all(entries),f'{name}: complete IOHIDDevice vtable')
  for i,(method,word)in enumerate(entries):
   require(word>>63 and word>>48&1 and word>>49&3==0 and word>>32&0xffff==slots[i][1],f'{name} slot{i} diversity')
   if '11IOHIDDevice'in method:require(slot_of.setdefault(method,i)==i,'consistent original HID slot')
 for n in {n for n,_,k in found if k==1 and '11IOHIDDevice'in n}-set(result):
  matches=by_div.get(discriminator(n[1:]),[]);slot=slot_of.get(n)
  if slot is None:require(len(matches)==1,f'{n}: unique HID diversity');slot=matches[0]
  require(slots[slot][0]!=int(abi['pure_target'],16),'No abstract HID target');result[n]=slots[slot][0]+slide
 for vt in vtables:
  for i,(n,_)in enumerate(object_vtable(raw,found,vt,len(slots))):
   if '11IOHIDDevice'in n:require(result.get(n)==slots[i][0]+slide,f'{n}: original HID target')
 return result,{'slots':len(slots),'vtables':vtables,'all_diversities_checked':True}

def assembly(bound):
 text='.text\n.p2align 2\n';addresses=''
 for name,va in sorted(bound.items()):
  if name in {'__ZN11IOHIDDevice10gMetaClassE','__ZTV11IOHIDDevice'}:addresses+=f'.globl {name}\n.set {name}, {va:#x}\n'
  else:addresses+=f'.globl {name}.original\n.set {name}.original, {va:#x}\n';text+=f'.globl {name}\n{name}:\n bti c\n b {name}.original\n'
 return text,addresses
