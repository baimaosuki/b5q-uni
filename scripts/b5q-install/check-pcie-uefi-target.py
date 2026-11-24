#!/usr/bin/env python3
"""Compile new firmware/loader sources with qualified EDK2 module flags."""
import argparse,hashlib,json,re,shlex,subprocess
from pathlib import Path
R=Path(__file__).resolve().parents[2];out=R/'artifacts/b5q-p3-work/uefi-target';out.mkdir(exist_ok=True)
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--media',action='store_true');p.add_argument('--dp',action='store_true');a=p.parse_args()
if a.media or a.dp:out=R/'artifacts/b5q-p4-work/uefi-target';out.mkdir(exist_ok=True)
build=R/'uefi-b5q/Build/b5qPkg/DEBUG_CLANGPDB/AARCH64'
groups=[(build/'b5qPkg/Drivers/B5qHandoffDxe/B5qHandoffDxe',R/'uefi-b5q/Platforms/Samsung/b5qPkg/Drivers/B5qHandoffDxe',['PcieDma.c','B5qHandoffDxe.c','UsbDma.c']),
        (build/'DarwinBootPkg/Driver/DarwinBoot',R/'UniXNU/drivers/DarwinBoot/DarwinBootPkg/Driver',['DarwinBoot.c'])]
if a.media or a.dp:groups[0][2].append('MediaDma.c')
if a.dp:
 out=R/'artifacts/b5q-p5-work/uefi-target';out.mkdir(exist_ok=True)
 groups[0][2].append('DpDma.c')
groups.append((build/'b5qPkg/Library/MemoryMapLib/MemoryMapLib',R/'uefi-b5q/Platforms/Samsung/b5qPkg/Library/MemoryMapLib',['MemoryMapLib.c']))
records=[]
for directory,source,names in groups:
    text=(directory/'GNUmakefile').read_text().replace('\\\n',' ')
    flags=re.search(r'^CC_FLAGS = (.+)$',text,re.M)[1]
    include=re.search(r'^INC = (.+)$',text,re.M)[1]
    variables={'WORKSPACE':str(R/'uefi-b5q'),'DEBUG_DIR':str(directory/'DEBUG'),'BASE_NAME':directory.name}
    for k,v in variables.items():flags=flags.replace('$('+k+')',v);include=include.replace('$('+k+')',v)
    assert '$('not in flags+include
    for name in names:
        target=out/(Path(name).stem+'.obj');command=['/usr/lib/llvm-17/bin/clang',*shlex.split(flags),*shlex.split(include),'-I',str(source),'-fno-lto','-c',str(source/name),'-o',str(target)]
        result=subprocess.run(command,capture_output=True,text=True)
        (out/(name+'.log')).write_text(result.stdout+result.stderr)
        if result.returncode:raise SystemExit(result.stderr)
        records.append(dict(source=str(source/name),sha256=hashlib.sha256((source/name).read_bytes()).hexdigest(),command=command,object_sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
(out/'report.json').write_text(json.dumps(dict(passed=True,link_pending=True,hardware_verified=False,objects=records),indent=2)+'\n')
print('PASS actual EDK2 target compile: PCIe HAL producer, handoff entry, DarwinBoot consumer')
