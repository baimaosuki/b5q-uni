#!/usr/bin/env python3
"""Read back the actual storage-only fix ESP, preserving every other asset."""
import argparse,hashlib,importlib.util,json,struct,subprocess,sys,tempfile,tomllib
from pathlib import Path
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'sources/UniXNU/kits/XnuPrelink'))
from kc_image import Image
def load(path):
 s=importlib.util.spec_from_file_location(path.stem,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def sha(path):
 with path.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
def main():
 p=argparse.ArgumentParser(description=__doc__)
 for name in ['esp','baseline-esp','diagnostics','out']:p.add_argument('--'+name,type=Path,required=True)
 a=p.parse_args();a.out.mkdir(exist_ok=True,parents=True)
 fs=load(R/'scripts/b5q-install/package-usb-dma-esp.py');fs.image_format(a.esp);subprocess.run(['fsck.fat','-n',str(a.esp)],check=True)
 subprocess.run([sys.executable,str(R/'scripts/b5q-install/verify-esp-log.py'),'--esp',str(a.esp),'--out',str(a.out/'log-allocation.json')],check=True)
 def unique(name):
  rows=list(a.diagnostics.rglob(name));assert len(rows)==1,(name,rows);return rows[0]
 relink=json.loads(unique('incremental-relink.json').read_text())
 assert relink['relink_version']=='data-mount'and relink['source_run']==45115332412
 assert relink['core_translation_units_compiled']==0 and relink['board_translation_units_compiled']==2 and not relink['gpu_recompiled']and not relink['data_regenerated']
 assert relink['unchanged_core_after_link_sha256']==relink['expected_core_sha256']=='88703fdc7eb18011294b5fe634d23b085496732f1e8bd4dd04e47f82dbe6ec2b'
 changed={}
 for archive,after in relink['output_archive_members'].items():
  before=relink['input_archive_members'][archive];diff=sorted(n for n in before.keys()|after.keys()if before.get(n)!=after.get(n));changed[archive]=diff
  assert diff==(['B5qUfs.late.o','NativeRamBlock.late.o']if archive.endswith('/libRamBlock.a')else[]),(archive,diff)
 assert relink['ramblock_source_sha256']==sha(R/'UniXNU/drivers/RamBlock/NativeRamBlock.cpp')
 for name,h in relink['ramblock_patch_sha256'].items():assert h==sha(R/'UniXNU-b5q/scripts'/name)
 for name,info in relink['returned_objects'].items():assert sha(unique(name))==info['sha256']
 km=json.loads(unique('kernel.json').read_text());assert not km['missing']and not km['stubbed']and not km['allow_missing']and km['mapping_complete']
 with tempfile.TemporaryDirectory(prefix='b5q-data-mount-accept-')as td:
  t=Path(td);new=fs.members(a.esp,t/'new');old=fs.members(a.baseline_esp,t/'old');assert set(new)==set(old)
  diff=sorted(n for n in new if new[n]!=old[n]);allowed={'EFI/UniXNU/Payloads/kernel.macho','EFI/UniXNU/Payloads/kernel.macho.crypto-hmac.json','EFI/UniXNU/Payloads/RAM/kernel.macho','EFI/UniXNU/Payloads/RAM/kernel.macho.crypto-hmac.json'}
  assert set(diff)<=allowed,diff
  boot=t/'new/EFI/UniXNU';menu=tomllib.loads((boot/'unixnu.toml').read_text());board=tomllib.loads((R/'UniXNU-b5q/board.toml').read_text());entries={e['id']:e for e in menu['entry']if e['type']=='xnu'}
  assert set(entries)=={'xnu','ram-fallback'}and'initrd'not in entries['xnu']and entries['ram-fallback']['initrd']=='Payloads/scratch-data.img'
  assert entries['xnu']['args']==' '.join(board['payload']['kernel_args'])and len(entries['xnu']['args'].encode())==981
  assert 'b5q-data-ufs=2'in entries['xnu']['args'].split()and'b5q-data-ufs=0'in entries['ram-fallback']['args'].split()
  assert 'offline-mobile-graphics-client'not in entries['xnu']['args']
  profiles={}
  for name,e in entries.items():
   k=boot/e['path'];adt=fs.adt_nodes(k.with_suffix('.macho.adt').read_bytes());chosen=adt['/chosen'][2]
   assert adt['/chosen/asmb'][2]['lp-sip0']==struct.pack('<Q',2)
   assert chosen['darwinboot-memory-size']==struct.pack('<Q',(6 if name=='xnu'else 4)<<30)
   assert chosen['text-fixups']==b''.join(x.encode()+b'\0'for x in board['payload']['text_fixups'])and len(board['payload']['text_fixups'])==2
   profiles[name]=dict(kernel_SHA256=sha(k),args_bytes=len(e['args'].encode()),lp_sip0_hex=adt['/chosen/asmb'][2]['lp-sip0'].hex(),RAM_seed_loaded='initrd'in e)
  assert profiles['xnu']['kernel_SHA256']==profiles['ram-fallback']['kernel_SHA256']
  kernel=boot/'Payloads/kernel.macho';raw=kernel.read_bytes();outer=Image(raw);core=Image(raw,outer.entries['com.apple.kernel'][1]);symbols={n:v for v,ns in core.symbols().items()for n in ns}
  wanted=['_native_ram_block_provider_seed','_native_ram_block_volume_seed','_native_ram_block_volume_device','_b5q_power_start','_sheng_cpu_idle_mach','_ml_outside_memory_pages','_ml_outside_memory_refused']
  assert all(n in symbols for n in wanted)
  assert b'B5qData: media-ready path=%s bytes=%llu retry=%u unique=1'in raw
  assert b'persistent Data media/UUID/BSD readiness timeout or duplicate UUID'in raw
  assert b'TOP6..10'in raw and b'FUA-still-accepted'in raw
  assets=boot/'Payloads';seed=assets/'scratch-data.img';loader=boot/'Drivers/DarwinBoot.efi'
  assert sha(seed)=='d2e32a5f7dd37807a816d857d8b62eba41615c5da9ac335c2322e3c7a35ffc70'
  assert sha(loader)=='100080919035179c86c1f4b1eee16e6a8a46166beee95234dc2c842995009cde'
  assert sha(assets/'kernel.macho.gpuaddon')=='b68e1164f7dd0ff822f20e116e97adc4606926a4204fc25eaa5241c2a966d82d'
  subprocess.run([sys.executable,str(R/'tests/b5q-ufs/test-post-seal.py'),'--kernel',str(kernel),'--out',str(a.out/'post-seal.json')],check=True)
  # Decode only the unchanged original RAM recovery seed for real APFS content
  # verification; never rebuild or read/write the physical persistent Data.
  sys.path.insert(0,str(R/'sources/UniXNU/drivers/DarwinBoot/Test'));from packed_ramdisk import regions
  logical,extents=regions(seed.read_bytes());assert logical==4<<30;image=t/'recovery.img'
  with image.open('wb')as f:
   f.truncate(logical)
   for off,body in extents:f.seek(off);f.write(body)
  subprocess.run([sys.executable,str(R/'scripts/b5q-install/verify-apfs-init-readback.py'),'--image',str(image),'--out',str(a.out/'RAM-recovery-APFS.json')],check=True)
  result=dict(passed=True,ESP=dict(bytes=a.esp.stat().st_size,sha256=sha(a.esp)),changed_FAT_members=diff,changed_archive_members=changed,profiles=profiles,linked_symbols={n:hex(symbols[n])for n in wanted},core_recompiled=False,storage_objects_compiled=2,GPU_UEFI_Data_rebuilt=False,persistent_Data_accessed=False,boot_args_ADT_loader_GPU_seed_trustcache_byte_identical=True,hardware_boot_verified=False)
  (a.out/'images.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
