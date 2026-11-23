#!/usr/bin/env python3
"""Initialize only a GPT-validated b5q Data tail/window, never repartition."""
import argparse,gzip,hashlib,json,re,shutil,struct,subprocess,sys,zlib
from pathlib import Path
from b5q_data_format import *

def local_image_metadata(image,manifest):
 if image.stat().st_size!=manifest['bytes'] or manifest['bytes']!=manifest['apfs_blocks']*4096:raise ValueError('image size')
 with image.open('rb') as f:
  sb=f.read(4096)
  if not apfs_superblock(sb,manifest['apfs_blocks'],manifest['container_uuid']):raise ValueError('APFS NXSB/geometry/UUID')
 if manifest['volume_uuid']!=DATA_UUID or manifest['seed_sha256']!='d2e32a5f7dd37807a816d857d8b62eba41615c5da9ac335c2322e3c7a35ffc70':raise ValueError('Batch1 seed identity')
 if {k:len(v) for k,v in manifest['policies'].items()}!={'disabled.plist':59,'disabled.501.plist':26}:raise ValueError('Batch1 policy')

def local_image(image,manifest):
 local_image_metadata(image,manifest)
 with image.open('rb') as f:
  if hashlib.file_digest(f,'sha256').hexdigest()!=manifest['sha256']:raise ValueError('image SHA256')

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--image',type=Path,required=True);p.add_argument('--manifest',type=Path);p.add_argument('--partition',choices=['macosroot-tail','macosdata','userdata'],default='macosroot-tail');p.add_argument('--replace-android-data',action='store_true',help='explicitly permit replacing old Android contents of the exact userdata partition; never overwrite initialized macOS Data');p.add_argument('--serial');p.add_argument('--apply',action='store_true',help='explicitly write a first-install Data window; existing initialized Data is always refused');p.add_argument('--sparse-init',action='store_true',help='userdata only: copy allocated APFS blocks and metadata, never the full blank device');p.add_argument('--source-receipt',type=Path);p.add_argument('--readback-image',type=Path);a=p.parse_args()
 m=json.loads((a.manifest or a.image.with_suffix('.json')).read_text())
 sparse_plan=None
 if a.sparse_init:
  if a.partition!='userdata' or not a.replace_android_data or not a.source_receipt or not a.readback_image:raise ValueError('sparse initialization requires explicit userdata replacement, validated source receipt and readback image')
  from apfs_sparse_init import allocation_plan,validate_source_receipt
  validate_source_receipt(a.image,m,a.source_receipt);local_image_metadata(a.image,m);sparse_plan=allocation_plan(a.image)
  print(f"Sparse initialization: {sparse_plan['write_bytes']} APFS bytes in {len(sparse_plan['segments'])} segments; no full-device zero write",flush=True)
 else:local_image(a.image,m)
 adb=['adb']+(['-s',a.serial]if a.serial else [])
 def shell(command):return subprocess.check_output(adb+['shell','-T',command],text=True).strip()
 if shell('id -u')!='0' or not shell('getprop ro.twrp.version'):raise SystemExit('requires root TWRP')
 dev=shell('getprop ro.product.device').lower();model=shell('getprop ro.product.model').upper()
 if not (dev.startswith('b5q') or model.startswith('SM-F731')):raise SystemExit('not a b5q')
 rootpath=shell('readlink -f /dev/block/by-name/macosroot')
 if not re.fullmatch(r'/dev/block/sda[0-9]+',rootpath):raise SystemExit('macosroot is not on expected normal UFS disk')
 disk='/dev/block/sda';part=Path(rootpath).name
 hctl=Path(shell('readlink -f /sys/class/block/sda/device')).name
 if not re.fullmatch(r'\d+:\d+:\d+:0',hctl):raise SystemExit('LUN0 not proven by SCSI H:C:T:L')
 if shell('blockdev --getss '+disk)!='4096':raise SystemExit('requires 4Kn')
 capacity=int(shell('blockdev --getsize64 '+disk))//4096
 def read(path,block,count):
  if path not in (disk,'/dev/block/by-name/macosroot','/dev/block/by-name/macosdata','/dev/block/by-name/userdata') or block<0 or count<=0:raise ValueError('read scope')
  data=subprocess.check_output(adb+['exec-out',f'dd if={path} bs=4096 skip={block} count={count} status=none'])
  if len(data)!=count*4096:raise ValueError('short device read')
  return data
 header=read(disk,1,1);entry_lba,count,stride,_=struct.unpack_from('<QIII',header,72)
 if not 2<=entry_lba<=64 or not 0<count<=8192 or not 128<=stride<=1024 or count*stride>1<<20:raise ValueError('GPT metadata read limits')
 table_blocks=(count*stride+4095)//4096;table=read(disk,entry_lba,table_blocks)
 diskid,parts,root=parse_gpt(header,table,capacity)
 backup=read(disk,capacity-1,1)if a.sparse_init else None
 if backup:
  backup_lba=struct.unpack_from('<Q',backup,72)[0]
  usable_last=struct.unpack_from('<Q',header,48)[0]
  if not max(usable_last+1,capacity-65)<=backup_lba<=capacity-1-table_blocks:raise ValueError('backup GPT array bounds')
  if backup[:8]!=b'EFI PART' or struct.unpack_from('<QQ',backup,24)!=(capacity-1,1) or backup[40:72]!=header[40:72] or backup[80:92]!=header[80:92]:raise ValueError('backup GPT identity mismatch')
  length=struct.unpack_from('<I',backup,12)[0];copy=bytearray(backup[:length]);copy[16:20]=bytes(4)
  if not 92<=length<=4096 or zlib.crc32(copy)!=struct.unpack_from('<I',backup,16)[0]:raise ValueError('backup GPT header CRC')
  backup_table=read(disk,backup_lba,table_blocks)
  if backup_table[:count*stride]!=table[:count*stride]:raise ValueError('backup GPT array differs')
 if int(shell('cat /sys/class/block/'+part+'/start'))*512!=ROOT_FIRST*4096 or int(shell('cat /sys/class/block/'+part+'/size'))*512!=(ROOT_LAST-ROOT_FIRST+1)*4096:raise ValueError('root sysfs geometry mismatch')
 root_header=read('/dev/block/by-name/macosroot',0,1)
 if hashlib.sha256(root_header).hexdigest()!=ROOT_HEADER_SHA or struct.unpack_from('<Q',root_header,16)[0]!=ROOT_TOTAL:raise ValueError('installed readonly root header mismatch')
 identity=choose(diskid,parts,root,a.partition)
 if identity['last']-identity['first']+1-ENVELOPE_BLOCKS!=m['apfs_blocks']:raise ValueError('Data image does not fit exact selected window; rebuild image for selected Data geometry')
 target='/dev/block/by-name/'+('macosroot'if a.partition=='macosroot-tail'else a.partition)
 start=identity['first']-(ROOT_FIRST if a.partition=='macosroot-tail'else identity['first'])
 if a.partition!='macosroot-tail':
  real=shell('readlink -f '+target)
  if not re.fullmatch(r'/dev/block/sda[0-9]+',real):raise ValueError('Data target is on a different disk')
  name=Path(real).name
  if int(shell('cat /sys/class/block/'+name+'/start'))*512!=identity['first']*4096 or int(shell('cat /sys/class/block/'+name+'/size'))*512!=(identity['last']-identity['first']+1)*4096:raise ValueError('Data target sysfs geometry')
 if a.partition=='userdata':
  if any(line.split()[1]=='/data' or line.split()[1].startswith('/data/') for line in shell('cat /proc/mounts').splitlines() if len(line.split())>=2):raise ValueError('Android /data is mounted; unmount it before conversion')
 existing=read(target,start,1);first_apfs=read(target,start+ENVELOPE_BLOCKS,1)
 if existing[:8]==b'B5QDATA1' or existing[32:36]==b'NXSB' or first_apfs[32:36]==b'NXSB':raise ValueError('existing macOS Data found; refusing reinitialization')
 if a.partition=='userdata':
  if not a.replace_android_data:raise ValueError('userdata conversion requires --replace-android-data')
 elif any(existing) or any(first_apfs):raise ValueError('Data area is nonzero; refusing overwrite of existing contents')
 config=envelope(identity,m['container_uuid']);validate_envelope(config,identity)
 print(f"VERIFIED LUN0 Data envelope={identity['first']} APFS={identity['first']+256}..{identity['last']} blocks={m['apfs_blocks']} readonly-root-end={ROOT_FIRST+ROOT_TOTAL//4096-1}")
 if not a.apply:print('CHECK ONLY; no writes performed');return
 mounted=shell('cat /proc/mounts').splitlines();swaps=shell('cat /proc/swaps').splitlines()[1:];target_real=shell('readlink -f '+target)
 if any(line.split() and line.split()[0] in (target,target_real) for line in mounted+swaps):raise ValueError('target partition is mounted')
 if sparse_plan:
  validate_source_receipt(a.image,m,a.source_receipt)
  if a.readback_image.resolve()==a.image.resolve() or a.readback_image.exists():raise ValueError('readback must be a new separate scratch file')
  a.readback_image.parent.mkdir(parents=True,exist_ok=True)
  # UNMAP invalidates old Android contents but is never assumed to read zero.
  # Every APFS-allocated block, including logical zero data, is copied below.
  shell(f'toybox blkdiscard -o 0 -l {(identity["last"]-identity["first"]+1)*4096} {target}')
  subprocess.run(adb+['shell','-T',f'dd of={target} bs=4096 seek=0 conv=fsync'],input=bytes(ENVELOPE_BLOCKS*4096),check=True)
  with a.image.open('rb')as source,a.readback_image.open('xb')as mirror:
   mirror.truncate(m['bytes'])
   for index,segment in enumerate(sparse_plan['segments'],1):
    block,blocks=segment['block'],segment['blocks'];source.seek(block*4096);body=source.read(blocks*4096)
    if len(body)!=blocks*4096 or hashlib.sha256(body).hexdigest()!=segment['sha256']:raise ValueError('source segment changed')
    command=f'set -o pipefail; gzip -dc | dd of={target} bs=4096 seek={ENVELOPE_BLOCKS+block} conv=fsync'
    subprocess.run(adb+['shell','-T',command],input=gzip.compress(body,compresslevel=1),check=True)
    returned=read(target,ENVELOPE_BLOCKS+block,blocks)
    if hashlib.sha256(returned).hexdigest()!=segment['sha256']:raise ValueError('sparse segment readback failed; envelope not committed')
    mirror.seek(block*4096);mirror.write(returned)
    print(f'PASS sparse segment {index}/{len(sparse_plan["segments"])} APFS block={block} bytes={len(body)}',flush=True)
  subprocess.run([sys.executable,str(Path(__file__).with_name('verify-apfs-init-readback.py')),'--image',str(a.readback_image),'--out',str(a.readback_image.with_suffix('.verified.json'))],check=True)
 # Both writes use fixed allowlisted aliases and prevalidated relative offsets.
 # Read the verified image through EOF: dd count counts partial pipe reads and
 # can otherwise stop early on ADB packets. The exact image size is checked
 # above; the selected partition ends exactly at the APFS window boundary.
 write_command=f'dd of={target} bs=4096 seek={start+ENVELOPE_BLOCKS} conv=fsync'
 compressed=not sparse_plan and a.partition=='userdata' and shutil.which('gzip') and shell('command -v gzip || true')
 with a.image.open('rb') as f:
  if compressed:
   # Compress only the transfer stream; keep the deliverable a normal sparse
   # APFS IMG. Large zero-filled free space never crosses ADB uncompressed.
   print('Transferring Data as a gzip stream; no temporary archive')
   encoder=subprocess.Popen(['gzip','-1','-c'],stdin=f,stdout=subprocess.PIPE)
   try:
    subprocess.run(adb+['shell','-T','set -o pipefail; gzip -dc | '+write_command],stdin=encoder.stdout,check=True)
   finally:
    encoder.stdout.close();encoded_status=encoder.wait()
   if encoded_status:raise ValueError('Data compression failed; envelope not committed')
  elif not sparse_plan:subprocess.run(adb+['shell','-T',write_command],stdin=f,check=True)
 if not sparse_plan:
  actual=shell(f'set -o pipefail; dd if={target} bs=4096 skip={start+ENVELOPE_BLOCKS} count={m["apfs_blocks"]} status=none | sha256sum').split()[0]
  if actual!=m['sha256']:raise ValueError('full Data readback SHA256 mismatch; envelope not committed')
 for block,expected in m['checkpoint_blocks'].items():
  data=read(target,start+ENVELOPE_BLOCKS+int(block),1)
  if hashlib.sha256(data).hexdigest()!=expected:raise ValueError('Data checkpoint readback failed; configuration not committed')
 if hashlib.sha256(read(target,start+ENVELOPE_BLOCKS+m['apfs_blocks']-1,1)).hexdigest()!=m['tail_block_sha256']:raise ValueError('Data last-block readback failed')
 subprocess.run(adb+['shell','-T',f'dd of={target} bs=4096 seek={start} conv=fsync'],input=config,check=True)
 validate_envelope(read(target,start,1),identity)
 if sparse_plan:
  if read(disk,1,1)!=header or read(disk,entry_lba,table_blocks)!=table or read(disk,capacity-1,1)!=backup or read(disk,backup_lba,table_blocks)!=backup_table:raise ValueError('GPT metadata changed')
  result=dict(passed=True,partition='userdata',envelope_first_lba=identity['first'],APFS_first_lba=identity['first']+256,APFS_last_lba=identity['last'],APFS_capacity_bytes=m['bytes'],APFS_bytes_written=sparse_plan['write_bytes'],envelope_area_bytes_written=ENVELOPE_BLOCKS*4096+4096,all_segments_readback_SHA256_verified=True,APFS_files_owners_policies_verified=True,GPT_primary_and_backup_unchanged=True,full_168GiB_write_performed=False,UNMAP_zero_reads_assumed=False,sparse_plan=sparse_plan)
  a.readback_image.with_suffix('.install.json').write_text(json.dumps(result,indent=2)+'\n')
 print('PASS Data initialized; GPT/root/guard untouched; subsequent boots mount persistent APFS directly')
if __name__=='__main__':main()
