#!/usr/bin/env python3
"""Plan the minimal b5q macOS-only conversion: reuse userdata, never change GPT."""
import argparse,hashlib,json,struct
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
SECTOR=4096
EXPECTED={'userdata':(36,3406336,47595510),'macosroot':(37,49692663,62275574),'esp':(29,3162880,3367679),'boot':(21,152448,177023)}
def digest(path):
 with path.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
def plan(source,header,root_bytes):
 if source.get('lba_bytes')!=SECTOR:raise ValueError('requires 4Kn listing')
 parts=source['partitions'];by={p['name']:p for p in parts}
 if len(by)!=len(parts)or len({p['number']for p in parts})!=len(parts):raise ValueError('duplicate partition name/number')
 for name,expected in EXPECTED.items():
  p=by.get(name)
  if p is None or (p['number'],p['first_lba'],p['last_lba'])!=expected:raise ValueError('source geometry differs: '+name)
 ordered=sorted(parts,key=lambda p:p['first_lba'])
 for i,p in enumerate(ordered):
  if p['size_bytes']!=(p['last_lba']-p['first_lba']+1)*SECTOR or p['byte_offset']!=p['first_lba']*SECTOR:raise ValueError('source size mismatch')
  if i and ordered[i-1]['last_lba']>=p['first_lba']:raise ValueError('source overlap')
 if len(header)!=4096 or header[:8]!=b'SHNGROOT' or struct.unpack_from('<II',header,8)!=(2,6)or hashlib.sha256(header[:4064]).digest()!=header[4064:]:raise ValueError('SHNGROOT v2 header integrity')
 if struct.unpack_from('<Q',header,16)[0]!=root_bytes or root_bytes!=17603493888:raise ValueError('root source size')
 data=by['userdata'];first,last=data['first_lba'],data['last_lba'];apfs=first+256
 return dict(schema_version=1,state='minimal-layout-selected; images not yet built',sector_bytes=SECTOR,source=dict(kind=source.get('source','unknown'),fresh_device_read=False,live_disk_and_partition_GUIDs='unknown until installer verifies actual GPT'),
  design='Keep every GPT entry and name byte-identical; reuse only original userdata contents for macOS Data. No system move, no GPT edits.',
  partitions=dict(boot=by['boot'],esp=by['esp'],macosroot=by['macosroot'],userdata=data),GPT_entries_unchanged=len(parts),GPT_write_count=0,
  root=dict(existing_image_bytes=root_bytes,existing_header_SHA256=hashlib.sha256(header).hexdigest(),partition_bytes=by['macosroot']['size_bytes'],reflash_required=False,read_only=True),
  Data=dict(physical_partition='userdata',partition_bytes=data['size_bytes'],partition_GiB=data['size_bytes']/2**30,envelope_first_lba=first,envelope_blocks=256,APFS_first_lba=apfs,APFS_last_lba=last,APFS_blocks=last-apfs+1,APFS_bytes=(last-apfs+1)*SECTOR,APFS_GiB=(last-apfs+1)*SECTOR/2**30,kernel_arg='b5q-data-ufs=2',format='B5QDATA1 1MiB envelope + APFS exposed by B5qDataBlock; GPT name userdata retained'),
  unused=dict(existing_gap_bytes=(by['macosroot']['first_lba']-last-1)*SECTOR,old_root_tail_remains_unmodified=True,reason='Using these areas would add GPT changes/move existing system; user explicitly requested least work'),
  existing_Android_data='Discarded during explicit first-install conversion; no preservation requested',
  build=dict(board_objects=['B5qRamStorage.cpp','B5qUfs/B5qUfs.cpp'],core_GPU_Mesa_UEFI_rebuild=False,existing_root_reflash=False,ESP_update=True,Data='grow verified Batch1 seed to exact original userdata capacity minus1MiB; preserve account/SIP2/59+26policies'),
  install=dict(connected_device_access=False,flash_performed=False,scope='User-run TWRP tool validates b5q+LUN0+4Kn+GPTCRC/name/UUID/exactbounds+root hash; requires userdata explicitly unmounted and explicit replacement flag; existing APFS/macOS envelope refused',required_images=['esp.img','data-ufs.img']))
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,default=ROOT/'artifacts/b5q-full-27.3-26C5035r/metadata/gpt-user.json');p.add_argument('--root-image',type=Path,default=ROOT/'artifacts/b5q-full-27.3-26C5035r/delivery/macosroot.img');p.add_argument('--out',type=Path,default=ROOT/'UniXNU-b5q/reports/macos-only-layout.json');a=p.parse_args()
 with a.root_image.open('rb')as f:header=f.read(4096)
 x=plan(json.loads(a.source.read_text()),header,a.root_image.stat().st_size);x['input_hashes']=dict(source_GPT_listing_SHA256=digest(a.source),planner_SHA256=digest(Path(__file__)))
 a.out.write_text(json.dumps(x,indent=2)+'\n');print(json.dumps(x,indent=2))
if __name__=='__main__':main()
