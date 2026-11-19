#!/usr/bin/env python3
"""Stage the completed v10 kernel for a payload-only rebuild; never compile it."""
import argparse,json,shutil,sys
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--unixnu',type=Path,required=True);p.add_argument('--device',type=Path,required=True);p.add_argument('--artifact',type=Path,required=True);a=p.parse_args()
core=a.unixnu.resolve();device=a.device.resolve();sys.path.insert(0,str(core/'scripts'))
from unixnu.cli import parser
from unixnu.config import Context
ctx=Context(parser().parse_args(['build','payload','--device',str(device),'--os','macos-27.3-26C5035r']))
found=list(a.artifact.rglob('package.manifest.json'))
if len(found)!=1:raise SystemExit('Existing v10 artifact must contain one package manifest')
source=found[0].parent;destination=ctx.work/'kernel';destination.mkdir(parents=True,exist_ok=True)
for path in (source/'kernel').glob('*'):
 if path.is_file():shutil.copyfile(path,destination/path.name)
record={'source_run':44606991063,'source_commit':'b6fd887c07b729e7e6a36d144aabe04f7648b842','kernel_recompiled':False,'prior_manifest':json.loads(found[0].read_text())}
(ctx.work/'kernel-reuse.json').write_text(json.dumps(record,indent=2)+'\n')
print('Staged completed v10 kernel; next command builds payload only')
