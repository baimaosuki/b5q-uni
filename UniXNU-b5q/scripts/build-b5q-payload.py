#!/usr/bin/env python3
"""Build/verify the official FAT payload and a genuine volatile APFS RAM seed.

This is the user's compile/link bring-up target. It does not invent Samsung
physical memory, include persistent OS root windows, or claim a desktop boot.
"""
import argparse,hashlib,importlib.util,json,os,secrets,subprocess,sys
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--unixnu',type=Path,required=True);p.add_argument('--device',type=Path,required=True);p.add_argument('--font-source',type=Path,required=True);a=p.parse_args()
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
if not seed.exists():
 raw=runtime/'ram-data.cdr'
 subprocess.run(['hdiutil','create','-size','512m','-layout','NONE','-fs','APFS','-volname','Data','-type','UDTO',str(raw)],check=True)
 spec=importlib.util.spec_from_file_location('b5q_packed_ramdisk',ctx.tree/'drivers/DarwinBoot/Test/packed_ramdisk.py');packed=importlib.util.module_from_spec(spec);spec.loader.exec_module(packed)
 packed.pack(raw,seed)
 logical,regions=packed.regions(seed.read_bytes())
 if logical!=512*1024*1024:raise SystemExit('Unexpected volatile APFS logical size')
 raw.unlink()
env=dict(os.environ,UNIXNU_UNIQUE_CHIP_ID=seedfile.read_text().strip(),UNIXNU_UEFI=str(font))
subprocess.run([str(core/'unixnu'),'build','payload','--device',str(device),'--os','macos-27.3-26C5035r','--data-ramdisk',str(seed)],cwd=core,env=env,check=True)
files={'kernel.macho':work/'kernel/kernel.macho','payload.img':work/'payload/payload.img'}
modules=feeds.resolve(ctx);plan=patches.plan(ctx,modules)
manifest=pipeline.write_manifest(ctx,modules,plan,files)
data=json.loads(manifest.read_text());data['scope']='RAM-only compile/link bring-up; not a full macOS installation or hardware qualification'
data['storage']={'ramblock':True,'verified_root_implementation':True,'ufs_controller':False,'persistent_root_windows':False,'data_seed':'new 512MiB volatile APFS filesystem, not a reused installation'}
data['identity']={'kind':'fresh development build namespace','published_seed':False}
data['memory_handoff']={'dts_dram':'zero placeholder from the Samsung static source','physical_window':'DarwinBoot EFI allocator at load time, not a fabricated b5q physical address'}
data['hardware_tested']=False
manifest.write_text(json.dumps(data,indent=2,sort_keys=True)+'\n')
for name,path in files.items():
 digest=hashlib.sha256(path.read_bytes()).hexdigest()
 if path.stat().st_size!=data['outputs'][name]['bytes'] or digest!=data['outputs'][name]['sha256']:raise SystemExit('Manifest mismatch: '+name)
# Verify actual FAT members against the linked kernel and packed RAM seed.
for relative,source in [('EFI/UniXNU/Payloads/kernel.macho',None),('EFI/UniXNU/Payloads/scratch-data.img',seed),('EFI/UniXNU/Payloads/kernel.macho.adt',None),('EFI/UniXNU/unixnu.toml',None)]:
 content=subprocess.check_output(['mtype','-i',str(files['payload.img']),'::/'+relative])
 if not content:raise SystemExit('Empty payload member '+relative)
 if source and hashlib.sha256(content).hexdigest()!=hashlib.sha256(source.read_bytes()).hexdigest():raise SystemExit('Payload seed mismatch')
print('PASS: actual kernel, FAT members, volatile APFS seed and official package manifest hashes')
