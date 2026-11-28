#!/usr/bin/env python3
"""Reconstruct the exact CI firmware patch inputs before spending another run."""
import argparse,hashlib,json,os,re,subprocess,tempfile,shutil
from pathlib import Path
R=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True)
p.add_argument('--media',action='store_true',help='Include optional P4 audio/video retained-domain patches')
p.add_argument('--dp',action='store_true',help='Include the P5 validated GOP tail handoff')
a=p.parse_args()
if "b5q-dp=1" in (R/"UniXNU-b5q/board.toml").read_text():a.dp=True
patch=R/'patches/uefi-b5q';records=[]
groups=[('uefi-b5q','b303410c8e401fc9419ae65a024356ed09a438ef',[*sorted(patch.glob('000[123]-*.patch')),patch/'0005-b5q-physical-esp.patch',patch/'0007-b5q-pcie-dma.patch']),
        ('UniXNU','563595abedfdfa413ad583b66b6176d82007e633',[patch/'0006-unixnu-ramdisk-direct-decompress.patch']),
        ('UniXNU/drivers/DarwinBoot','5243c68ec332a227fe3680cd5da6d5a0e127035c',[patch/'0004-darwinboot-b5q-usb-dma.patch',patch/'0008-darwinboot-b5q-pcie-dma.patch'])]
if a.media or a.dp:
 groups[0][2].append(patch/'0009-b5q-media-dma.patch')
 groups[2][2].append(patch/'0010-darwinboot-b5q-media-dma.patch')
if a.dp:
 groups[0][2].append(patch/'0011-b5q-dp-splash-tail.patch')
 groups[0][2].append(patch/'0013-b5q-reserved-dma-guards.patch')
 groups[0][2].append(patch/'0014-b5q-dma-unprivileged-wbis.patch')
 groups[0][2].append(patch/'0015-b5q-usb-map-lifetime.patch')
 groups[2][2].append(patch/'0012-darwinboot-b5q-dp-tail.patch')
 groups[2][2].append(patch/'0016-darwinboot-dma-order-inputs.patch')
 groups[0][2].append(patch/'0017-b5q-dma-attach-flush.patch')
 groups[2][2].append(patch/'0018-darwinboot-usb-coverage.patch')
 groups[0][2].append(patch/'0019-b5q-pcie-64m.patch')
 groups[2][2].append(patch/'0020-darwinboot-pcie-64m.patch')
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
  mirror=Path(td)/('live-'+str(index));mirror.mkdir()
  for name in sorted(paths):
   target=mirror/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(R/repo/name,target)
  diff=subprocess.run(['diff','-ruN','--exclude=.git',str(dest),str(mirror)],capture_output=True,text=True)
  assert diff.returncode==0,(repo,diff.stdout,diff.stderr)
  if index==0:
   inf='Binaries/b5q/QcomPkg/Drivers/UFSDxe/UFSDxe.patched.efi'
   target=dest/inf;target.parent.mkdir(parents=True,exist_ok=True);target.symlink_to(R/repo/inf)
   env=dict(os.environ,UNIXNU_UEFI=str(dest),UNIXNU_DEVICE=str(Path(td)/'record'))
   subprocess.run(['python3',str(R/'UniXNU-b5q/scripts/check-b5q-uefi.py')],env=env,check=True)
  records.append(dict(repo=repo,revision=revision,patch_sha256={f.name:hashlib.sha256(f.read_bytes()).hexdigest()for f in patches},reconstructed_source_sha256=identities,diff_ruN_returncode=diff.returncode,diff_ruN_stdout=diff.stdout))
a.out.parent.mkdir(parents=True,exist_ok=True)
a.out.write_text(json.dumps(dict(passed=True,groups=records,hardware_verified=False),indent=2)+'\n')
print('PASS',sum(len(g[2])for g in groups),'firmware patches reconstruct exact current sources; retained DMA, UFSDxe, USB exclusion, memory reservations and direct decompressor gates')
