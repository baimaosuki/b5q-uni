#!/usr/bin/env python3
"""Read back the actual CI ESP/APFS bytes and every New Batch2 invariant."""
import argparse,ast,hashlib,importlib.util,json,plistlib,shutil,struct,subprocess,sys,tempfile,tomllib,uuid
from pathlib import Path
R=Path(__file__).resolve().parents[2];sys.path[:0]=[str(R/'scripts/b5q-install'),str(R/'sources/UniXNU/kits/XnuPrelink')]
import b5q_data_format as fmt
from kc_image import Image

def load(path):
 s=importlib.util.spec_from_file_location(path.stem,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def sha(p):
 with p.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
def run(*cmd):subprocess.run(list(map(str,cmd)),check=True)
def validate_digest_receipt(image,receipt_path,expected_sha256):
 receipt=json.loads(receipt_path.read_text());stat=image.stat()
 assert receipt['path']==str(image.resolve()) and receipt['sha256']==expected_sha256
 assert receipt['full_image_SHA256_calculated'] is True
 assert receipt['stat']=={key:getattr(stat,key)for key in ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')},'Data changed since the full SHA256 pass'
def main():
 p=argparse.ArgumentParser(description=__doc__)
 for n in ('esp','data','manifest','diagnostics','out'):p.add_argument('--'+n,type=Path,required=True)
 p.add_argument('--storage-profile',choices=['tail','userdata'],default='tail')
 p.add_argument('--data-sha256-receipt',type=Path,help='reuse this session full-image hash only while the exact file stat is unchanged')
 a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
 fs=load(R/'scripts/b5q-install/package-usb-dma-esp.py');fs.image_format(a.esp);run('fsck.fat','-n',a.esp)
 run(sys.executable,R/'scripts/b5q-install/verify-esp-log.py','--esp',a.esp,'--out',a.out/'log-allocation.json')
 def unique(name):
  rows=list(a.diagnostics.rglob(name));assert len(rows)==1,(name,rows);return rows[0]
 relink=json.loads(unique('incremental-relink.json').read_text())
 selected_userdata=a.storage_profile=='userdata';expected_objects=2 if selected_userdata else 6
 assert relink['relink_version']==('userdata'if selected_userdata else'batch2') and relink['source_run']==(45108577992 if selected_userdata else 45047962341)
 assert relink['core_translation_units_compiled']==0 and relink['board_translation_units_compiled']==expected_objects and not relink['gpu_recompiled']
 assert relink['expected_core_sha256']==relink['unchanged_core_after_link_sha256']=='88703fdc7eb18011294b5fe634d23b085496732f1e8bd4dd04e47f82dbe6ec2b'
 for name,meta in relink['returned_objects'].items():assert sha(unique(name))==meta['sha256']
 changed_members={}
 for archive,after in relink['output_archive_members'].items():
  before=relink['input_archive_members'][archive]
  changed={n for n in before.keys()|after.keys()if before.get(n)!=after.get(n)};changed_members[archive]=sorted(changed)
  expected={m['archive_member']for m in relink['returned_objects'].values()if archive in m['archives']}
  assert changed==expected,(archive,changed,expected)
 assert relink['input_archives']['build/adreno740/libAdreno740.a']==relink['archive_outputs']['build/adreno740/libAdreno740.a']
 kmeta=json.loads(unique('kernel.json').read_text());assert not kmeta['missing'] and not kmeta['stubbed'] and not kmeta['allow_missing'] and kmeta['mapping_complete']
 assert kmeta['inputs']['native_sha256']==relink['native_output_sha256']
 with tempfile.TemporaryDirectory(prefix='b5q-batch2-readback-')as td:
  t=Path(td);members=fs.members(a.esp,t/'files');boot=t/'files/EFI/UniXNU';assets=boot/'Payloads'
  package=json.loads(unique('batch2-package.json').read_text());assert members==package['members'] and sha(a.esp)==package['esp']['sha256']
  menu=tomllib.loads((boot/'unixnu.toml').read_text());entries={e['id']:e for e in menu['entry']if e['type']=='xnu'}
  assert menu['boot']['default']=='xnu' and set(entries)=={'xnu','ram-fallback'}
  normal,recovery=entries['xnu'],entries['ram-fallback'];assert 'initrd'not in normal and recovery['initrd']=='Payloads/scratch-data.img'
  b=tomllib.loads((R/'UniXNU-b5q/board.toml').read_text());assert normal['args']==' '.join(b['payload']['kernel_args']) and len(normal['args'].encode('ascii'))<=1000
  assert recovery['args']==' '.join('b5q-data-ufs=0'if x.startswith('b5q-data-ufs=')else x for x in normal['args'].split())
  assert ('b5q-data-ufs=2'if selected_userdata else'b5q-data-ufs=1')in normal['args'].split()
  assert 'offline-mobile-graphics-client'not in normal['args']
  profiles={}
  for name,entry in entries.items():
   kernel=boot/entry['path'];adt=fs.adt_nodes(kernel.with_suffix('.macho.adt').read_bytes());chosen=adt['/chosen'][2];maps=adt['/chosen/memory-map'][2]
   assert adt['/chosen/asmb'][2]['lp-sip0']==struct.pack('<Q',2)
   assert chosen['text-fixups']==b''.join(x.encode()+b'\0'for x in b['payload']['text_fixups']) and len(b['payload']['text_fixups'])==2
   assert sum('cluster-type'in props for path,(_,_,props)in adt.items()if path.startswith('/cpus/'))==8
   expected_span=(6 if name=='xnu'else 4)<<30
   assert chosen['darwinboot-memory-size']==struct.pack('<Q',expected_span)
   if name=='xnu':assert 'PackedRAMDisk'not in maps and 'RAMDisk'not in maps and 'ephemeral-storage'not in chosen and len(chosen['darwinboot-memory-excluded'])==128*16 and len(chosen['darwinboot-memory-outside'])==16*16
   else:assert 'PackedRAMDisk'in maps and chosen['ephemeral-storage']==struct.pack('<I',1) and 'darwinboot-memory-outside'not in chosen
   profiles[name]=dict(owned_memory_span_bytes=expected_span,kernel_sha256=sha(kernel),lp_sip0_hex=adt['/chosen/asmb'][2]['lp-sip0'].hex(),RAM_seed_loaded='initrd'in entry,args_bytes=len(entry['args'].encode()),ADT_sha256=sha(kernel.with_suffix('.macho.adt')))
  assert profiles['xnu']['kernel_sha256']==profiles['ram-fallback']['kernel_sha256']
  assert sha(boot/'Drivers/DarwinBoot.efi')=='100080919035179c86c1f4b1eee16e6a8a46166beee95234dc2c842995009cde'
  assert sha(assets/'scratch-data.img')=='d2e32a5f7dd37807a816d857d8b62eba41615c5da9ac335c2322e3c7a35ffc70'
  assert sha(assets/'kernel.macho.gpuaddon')=='b68e1164f7dd0ff822f20e116e97adc4606926a4204fc25eaa5241c2a966d82d'
  kernel=assets/'kernel.macho';raw=kernel.read_bytes();outer=Image(raw);core=Image(raw,outer.entries['com.apple.kernel'][1]);symbols={n:v for v,ns in core.symbols().items()for n in ns}
  for n in ('_b5q_power_start','_b5q_ufs_shutdown_status','_ml_outside_memory_pages','_ml_outside_memory_refused','_sheng_cpu_idle_mach'):assert n in symbols,n
  (a.out/'kernel-symbols.json').write_text(json.dumps({n:hex(v)for n,v in symbols.items()if n in ('_b5q_power_start','_b5q_ufs_shutdown_status','_ml_outside_memory_pages','_ml_outside_memory_refused','_sheng_cpu_idle_mach')or 'B5qDataBlock' in n or 'b5qPlatformPower' in n},indent=2)+'\n')
  for marker in (b'FUA-still-accepted',b'outside adopted=',b'4.5 GiB',b'TOP6..10',b'window=[%llu,%llu]',b'B5qPower:'):assert marker in raw,marker
  assert b'B5qProcTop: window=30s spawns=%llu exits=%llu top='not in raw
  builtin=json.loads((R/'UniXNU-b5q/package/B5qBootPolicy.c').read_text().splitlines()[-1].rstrip(';'))
  assert core.read(symbols['_PE_builtin_boot_args'],len(builtin)+1)==builtin.encode()+b'\0' and 'endpointsecurity'not in builtin
  account=load(R/'scripts/b5q-install/verify-data-account.py');build=account.TOOLS/'build';exe=t/'read-apfs'
  code=(R/'scripts/b5q-install/read-seed-apfs.cpp').read_text().replace('if(!container.Init())return 4;',
   'if(!container.Init())return 4; apfs_superblock_t sb; if(!container.GetVolumeInfo(0,sb))return 12; const uint8_t expected[16]={'+','.join(str(x)for x in uuid.UUID(fmt.DATA_UUID).bytes)+'}; if(memcmp(sb.apfs_vol_uuid,expected,16))return 13;')
  src=t/'read-apfs.cpp';src.write_text('#include <cstring>\n'+code)
  run('c++','-std=c++17','-O2','-I',account.TOOLS,src,build/'libapfs.a','-lz','-lbz2',build/'liblzfse.a',build/'libcrypto.a','-o',exe)
  policy=load(R/'UniXNU-b5q/scripts/update-b5q-launchd-seed.py');paths=list(account.PATHS)+[policy.DIRECTORY+'/disabled.501.plist',policy.DIRECTORY+'/disabled.migrated','private/var/ngpu/bin/b5q-absentd']
  def read_apfs(image,label):
   dest=t/label;stats={}
   for line in subprocess.check_output([str(exe),str(image),str(dest),*paths],text=True).splitlines():
    path,uid,gid,mode,size=line.split('\t');stats[path]=dict(uid=int(uid),gid=int(gid),mode=int(mode,8),bytes=int(size))
   account.verify_files(dest,stats);result={}
   for filename,labels in policy.policies().items():
    path=policy.DIRECTORY+'/'+filename;content=(dest/path).read_bytes();values=plistlib.loads(content);assert content.startswith(b'bplist00')and values==dict.fromkeys(labels,True)
    assert stats[path]['uid']==stats[path]['gid']==0 and stats[path]['mode']==0o100644
    result[path]=dict(stats[path],contents=values,format='bplist00')
   mark=policy.DIRECTORY+'/disabled.migrated';assert stats[mark]==dict(uid=0,gid=0,mode=0o100644,bytes=0)
   absent=dest/'private/var/ngpu/bin/b5q-absentd';assert sha(absent)=='29c52a1b79e53b71022c973a071e1e5dc96830445f742263d68276cee3cb9b72'
   assert stats['private/var/ngpu/bin/b5q-absentd']['mode']==0o100755
   return result,absent.read_bytes()
  install=load(R/'scripts/b5q-install/install-data-ufs.py');manifest=json.loads(a.manifest.read_text())
  if a.data_sha256_receipt:
   validate_digest_receipt(a.data,a.data_sha256_receipt,manifest['sha256'])
   install.local_image_metadata(a.data,manifest)
  else:install.local_image(a.data,manifest)
  expected_blocks=(fmt.USERDATA_LAST-fmt.USERDATA_FIRST+1 if selected_userdata else fmt.ROOT_LAST-fmt.TAIL_FIRST+1)-fmt.ENVELOPE_BLOCKS
  assert manifest['apfs_blocks']==expected_blocks
  persistent,absent=read_apfs(a.data,'persistent')
  sys.path.insert(0,str(R/'sources/UniXNU/drivers/DarwinBoot/Test'));from packed_ramdisk import regions
  logical,extents=regions((assets/'scratch-data.img').read_bytes());assert logical==4<<30
  recovery_image=t/'recovery.raw'
  with recovery_image.open('wb')as f:
   f.truncate(logical)
   for offset,body in extents:f.seek(offset);f.write(body)
  recovered,_=read_apfs(recovery_image,'recovery');assert persistent==recovered
  source=(R/'scripts/b5q-install/verify-mount-runtime.py').read_text();nodes=[n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef)and n.name in ('modules','codesign')];helpers=dict(struct=struct,hashlib=hashlib);exec(compile(ast.Module(body=nodes,type_ignores=[]),source,'exec'),helpers)
  hashes=helpers['codesign'](absent);mods=helpers['modules']((assets/'kernel.macho.trustcache').read_bytes());trusted={mod[i:i+20]for mod in mods for i in range(24,len(mod),24)};assert all(h in trusted for h in hashes)
  with a.data.open('rb')as f:
   for block,digest in manifest['checkpoint_blocks'].items():
    f.seek(int(block)*4096);data=f.read(4096);assert hashlib.sha256(data).hexdigest()==digest and fmt.fletcher(data)
   f.seek(-4096,2);assert hashlib.sha256(f.read(4096)).hexdigest()==manifest['tail_block_sha256']
  run(sys.executable,R/'tests/b5q-ufs/test-post-seal.py','--kernel',kernel,'--out',a.out/'post-seal.json')
  if a.data_sha256_receipt:validate_digest_receipt(a.data,a.data_sha256_receipt,manifest['sha256'])
  (a.out/'disabled-plists-readback.json').write_text(json.dumps(persistent,indent=2)+'\n')
  result=dict(passed=True,CI_core_recompiled=False,board_objects_recompiled=expected_objects,storage_profile=a.storage_profile,board_objects_compiled_this_run=relink.get("board_objects_compiled_this_run",expected_objects),completed_native_source_CI=relink.get("completed_relink_reused_from_CI"),ESP=dict(bytes=a.esp.stat().st_size,sha256=sha(a.esp)),Data=dict(bytes=a.data.stat().st_size,sha256=manifest['sha256'],APFS_volume_uuid=fmt.DATA_UUID,APFS_container_uuid=manifest['container_uuid'],policies_counts={p:len(v['contents'])for p,v in persistent.items()}),profiles=profiles,changed_archive_members=changed_members,loader_sha256=sha(boot/'Drivers/DarwinBoot.efi'),Batch1_absentd_signatures_trusted=[h.hex()for h in hashes],hardware_qualified=False)
  result['Data_SHA256_verification']=dict(full_image_pass=True,reused_receipt=str(a.data_sha256_receipt.resolve())if a.data_sha256_receipt else None,unchanged_stat_checked_before_and_after=bool(a.data_sha256_receipt))
  (a.out/'images.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
