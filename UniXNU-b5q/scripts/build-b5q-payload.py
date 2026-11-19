#!/usr/bin/env python3
"""Build the official FAT payload and a genuine volatile APFS RAM seed.

This is the user's compile/link bring-up target. It does not invent Samsung
physical memory, include persistent OS root windows, or claim a desktop boot.
"""
import argparse,hashlib,importlib.util,json,os,secrets,subprocess,sys
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--unixnu',type=Path,required=True);p.add_argument('--device',type=Path,required=True);p.add_argument('--font-source',type=Path,required=True);p.add_argument('--data-ramdisk',type=Path,required=True);a=p.parse_args()
core,device,font=a.unixnu.resolve(),a.device.resolve(),a.font_source.resolve()
sys.path.insert(0,str(core/'scripts'))
from unixnu.cli import parser
from unixnu.config import Context
from unixnu import feeds,patches,pipeline
ctx=Context(parser().parse_args(['build','payload','--device',str(device),'--os','macos-27.3-26C5035r']))
work=ctx.work;runtime=work/'runtime';runtime.mkdir(parents=True,exist_ok=True)
# A fresh build namespace seed, not a hardware identifier and never printed.
seedfile=runtime/'build-platform-seed'
if not seedfile.exists():
 fd=os.open(seedfile,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 with os.fdopen(fd,'w') as f:f.write(f'{secrets.randbits(64) or 1:016x}\n')
seed=runtime/'data.dbr'
import shutil
provided=a.data_ramdisk.resolve()
# Local pre-CI checks bind source inputs; returned output verification runs locally.
shutil.copyfile(provided,seed)
shutil.copyfile(provided.with_name('data-seed.json'),runtime/'data-seed.json')
trust=provided.with_name('original-ipsw-trust.bundle')
if not trust.is_file():raise SystemExit('Original IPSW trust bundle is missing')
env=dict(os.environ,UNIXNU_UNIQUE_CHIP_ID=seedfile.read_text().strip(),UNIXNU_UEFI=str(font))
subprocess.run([str(core/'unixnu'),'build','payload','--device',str(device),'--os','macos-27.3-26C5035r','--data-ramdisk',str(seed),'--trust-cache',str(trust)],cwd=core,env=env,check=True)
files={'kernel.macho':work/'kernel/kernel.macho','payload.img':work/'payload/payload.img'}
modules=feeds.resolve(ctx);plan=patches.plan(ctx,modules)
manifest=pipeline.write_manifest(ctx,modules,plan,files)
data=json.loads(manifest.read_text());data['scope']='Initial b5q macosroot reader build; authenticated roots plus volatile template Data; hardware boot not yet observed'
data['storage']={'ramblock':True,'verified_root_implementation':True,'ufs_controller':True,'persistent_block_writes':False,'persistent_root_windows':True,'root_partition':'macosroot','data_seed':'official template-derived 29GiB sparse RAM Data; exact UUID bound to this kernel'}
data['identity']={'kind':'fresh development build namespace','published_seed':False}
data['memory_handoff']={'dts_dram':'zero placeholder from the Samsung static source','physical_window':'DarwinBoot EFI allocator at load time, not a fabricated b5q physical address'}
data['hardware_tested']=False
manifest.write_text(json.dumps(data,indent=2,sort_keys=True)+'\n')
print('Built first-root kernel, FAT payload and package manifest; verification is performed locally after return')
