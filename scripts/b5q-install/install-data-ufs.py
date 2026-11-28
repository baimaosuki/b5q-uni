#!/usr/bin/env python3
"""Initialize only a GPT-validated b5q Data tail/window, never repartition."""
import argparse,hashlib,json,re,struct,subprocess,sys
from pathlib import Path
from b5q_data_format import *

def local_image(image,manifest):
 if image.stat().st_size!=manifest['bytes'] or manifest['bytes']!=manifest['apfs_blocks']*4096:raise ValueError('image size')
 with image.open('rb') as f:
  if hashlib.file_digest(f,'sha256').hexdigest()!=manifest['sha256']:raise ValueError('image SHA256')
  f.seek(0);sb=f.read(4096)
  if not apfs_superblock(sb,manifest['apfs_blocks'],manifest['container_uuid']):raise ValueError('APFS NXSB/geometry/UUID')
 if manifest['volume_uuid']!=DATA_UUID or manifest['seed_sha256']!='d2e32a5f7dd37807a816d857d8b62eba41615c5da9ac335c2322e3c7a35ffc70':raise ValueError('Batch1 seed identity')
 if {k:len(v) for k,v in manifest['policies'].items()}!={'disabled.plist':59,'disabled.501.plist':26}:raise ValueError('Batch1 policy')

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--image',type=Path,required=True);p.add_argument('--manifest',type=Path);p.add_argument('--partition',choices=['macosroot-tail','macosdata','userdata'],default='macosroot-tail');p.add_argument('--replace-android-data',action='store_true',help='explicitly permit replacing old Android contents of the exact userdata partition; never overwrite initialized macOS Data');p.add_argument('--serial');p.add_argument('--apply',action='store_true',help='explicitly write a first-install Data window; existing initialized Data is always refused');a=p.parse_args()
 m=json.loads((a.manifest or a.image.with_suffix('.json')).read_text());local_image(a.image,m)
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
 diskid,parts,root=parse_gpt(header,read(disk,entry_lba,(count*stride+4095)//4096),capacity)
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
 # Both writes use fixed allowlisted aliases and prevalidated relative offsets.
 with a.image.open('rb') as f:
  subprocess.run(adb+['shell','-T',f'dd of={target} bs=4096 seek={start+ENVELOPE_BLOCKS} count={m["apfs_blocks"]} conv=fsync'],stdin=f,check=True)
 actual=shell(f'set -o pipefail; dd if={target} bs=4096 skip={start+ENVELOPE_BLOCKS} count={m["apfs_blocks"]} status=none | sha256sum').split()[0]
 if actual!=m['sha256']:raise ValueError('full Data readback SHA256 mismatch; envelope not committed')
 for block,expected in m['checkpoint_blocks'].items():
  data=read(target,start+ENVELOPE_BLOCKS+int(block),1)
  if hashlib.sha256(data).hexdigest()!=expected:raise ValueError('Data checkpoint readback failed; configuration not committed')
 if hashlib.sha256(read(target,start+ENVELOPE_BLOCKS+m['apfs_blocks']-1,1)).hexdigest()!=m['tail_block_sha256']:raise ValueError('Data last-block readback failed')
 subprocess.run(adb+['shell','-T',f'dd of={target} bs=4096 seek={start} count=1 conv=fsync'],input=config,check=True)
 validate_envelope(read(target,start,1),identity)
 print('PASS Data initialized; GPT/root/guard untouched; subsequent boots mount persistent APFS directly')
if __name__=='__main__':main()
