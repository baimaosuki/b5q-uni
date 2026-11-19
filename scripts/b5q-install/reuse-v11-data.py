#!/usr/bin/env python3
"""Extract the completed v11 RAM Data and original trust from its existing payload."""
import argparse,json,subprocess,struct,sys
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--artifact',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
found=list(a.artifact.rglob('package.manifest.json'))
if len(found)!=1:raise SystemExit('Expected the completed v11 build artifact')
source=found[0].parent;out=a.out;out.mkdir(parents=True,exist_ok=True)
for src,dest in [('scratch-data.img','data.dbr'),('kernel.macho.trustcache','original-ipsw-trust.bundle')]:
 subprocess.run(['mcopy','-i',str(source/'payload/payload.img'),'::/EFI/UniXNU/Payloads/'+src,str(out/dest)],check=True)
# Preserve the three original Apple modules, excluding the previous owner module.
f=out/'original-ipsw-trust.bundle';data=f.read_bytes();count=struct.unpack_from('<I',data)[0];offsets=list(struct.unpack_from(f'<{count}I',data,4))+[len(data)];mods=[data[offsets[i]:offsets[i+1]] for i in range(3)];start=16;result=struct.pack('<4I',3,start,start+len(mods[0]),start+len(mods[0])+len(mods[1]))+b''.join(mods);f.write_bytes(result)
(out/'data-seed.json').write_bytes((source/'runtime/data-seed.json').read_bytes())
(out/'reuse.json').write_text(json.dumps({'source_run':44616733365,'source_commit':'5302eabc4ba6a834d4cd133ba14a0d656af0fd50','data_regenerated':False,'source_seed_metadata':json.loads((out/'data-seed.json').read_text())},indent=2)+'\n')
print('Reused v11 2GiB sparse RAM Data and unchanged original Apple trust modules')
