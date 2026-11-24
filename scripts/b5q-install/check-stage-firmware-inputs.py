#!/usr/bin/env python3
"""Reconstruct the exact CI firmware patch inputs before spending another run."""
import argparse,hashlib,json,os,re,subprocess,tempfile
from pathlib import Path
R=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True)
p.add_argument('--media',action='store_true',help='Include optional P4 audio/video retained-domain patches')
a=p.parse_args()
patch=R/'patches/uefi-b5q';records=[]
groups=[('uefi-b5q','b303410c8e401fc9419ae65a024356ed09a438ef',[*sorted(patch.glob('000[123]-*.patch')),patch/'0005-b5q-physical-esp.patch',patch/'0007-b5q-pcie-dma.patch']),
        ('UniXNU','563595abedfdfa413ad583b66b6176d82007e633',[patch/'0006-unixnu-ramdisk-direct-decompress.patch']),
        ('UniXNU/drivers/DarwinBoot','5243c68ec332a227fe3680cd5da6d5a0e127035c',[patch/'0004-darwinboot-b5q-usb-dma.patch',patch/'0008-darwinboot-b5q-pcie-dma.patch'])]
if a.media:
 groups[0][2].append(patch/'0009-b5q-media-dma.patch')
 groups[2][2].append(patch/'0010-darwinboot-b5q-media-dma.patch')
with tempfile.TemporaryDirectory(prefix='b5q-stage-firmware-')as td:
 for index,(repo,revision,patches)in enumerate(groups):
  dest=Path(td)/str(index);dest.mkdir();paths=set();subprocess.run(['git','init','-q',str(dest)],check=True)
  for f in patches:
   assert f.is_file(),f
   paths.update(re.findall(r'^diff --git a/(\S+) b/\S+',f.read_text(),re.M))
  for name in paths:
   r=subprocess.run(['git','-C',str(R/repo),'show',revision+':'+name],stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
   if not r.returncode:
    target=dest/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(r.stdout)
  for f in patches:
   result=subprocess.run(['git','-C',str(dest),'apply','--whitespace=error'],input=f.read_bytes(),stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
   assert not result.returncode,(str(f),result.stdout.decode())
  # The reconstructed sources must be the sources of the retained known-good
  # local v30 firmware, not a different historical file with the same name.
  identities={}
  for name in sorted(paths):
   target=dest/name;actual=R/repo/name
   assert target.is_file() and actual.is_file() and target.read_bytes()==actual.read_bytes(),(repo,name)
   identities[name]=hashlib.sha256(target.read_bytes()).hexdigest()
  if index==0:
   inf='Binaries/b5q/QcomPkg/Drivers/UFSDxe/UFSDxe.patched.efi'
   target=dest/inf;target.parent.mkdir(parents=True,exist_ok=True);target.symlink_to(R/repo/inf)
   env=dict(os.environ,UNIXNU_UEFI=str(dest),UNIXNU_DEVICE=str(Path(td)/'record'))
   subprocess.run(['python3',str(R/'UniXNU-b5q/scripts/check-b5q-uefi.py')],env=env,check=True)
  records.append(dict(repo=repo,revision=revision,patch_sha256={f.name:hashlib.sha256(f.read_bytes()).hexdigest()for f in patches},reconstructed_source_sha256=identities))
a.out.parent.mkdir(parents=True,exist_ok=True)
a.out.write_text(json.dumps(dict(passed=True,groups=records,hardware_verified=False),indent=2)+'\n')
print('PASS',sum(len(g[2])for g in groups),'firmware patches reconstruct exact current sources; retained DMA, UFSDxe, USB exclusion, memory reservations and direct decompressor gates')
