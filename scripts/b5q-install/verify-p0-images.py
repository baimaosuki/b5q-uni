#!/usr/bin/env python3
"""Read actual full-build P0 ESP/UEFI bytes and preserve desktop invariants."""
import argparse,ast,hashlib,importlib.util,json,struct,subprocess,sys,tempfile,tomllib
from pathlib import Path
R=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(R/'sources/UniXNU/kits/XnuPrelink'))
from kc_image import Image
def load(path):
 spec=importlib.util.spec_from_file_location(path.stem,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def sha(p):
 with p.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
def run(*cmd):subprocess.run(list(map(str,cmd)),check=True)
def main():
 p=argparse.ArgumentParser(description=__doc__)
 for key in ['esp','ci','fd','out']:p.add_argument('--'+key,type=Path,required=True)
 a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
 fs=load(R/'scripts/b5q-install/package-usb-dma-esp.py');fs.image_format(a.esp)
 run('fsck.fat','-n',a.esp)
 run(sys.executable,R/'scripts/b5q-install/verify-esp-log.py','--esp',a.esp,'--out',a.out/'log-allocation.json')
 run(sys.executable,R/'scripts/b5q-install/check-usb-dma-fv.py','--fd',a.fd,'--out',a.out/'firmware-FV.json')
 meta,=a.ci.rglob('kernel.json');kmeta=json.loads(meta.read_text())
 assert kmeta['mapping_complete'] and not kmeta['missing'] and not kmeta['stubbed'] and not kmeta['allow_missing']
 package,=a.ci.rglob('batch2-package.json');expected=json.loads(package.read_text())
 with tempfile.TemporaryDirectory(prefix='b5q-p0-readback-')as td:
  t=Path(td);members=fs.members(a.esp,t/'files')
  assert members==expected['members'] and sha(a.esp)==expected['esp']['sha256']
  boot=t/'files/EFI/UniXNU';assets=boot/'Payloads';board=tomllib.loads((R/'UniXNU-b5q/board.toml').read_text())
  menu=tomllib.loads((boot/'unixnu.toml').read_text());entries={e['id']:e for e in menu['entry']if e['type']=='xnu'}
  assert menu['boot']['default']=='xnu' and set(entries)=={'xnu','ram-fallback'}
  assert entries['xnu']['args']==' '.join(board['payload']['kernel_args']) and len(entries['xnu']['args'].encode())<=1000
  assert 'b5q-data-ufs=2' in entries['xnu']['args'].split() and 'initrd' not in entries['xnu']
  assert 'offline-mobile-graphics-client' not in entries['xnu']['args']
  assert 'b5q-data-ufs=0' in entries['ram-fallback']['args'].split()
  assert entries['ram-fallback']['initrd']=='Payloads/scratch-data.img'
  profiles={}
  for name,entry in entries.items():
   kernel=boot/entry['path'];nodes=fs.adt_nodes(kernel.with_suffix('.macho.adt').read_bytes());chosen=nodes['/chosen'][2]
   assert nodes['/chosen/asmb'][2]['lp-sip0']==struct.pack('<Q',2)
   assert chosen['darwinboot-memory-size']==struct.pack('<Q',(6 if name=='xnu' else 4)<<30)
   assert chosen['text-fixups']==b''.join(v.encode()+b'\0'for v in board['payload']['text_fixups']) and len(board['payload']['text_fixups'])==2
   assert sum('cluster-type'in v[2]for k,v in nodes.items()if k.startswith('/cpus/'))==8
   maps=nodes['/chosen/memory-map'][2]
   if name=='xnu':
    assert 'RAMDisk'not in maps and 'PackedRAMDisk'not in maps
    assert len(chosen['darwinboot-memory-excluded'])==128*16 and len(chosen['darwinboot-memory-outside'])==16*16
   else:assert 'PackedRAMDisk'in maps and 'darwinboot-memory-outside'not in chosen
   profiles[name]=dict(kernel_sha256=sha(kernel),args_bytes=len(entry['args'].encode()),lp_sip0_hex=chosen.get('lp-sip0',nodes['/chosen/asmb'][2]['lp-sip0']).hex(),RAM_seed_loaded='initrd'in entry)
  assert profiles['xnu']['kernel_sha256']==profiles['ram-fallback']['kernel_sha256']
  kernel=assets/'kernel.macho';raw=kernel.read_bytes();outer=Image(raw);core=Image(raw,outer.entries['com.apple.kernel'][1]);symbols={n:v for v,names in core.symbols().items()for n in names}
  required=['_native_ram_block_provider_seed','_native_ram_block_volume_seed','_native_ram_block_volume_device','_b5q_power_start','_sheng_cpu_idle_mach','_ml_outside_memory_pages','_ml_outside_memory_refused','_native_touch_recovered','_native_touch_set_sink']
  assert all(n in symbols for n in required),[n for n in required if n not in symbols]
  assert not any('B5qTouchPointer'in n for n in symbols)
  for marker in [b'B5qTouch: mode=%02x',b'c2=%u release_all=%u hid=%u',b'stage=release-all',b'stage=report-recovery',b'FUA-still-accepted',b'outside adopted=',b'4.5 GiB',b'TOP6..10',b'B5qPower:',b'persistent Data media/UUID/BSD readiness timeout or duplicate UUID']:
   assert marker in raw,marker
  for name,digest in [('scratch-data.img','d2e32a5f7dd37807a816d857d8b62eba41615c5da9ac335c2322e3c7a35ffc70'),('kernel.macho.gpuaddon','b68e1164f7dd0ff822f20e116e97adc4606926a4204fc25eaa5241c2a966d82d')]:assert sha(assets/name)==digest,name
  assert sha(boot/'Drivers/DarwinBoot.efi')=='100080919035179c86c1f4b1eee16e6a8a46166beee95234dc2c842995009cde'
  builtin=json.loads((R/'UniXNU-b5q/package/B5qBootPolicy.c').read_text().splitlines()[-1].rstrip(';'))
  assert core.read(symbols['_PE_builtin_boot_args'],len(builtin)+1)==builtin.encode()+b'\0' and 'endpointsecurity'not in builtin
  run(sys.executable,R/'tests/b5q-ufs/test-post-seal.py','--kernel',kernel,'--out',a.out/'POST.json')
  sys.path.insert(0,str(R/'sources/UniXNU/drivers/DarwinBoot/Test'));from packed_ramdisk import regions
  size,extents=regions((assets/'scratch-data.img').read_bytes());assert size==4<<30
  recovery=t/'recovery.img'
  with recovery.open('wb')as stream:
   stream.truncate(size)
   for offset,body in extents:stream.seek(offset);stream.write(body)
  run(sys.executable,R/'scripts/b5q-install/verify-apfs-init-readback.py','--image',recovery,'--trust-cache',assets/'kernel.macho.trustcache','--out',a.out/'APFS.json')
  result=dict(passed=True,stage='P0',ESP=dict(bytes=a.esp.stat().st_size,sha256=sha(a.esp)),FD=dict(bytes=a.fd.stat().st_size,sha256=sha(a.fd)),profiles=profiles,required_symbols={n:hex(symbols[n])for n in required},FAT_members=len(members),all_real_link_inputs_resolved=True,Data_GPU_loader_unchanged=True,hardware_qualification='HOST_VERIFIED_PENDING_HARDWARE',physical_Data_accessed=False)
  (a.out/'images.json').write_text(json.dumps(result,indent=2)+'\n')
  print(json.dumps(result,indent=2))
if __name__=='__main__':main()
