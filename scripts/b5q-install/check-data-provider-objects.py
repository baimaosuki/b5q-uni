#!/usr/bin/env python3
"""Check real storage-object cross references and authenticated weak-hook type."""
import argparse,hashlib,importlib.util,json,struct,sys
from pathlib import Path
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'UniXNU-b5q/scripts'))
from b5q_abi import macho,object_symbols,object_vtable
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--objects',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
 s=importlib.util.spec_from_file_location('pac',R/'scripts/b5q-install/check-proctop-pac.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
 ram=m.scan(a.objects/'NativeRamBlock.o');ufs=m.scan(a.objects/'B5qUfs.o');hook='_native_ram_block_provider_seed';select='_native_ram_block_volume_seed'
 assert any(n==hook and k&0xe for n,v,k in ufs['symbols'])
 assert any(n==hook and not k&0xe for n,v,k in ram['symbols'])
 assert any(n==select and k&0xe for n,v,k in ram['symbols'])
 assert any(n==select and not k&0xe for n,v,k in ufs['symbols'])
 signed=ram['signed'][hook];assert signed and all(v['key']==0 and v['diversity']==0xbd41 and not v['address_diversity']for v in signed)
 def branches(path,name):
  raw=path.read_bytes();sy=object_symbols(raw);count=0
  for seg in macho(raw)['segments']:
   for sec in seg['sections']:
    off,n=struct.unpack_from('<II',raw,sec['command_offset']+56)
    for i in range(n):
     at,bits=struct.unpack_from('<II',raw,off+i*8)
     if bits>>27&1 and bits>>28==2 and sy[bits&0xffffff][0]==name:count+=1
  return count
 assert branches(a.objects/'NativeRamBlock.o',hook)>=1 and branches(a.objects/'B5qUfs.o',select)>=1
 # The nonvirtual provider helper adds no slot. Compare inherited PAC slots
 # across the compiled RAM and persistent block-device implementations.
 def table(path,name):
  raw=path.read_bytes();sy=object_symbols(raw);va=next(v for n,v,k in sy if n==name)
  end=min(v for n,v,k in sy if v>va and k&0xe)
  return object_vtable(raw,sy,name,(end-va)//8-2)
 x=table(a.objects/'NativeRamBlock.o','__ZTV14NativeRamBlock');y=table(a.objects/'B5qUfs.o','__ZTV12B5qDataBlock');assert len(x)==len(y)
 checked=0
 for i,(left,right)in enumerate(zip(x,y)):
  if left is not None and right is not None:assert left[1]>>32==right[1]>>32,(i,left,right);checked+=1
 assert checked>200
 report=dict(passed=True,hook=hook,weak_import_presence_PAC=dict(key='IA',diversity='0xbd41',signed_sites=signed),hook_and_selector_calls='ARM64_RELOC_BRANCH26 direct calls; no indirect callback discriminator mismatch',RAM_and_Data_inherited_vtable_PAC_slots=checked,objects={p.name:hashlib.sha256(p.read_bytes()).hexdigest()for p in [a.objects/'NativeRamBlock.o',a.objects/'B5qUfs.o']})
 a.out.write_text(json.dumps(report,indent=2)+'\n');print('PASS provider weak hook IA0xbd41, direct cross-object calls, RAM/Data inherited PAC slots',checked)
if __name__=='__main__':main()
