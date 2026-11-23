#!/usr/bin/env python3
"""Grow the verified Batch1 RAM seed into a persistent APFS IMG on macOS."""
import argparse,hashlib,json,plistlib,struct,subprocess,sys,tempfile,uuid
from pathlib import Path
from b5q_data_format import DATA_UUID,ENVELOPE_BLOCKS,SECTOR,ROOT_FIRST,ROOT_LAST,TAIL_FIRST,fletcher
SEED_SHA='d2e32a5f7dd37807a816d857d8b62eba41615c5da9ac335c2322e3c7a35ffc70'
def mounted_volume(device,preferred=None):
 # Native resize leaves the volume unmounted on current macOS. It can also
 # remount elsewhere; use the original device, then verify UUID and path.
 command=['diskutil','info','-plist',device]
 info=plistlib.loads(subprocess.check_output(command))
 if not info.get('Mounted') and preferred is not None:
  subprocess.run(['diskutil','mount','-mountPoint',str(preferred),device],check=True)
  subprocess.run(['diskutil','enableOwnership',device],check=True)
  info=plistlib.loads(subprocess.check_output(command))
 if not info.get('Mounted') or info.get('VolumeUUID','').upper()!=DATA_UUID:
  raise ValueError('resized volume is not mounted with the original Data UUID')
 mount=Path(info.get('MountPoint',''))
 if not mount.is_absolute() or not mount.is_dir():raise ValueError('invalid resized Data mountpoint')
 return mount
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--seed',type=Path,required=True);p.add_argument('--codec',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
 p.add_argument('--blocks',type=int,default=ROOT_LAST-TAIL_FIRST+1-ENVELOPE_BLOCKS);a=p.parse_args()
 if sys.platform!='darwin':raise SystemExit('APFS growth requires native macOS diskutil; no Linux substitute')
 if not (4<<30)//4096<=a.blocks<(1<<32):raise SystemExit('APFS size out of bounds')
 body=a.seed.read_bytes();assert hashlib.sha256(body).hexdigest()==SEED_SHA,'Batch1-final seed required; never use old v32/v33 policy'
 sys.path.insert(0,str(a.codec/'Test'));from packed_ramdisk import regions
 logical,extents=regions(body);assert logical==4<<30
 a.out.parent.mkdir(parents=True,exist_ok=True)
 if a.out.exists():raise SystemExit('refusing to overwrite an existing persistent Data image')
 with a.out.open('xb') as f:
  f.truncate(a.blocks*4096)
  for offset,data in extents:f.seek(offset);f.write(data)
 with tempfile.TemporaryDirectory(prefix='b5q-data-grow-') as td:
  mount=Path(td)/'mount';mount.mkdir();attached=plistlib.loads(subprocess.check_output(['hdiutil','attach','-imagekey','diskimage-class=CRawDiskImage','-nobrowse','-owners','on','-mountpoint',str(mount),'-plist',str(a.out.resolve())]))
  device=attached['system-entities'][0]['dev-entry']
  try:
   info=plistlib.loads(subprocess.check_output(['diskutil','info','-plist',str(mount)]));assert info['VolumeUUID'].upper()==DATA_UUID
   container=info['APFSContainerReference']
   subprocess.run(['diskutil','apfs','resizeContainer',container,'0'],check=True)
   mount=mounted_volume(info['DeviceIdentifier'],mount)
   directory=mount/'private/var/db/com.apple.xpc.launchd'
   policy={}
   for name,expected in [('disabled.plist',59),('disabled.501.plist',26)]:
    data=(directory/name).read_bytes();values=plistlib.loads(data);st=(directory/name).stat()
    assert data.startswith(b'bplist00') and len(values)==expected and all(x is True for x in values.values())
    assert st.st_uid==st.st_gid==0 and st.st_mode&0o7777==0o644
    policy[name]=values
   standin=(mount/'private/var/ngpu/bin/b5q-absentd').read_bytes()
   assert hashlib.sha256(standin).hexdigest()=='29c52a1b79e53b71022c973a071e1e5dc96830445f742263d68276cee3cb9b72'
   assert (directory/'disabled.migrated').stat().st_size==0
  finally:subprocess.run(['hdiutil','detach',device],check=True)
 with a.out.open('rb') as f:
  sb=f.read(4096);assert fletcher(sb) and sb[32:36]==b'NXSB' and struct.unpack_from('<IQ',sb,36)==(4096,a.blocks)
  container=str(uuid.UUID(bytes=sb[72:88]));checkpoints={0:hashlib.sha256(sb).hexdigest()}
  desc_count=struct.unpack_from('<I',sb,104)[0];desc_base=struct.unpack_from('<Q',sb,112)[0]
  assert desc_count<65536 and desc_base<a.blocks and desc_count<a.blocks-desc_base
  for b in range(desc_base,desc_base+desc_count):
   f.seek(b*4096);data=f.read(4096)
   if data[32:36]==b'NXSB':assert fletcher(data);checkpoints[b]=hashlib.sha256(data).hexdigest()
  f.seek(-4096,2);tail=hashlib.sha256(f.read(4096)).hexdigest()
  f.seek(0);digest=hashlib.file_digest(f,'sha256').hexdigest()
 result=dict(bytes=a.out.stat().st_size,sha256=digest,apfs_blocks=a.blocks,container_uuid=container,volume_uuid=DATA_UUID,seed_sha256=SEED_SHA,checkpoint_blocks=checkpoints,tail_block_sha256=tail,policies=policy,source='grown existing Batch1-final APFS volume, account/UUID/absentd preserved; not regenerated',hardware_tested=False)
 a.out.with_suffix('.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items()if k!='policies'},indent=2))
if __name__=='__main__':main()
