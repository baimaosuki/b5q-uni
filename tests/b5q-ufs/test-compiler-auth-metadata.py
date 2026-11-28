#!/usr/bin/env python3
"""Reject referenced/unsigned aliases when classifying Apple's unused PAC nlists."""
import ast,importlib.util,struct,sys,tempfile
from pathlib import Path
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'UniXNU-b5q/scripts'))
from b5q_abi import macho
spec=importlib.util.spec_from_file_location('pac',R/'scripts/b5q-install/check-proctop-pac.py');pac=importlib.util.module_from_spec(spec);spec.loader.exec_module(pac)
src=R/'scripts/b5q-install/check-wireless-target-closure.py'
functions=[v for v in ast.parse(src.read_text()).body if isinstance(v,ast.FunctionDef)and v.name=='unused_auth_declarations'];assert len(functions)==1
ns=dict(macho=macho,struct=struct);exec(compile(ast.Module(body=functions,type_ignores=[]),str(src),'exec'),ns);classify=ns['unused_auth_declarations']
p=next((R/'artifacts/b5q-p3-work/ci45268304105').rglob('B5qWcnPower.o'));raw=p.read_bytes();scan=pac.scan(p);rows=classify(p,scan);assert len(rows)==2
h=macho(raw);st=next(at for cmd,at,_ in h['commands']if cmd==2);sy,count,_,_=struct.unpack_from('<4I',raw,st+8)
index=next(i for i,(name,_,_)in enumerate(scan['symbols'])if name==rows[0]['declaration'])
mutations=[]
changed=bytearray(raw);desc=struct.unpack_from('<H',raw,sy+16*index+6)[0];struct.pack_into('<H',changed,sy+16*index+6,desc&~0x40);mutations.append(('non-weak alias',changed))
changed=bytearray(raw);done=False
for seg in h['segments']:
 for sec in seg['sections']:
  off,n=struct.unpack_from('<II',raw,sec['command_offset']+56)
  for j in range(n):
   pos=off+8*j+4;bits=struct.unpack_from('<I',raw,pos)[0]
   if bits>>27&1 and not done:struct.pack_into('<I',changed,pos,(bits&0xff000000)|index);done=True
assert done;mutations.append(('referenced alias',changed))
changed=bytearray(raw);done=False
for seg in h['segments']:
 for sec in seg['sections']:
  off,n=struct.unpack_from('<II',raw,sec['command_offset']+56)
  for j in range(n):
   pos=off+8*j+4;bits=struct.unpack_from('<I',raw,pos)[0]
   if bits>>27&1 and bits>>28==11 and scan['symbols'][bits&0xffffff][0]==rows[0]['target']:
    struct.pack_into('<I',changed,pos,bits&0x0fffffff);done=True
assert done;mutations.append(('missing real authenticated relocation',changed))
with tempfile.TemporaryDirectory(prefix='b5q-auth-metadata-')as td:
 for label,changed in mutations:
  f=Path(td)/'changed.o';f.write_bytes(changed)
  try:classify(f,pac.scan(f));raise RuntimeError('accepted '+label)
  except AssertionError:pass
media=R/'scripts/b5q-install/check-media-target-closure.py'
other=[v for v in ast.parse(media.read_text()).body if isinstance(v,ast.FunctionDef)and v.name=='unused_auth_declarations']
assert len(other)==1 and ast.dump(functions[0],include_attributes=False)==ast.dump(other[0],include_attributes=False)
ci=R/'artifacts/b5q-p4-work/ci45295645295'
manifest,=ci.rglob('media-build.json')
import json
build=json.loads(manifest.read_text());total=0
for name in build['objects']:
 f=manifest.parent/Path(name).name;total+=len(classify(f,pac.scan(f)))
assert total==10,total
print('PASS Xcode PAC metadata:2wireless+10media declarations (7 unique targets);3 negative mutations; identical strict classifier; no weak runtime exemption')
