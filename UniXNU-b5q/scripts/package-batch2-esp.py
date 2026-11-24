#!/usr/bin/env python3
"""Use the official payload assets with separate persistent/RAM boot profiles."""
import argparse,copy,hashlib,json,shutil,subprocess,sys,tempfile,tomllib
from pathlib import Path
R=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--unixnu',type=Path,required=True);p.add_argument('--inputs',type=Path,required=True);p.add_argument('--ci',type=Path);p.add_argument('--out',type=Path);p.add_argument('--fd',type=Path);p.add_argument('--gates',type=Path);a=p.parse_args()
sys.path.insert(0,str(a.unixnu.resolve()/'scripts'))
from unixnu.cli import parser
from unixnu.config import Context
from unixnu.devicetree import generate,compile_hardware
from unixnu import ramdisk
from unixnu.payload import check_args
from b5q_gpu_adt import preserve as preserve_gpu_firmware,verify as verify_gpu_firmware
ctx=Context(parser().parse_args(['build','payload','--device',str(R/'UniXNU-b5q'),'--os','macos-27.3-26C5035r']))
work=a.ci.resolve()if a.ci else ctx.work;payload=work/'payload/payload.img';esp=a.out.resolve()if a.out else work/'esp.img'
if a.ci:
 if not a.gates or not a.fd:raise SystemExit('Returned payload packaging requires local gate receipt and paired FD')
 gate=json.loads(a.gates.read_text());assert gate['passed']and gate['returned_binaries_verified']
 assert gate['source_sha256']=={n:hashlib.sha256((R/n).read_bytes()).hexdigest()for n in gate['source_sha256']},'Source changed since acceptance'
 assert gate['payload_sha256']==hashlib.sha256(payload.read_bytes()).hexdigest()
 esp.parent.mkdir(parents=True,exist_ok=True)
def run(*cmd):subprocess.run(list(map(str,cmd)),check=True)
def record(p):
 with p.open('rb')as f:return dict(bytes=p.stat().st_size,sha256=hashlib.file_digest(f,'sha256').hexdigest())
with tempfile.TemporaryDirectory(prefix='b5q-batch2-package-')as td:
 t=Path(td);stage=t/'files';stage.mkdir()
 if ramdisk.packed(payload):raw=t/'payload.fat';ramdisk.decode(payload,raw);payload=raw
 run('mcopy','-s','-i',payload,'::/EFI',stage)
 boot=stage/'EFI/UniXNU';assets=boot/'Payloads'
 for src,dest in [('BOOTAA64.EFI',stage/'EFI/BOOT/BOOTAA64.EFI'),('DarwinBoot.efi',boot/'Drivers/DarwinBoot.efi')]:dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(a.inputs/src,dest)
 if a.ci:
  from unixnu.boot_template import loader_pe
  assert (boot/'Drivers/DarwinBoot.efi').read_bytes()==loader_pe(a.fd.read_bytes(),'1b64af87-8415-4b57-9b16-680d70913b9f')
  seedmeta=json.loads((work/'runtime/data-seed.json').read_text());assert record(assets/'scratch-data.img')['sha256']==seedmeta['sha256']
  import importlib.util,struct
  spec=importlib.util.spec_from_file_location('fs',R/'scripts/b5q-install/package-usb-dma-esp.py');fs=importlib.util.module_from_spec(spec);spec.loader.exec_module(fs)
  chosen=fs.adt_nodes((assets/'kernel.macho.adt').read_bytes())['/chosen'][2]
  gpu_firmware=preserve_gpu_firmware(ctx.board,chosen)
  seed=format(struct.unpack('<Q',chosen['unique-chip-id'])[0],'016x');dtb=work/'device-tree/hardware.dtb'
 else:
  assert record(boot/'Drivers/DarwinBoot.efi')['sha256']=='100080919035179c86c1f4b1eee16e6a8a46166beee95234dc2c842995009cde'
  assert record(assets/'scratch-data.img')['sha256']=='d2e32a5f7dd37807a816d857d8b62eba41615c5da9ac335c2322e3c7a35ffc70'
  seed=(work/'runtime/build-platform-seed').read_text().strip();dtb=compile_hardware(ctx)
 # DarwinBoot uses kernel-path + .adt; a separate byte-identical kernel path
 # is required to select the independent RAM profile without changing firmware.
 fallback=assets/'RAM';fallback.mkdir()
 for asset in assets.iterdir():
  if asset.is_file()and asset.name.startswith('kernel.macho')and asset.suffix!='.adt':shutil.copyfile(asset,fallback/asset.name)
 normal=generate(dtb,ctx.board,unique_chip_id=seed,data=False,trust=True,addon=True,root_policies=False)
 if a.ci:assert verify_gpu_firmware(fs.adt_nodes(normal)['/chosen'][2])==gpu_firmware
 (assets/'kernel.macho.adt').write_bytes(normal)
 ram=copy.deepcopy(ctx.board);ram['payload']['adt']['persistent_data']=False
 ram['payload']['adt']['owned_memory_size']='0x100000000'
 ram['payload']['adt'].pop('owned_memory_outside_ranges',None);ram['payload']['adt'].pop('owned_memory_outside_reserved',None)
 (fallback/'kernel.macho.adt').write_bytes(generate(dtb,ram,unique_chip_id=seed,data=True,trust=True,addon=True,root_policies=False))
 if a.ci:assert verify_gpu_firmware(fs.adt_nodes((fallback/'kernel.macho.adt').read_bytes())['/chosen'][2])==gpu_firmware
 from b5q_menu import profiles,config
 entries=profiles(ctx.board['payload']['kernel_args'])
 ram.setdefault('adt',{}).setdefault('chosen',{}).setdefault('u32',{})['b5q-feature-mask']=0
 (fallback/'kernel.macho.adt').write_bytes(generate(dtb,ram,unique_chip_id=seed,data=True,trust=True,addon=True,root_policies=False))
 (boot/'unixnu.toml').write_text(config(ctx.board['payload']['kernel_args']))
 if a.ci:
  for path in assets.rglob('*.adt'):
   assert verify_gpu_firmware(fs.adt_nodes(path.read_bytes())['/chosen'][2])==gpu_firmware
 (stage/'startup.nsh').write_text('\\EFI\\BOOT\\BOOTAA64.EFI\r\n')
 run(sys.executable,R/'scripts/b5q-install/make-xnu2log.py','--out',stage/'XNU2LOG.BIN','--token','411839cbaebac4088c251c0ea57579a2')
 with esp.open('wb')as f:f.truncate(800<<20)
 run('mformat','-i',esp,'-T','204800','-S','5','-c','1','-F','-v','B5QMACOS','::')
 for name in ['EFI','startup.nsh','XNU2LOG.BIN']:run('mcopy','-s','-i',esp,stage/name,'::/')
 metadata=dict(scope='New Batch2; persistent default and original 4GiB RAM recovery; hardware untested',members={str(p.relative_to(stage)):record(p)for p in stage.rglob('*')if p.is_file()},esp=record(esp),normal_no_initrd=True,menu_feature_masks={'full':ctx.board['adt']['chosen']['u32']['b5q-feature-mask'],'daily':0,'safe':0,'ram-fallback':0},menu_arg_bytes={e['id']:len(e['args'].encode())for e in entries},ram_recovery_seed_sha256=record(assets/'scratch-data.img')['sha256'])
 (work/'batch2-package.json').write_text(json.dumps(metadata,indent=2)+'\n')
print('Packaged New Batch2 800MiB4Kn ESP; persistent default loads no RAM seed; v30 loader retained')
