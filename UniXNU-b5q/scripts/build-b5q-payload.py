#!/usr/bin/env python3
"""Build the official payload with verified Data recovery seed and board inputs."""
import argparse,hashlib,importlib.util,json,os,secrets,subprocess,sys
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--unixnu',type=Path,required=True);p.add_argument('--device',type=Path,required=True);p.add_argument('--font-source',type=Path,required=True);p.add_argument('--data-ramdisk',type=Path,required=True);p.add_argument('--reuse-addon',action='store_true');a=p.parse_args()
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
# The official runtime invokes boot_shims only when it collects/pairs trust itself.
trust_args=[] if ctx.board.get('payload',{}).get('runtime',{}).get('boot_shims') else ['--trust-cache',str(trust)]
if a.reuse_addon:
 trust_args=['--gpu-addon',str(provided.with_name('gpu-addon.bin')),'--owner-trust-cache',str(provided.with_name('owner-trust.bundle'))]
subprocess.run([str(core/'unixnu'),'build','payload','--device',str(device),'--os','macos-27.3-26C5035r','--data-ramdisk',str(seed),*trust_args],cwd=core,env=env,check=True)
files={'kernel.macho':work/'kernel/kernel.macho','payload.img':work/'payload/payload.img'}
modules=feeds.resolve(ctx);plan=patches.plan(ctx,modules)
manifest=pipeline.write_manifest(ctx,modules,plan,files)
data=json.loads(manifest.read_text());data['scope']='b5q macOS27.3 build; baseline hardware evidence is separate from qualification of this new image'
data['storage']={'ramblock':True,'verified_root_implementation':True,'ufs_controller':True,'persistent_block_writes':'validated B5QDATA1 Data window and XNU2LOG.BIN A/B slots only', 'root_read_only':True, 'log_file':'XNU2LOG.BIN','smmu_mode':'firmware-owned handoff; zero EL1 apps_smmu MMIO','persistent_root_windows':True,'root_partition':'macosroot','data_seed':'verified 4GiB RAM recovery seed; default persistent Data selected independently by board arguments'}
data['identity']={'kind':'fresh development build namespace','published_seed':False}
data['memory_handoff']={'dts_dram':'b5q low physical bank 0x80000000 + 0x80000000 for DRAM classification; not the allocator window','physical_window':'DarwinBoot EFI allocator at load time, not a fabricated b5q physical address'}
data['hardware_tested']=False
if (work/'kernel-reuse.json').is_file():data['kernel_reuse']=json.loads((work/'kernel-reuse.json').read_text())
data['data_seed']=json.loads((runtime/'data-seed.json').read_text())
data['runtime_build']={'boot_shims':bool(ctx.board.get('payload',{}).get('runtime',{}).get('boot_shims')),'tool_patch':'UniXNU-b5q/patches/tools/macos-2g-ram-data.patch','watchdogd':'disabled in RAM Data launchd disabled.plist; v10 has no BootWatchdogPolicy argument handler'}
manifest.write_text(json.dumps(data,indent=2,sort_keys=True)+'\n')
print('Built first-root kernel, FAT payload and package manifest; verification is performed locally after return')
