#!/usr/bin/env python3
"""Create a fresh template-derived Data seed with the pinned official Mac tool.

Root images are re-extracted from Apple's original IPSW on the runner. No
existing board seed, account, identity or root image is reused.
"""
import argparse,hashlib,importlib.util,json,os,subprocess,sys,tomllib,uuid
from pathlib import Path
from types import SimpleNamespace
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--unixnu',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--gpt',type=Path,required=True);a=p.parse_args();core=a.unixnu.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True);sys.path.insert(0,str(core/'scripts'))
from unixnu.ipsw import Ipsw
from unixnu.util import sha256_file
profile=tomllib.loads((core/'profiles/os/macos-27.3-26C5035r/profile.toml').read_text());gpt=json.loads(a.gpt.read_text());part=gpt['selected']['macosroot'];root_bytes=gpt['root_image_bytes'];capacity=part['size_bytes']
# Same capacity formula as official seed-data-grow.py auto_gib: 4MiB guard,
# 1GiB default reserve, bitmap/header and one further GiB margin.
spec=importlib.util.spec_from_file_location('official_seed_grow',core/'scripts/seed-data-grow.py');grow=importlib.util.module_from_spec(spec);sys.path.insert(0,str(core/'drivers/DarwinBoot/Test'));spec.loader.exec_module(grow)
grow.root_image_bytes=lambda:root_bytes
gib=grow.auto_gib(capacity,1024)
if not 3<=gib<=1024:raise SystemExit('GPT/root layout cannot hold an official Data seed')
ctx=SimpleNamespace(board=profile,out_root=out/'inputs',args=SimpleNamespace(ipsw=None),option_text=lambda key,env:None)
source=Ipsw(ctx,profile['ipsw']['url']);os_image=source.disk_image('OS');digest=sha256_file(os_image)
if digest!=profile['root']['os_image_sha256']:raise SystemExit('Fresh OS image differs from exact profile pin')
runtime=out/'runtime';runtime.mkdir(exist_ok=True);seed=runtime/'data.dbr'
subprocess.run(['sudo','-n',sys.executable,str(core/'scripts/make-macos-data-seed.py'),str(os_image),str(seed),'--gib',str(gib)],check=True)
spec=importlib.util.spec_from_file_location('packed_seed',core/'drivers/DarwinBoot/Test/packed_ramdisk.py');packed=importlib.util.module_from_spec(spec);spec.loader.exec_module(packed);logical,regions=packed.regions(seed.read_bytes());assert logical==gib*2**30
identities=set()
for _,data in regions:
 for at in range(0,len(data),4096):
  block=data[at:at+4096]
  if block[32:36]==b'APSB':identities.add(str(uuid.UUID(bytes=bytes(block[240:256]))).upper())
if len(identities)!=1:raise SystemExit('Require exactly one APFS Data volume UUID')
record={'profile':'macos-27.3-26C5035r','source':'fresh Apple IPSW OS template; pinned official make-macos-data-seed.py','os_image_sha256':digest,'bytes':seed.stat().st_size,'sha256':sha256_file(seed),'logical_bytes':logical,'data_gib':gib,'volume_uuid':identities.pop(),'fresh_first_install':True,'template_owners_preserved':True,'account_created':False,'skip_setup':False,'auto_login':False,'existing_kernel_bound':False,'macosroot_partition_bytes':capacity,'root_image_bytes':root_bytes,'size_formula':'official seed-data-grow.auto_gib(capacity, default 1024MiB reserve); no persistent transport enabled','ci_run':os.environ.get('GITHUB_RUN_ID'),'hardware_tested':False}
(runtime/'data-seed.json').write_text(json.dumps(record,indent=2)+'\n');print('PASS: actual template-derived Data seed; administrator/Setup and kernel binding remain explicit integration tasks')
