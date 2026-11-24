#!/usr/bin/env python3
"""Use the official payload assets with separate persistent/RAM boot profiles."""
import argparse,copy,hashlib,json,shutil,subprocess,sys,tempfile,tomllib
from pathlib import Path
R=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--unixnu',type=Path,required=True);p.add_argument('--inputs',type=Path,required=True);a=p.parse_args()
sys.path.insert(0,str(a.unixnu.resolve()/'scripts'))
from unixnu.cli import parser
from unixnu.config import Context
from unixnu.devicetree import generate,compile_hardware
from unixnu import ramdisk
from unixnu.payload import check_args
ctx=Context(parser().parse_args(['build','payload','--device',str(R/'UniXNU-b5q'),'--os','macos-27.3-26C5035r']))
work=ctx.work;payload=work/'payload/payload.img';esp=work/'esp.img'
def run(*cmd):subprocess.run(list(map(str,cmd)),check=True)
def record(p):
 with p.open('rb')as f:return dict(bytes=p.stat().st_size,sha256=hashlib.file_digest(f,'sha256').hexdigest())
with tempfile.TemporaryDirectory(prefix='b5q-batch2-package-')as td:
 t=Path(td);stage=t/'files';stage.mkdir()
 if ramdisk.packed(payload):raw=t/'payload.fat';ramdisk.decode(payload,raw);payload=raw
 run('mcopy','-s','-i',payload,'::/EFI',stage)
 boot=stage/'EFI/UniXNU';assets=boot/'Payloads'
 for src,dest in [('BOOTAA64.EFI',stage/'EFI/BOOT/BOOTAA64.EFI'),('DarwinBoot.efi',boot/'Drivers/DarwinBoot.efi')]:dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(a.inputs/src,dest)
 assert record(boot/'Drivers/DarwinBoot.efi')['sha256']=='100080919035179c86c1f4b1eee16e6a8a46166beee95234dc2c842995009cde'
 assert record(assets/'scratch-data.img')['sha256']=='d2e32a5f7dd37807a816d857d8b62eba41615c5da9ac335c2322e3c7a35ffc70'
 seed=(work/'runtime/build-platform-seed').read_text().strip();dtb=compile_hardware(ctx)
 # DarwinBoot uses kernel-path + .adt; a separate byte-identical kernel path
 # is required to select the independent RAM profile without changing firmware.
 fallback=assets/'RAM';fallback.mkdir()
 for asset in assets.iterdir():
  if asset.is_file()and asset.name.startswith('kernel.macho')and asset.suffix!='.adt':shutil.copyfile(asset,fallback/asset.name)
 normal=generate(dtb,ctx.board,unique_chip_id=seed,data=False,trust=True,addon=True,root_policies=False)
 (assets/'kernel.macho.adt').write_bytes(normal)
 ram=copy.deepcopy(ctx.board);ram['payload']['adt']['persistent_data']=False
 ram['payload']['adt']['owned_memory_size']='0x100000000'
 ram['payload']['adt'].pop('owned_memory_outside_ranges',None);ram['payload']['adt'].pop('owned_memory_outside_reserved',None)
 (fallback/'kernel.macho.adt').write_bytes(generate(dtb,ram,unique_chip_id=seed,data=True,trust=True,addon=True,root_policies=False))
 from b5q_menu import profiles,config
 entries=profiles(ctx.board['payload']['kernel_args'])
 ram.setdefault('adt',{}).setdefault('chosen',{}).setdefault('u32',{})['b5q-feature-mask']=0
 (fallback/'kernel.macho.adt').write_bytes(generate(dtb,ram,unique_chip_id=seed,data=True,trust=True,addon=True,root_policies=False))
 (boot/'unixnu.toml').write_text(config(ctx.board['payload']['kernel_args']))
 (stage/'startup.nsh').write_text('\\EFI\\BOOT\\BOOTAA64.EFI\r\n')
 run(sys.executable,R/'scripts/b5q-install/make-xnu2log.py','--out',stage/'XNU2LOG.BIN','--token','411839cbaebac4088c251c0ea57579a2')
 with esp.open('wb')as f:f.truncate(800<<20)
 run('mformat','-i',esp,'-T','204800','-S','5','-c','1','-F','-v','B5QMACOS','::')
 for name in ['EFI','startup.nsh','XNU2LOG.BIN']:run('mcopy','-s','-i',esp,stage/name,'::/')
 metadata=dict(scope='New Batch2; persistent default and original 4GiB RAM recovery; hardware untested',members={str(p.relative_to(stage)):record(p)for p in stage.rglob('*')if p.is_file()},esp=record(esp),normal_no_initrd=True,menu_feature_masks={'full':ctx.board['adt']['chosen']['u32']['b5q-feature-mask'],'daily':0,'safe':0,'ram-fallback':0},menu_arg_bytes={e['id']:len(e['args'].encode())for e in entries},ram_recovery_seed_sha256=record(assets/'scratch-data.img')['sha256'])
 (work/'batch2-package.json').write_text(json.dumps(metadata,indent=2)+'\n')
print('Packaged New Batch2 800MiB4Kn ESP; persistent default loads no RAM seed; v30 loader retained')
