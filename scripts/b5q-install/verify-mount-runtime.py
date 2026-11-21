#!/usr/bin/env python3
"""Locally verify the mount repair against actual ESP bytes, signatures and seed."""
import argparse,hashlib,importlib.util,json,plistlib,struct,subprocess,sys,tempfile,uuid,zlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'sources/UniXNU/drivers/DarwinBoot/Test'))
import packed_ramdisk
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--package',type=Path,required=True);a=p.parse_args();package=a.package.resolve();manifest=json.loads((package/'package.manifest.json').read_text())

def modules(data):
 count=struct.unpack_from('<I',data)[0];starts=list(struct.unpack_from(f'<{count}I',data,4))+[len(data)];result=[]
 for lo,hi in zip(starts,starts[1:]):
  m=data[lo:hi];version,_,entries=struct.unpack_from('<I16sI',m);assert version==2 and len(m)==24+24*entries;result.append(m)
 return result

def codesign(body):
 assert struct.unpack_from('<I',body)[0]==0xfeedfacf
 at=32;signature=None
 for _ in range(struct.unpack_from('<I',body,16)[0]):
  cmd,n=struct.unpack_from('<II',body,at)
  if cmd==0x1d:signature=struct.unpack_from('<II',body,at+8)
  at+=n
 assert signature;lo,n=signature;sig=body[lo:lo+n];magic,length,count=struct.unpack_from('>III',sig);assert magic==0xfade0cc0 and length<=len(sig)
 hashes=[]
 for i in range(count):
  _,off=struct.unpack_from('>II',sig,12+8*i);magic,size=struct.unpack_from('>II',sig,off)
  if magic!=0xfade0c02:continue
  cd=sig[off:off+size];hash_at=struct.unpack_from('>I',cd,16)[0];slots,limit=struct.unpack_from('>II',cd,28)
  hash_size,kind,page=cd[36],cd[37],cd[39];assert kind==2 and hash_size==32 and page==12
  assert slots==(limit+4095)//4096 and limit<=lo
  for index in range(slots):assert hashlib.sha256(body[index*4096:min(limit,(index+1)*4096)]).digest()==cd[hash_at+index*32:hash_at+(index+1)*32]
  hashes.append(hashlib.sha256(cd).digest()[:20])
 assert hashes;return hashes

with tempfile.TemporaryDirectory(prefix='b5q-mount-verify-') as temp:
 temp=Path(temp);files={}
 for name in ['kernel.macho','kernel.macho.adt','kernel.macho.trustcache','kernel.macho.gpuaddon','scratch-data.img']:
  target=temp/name;subprocess.run(['mcopy','-i',str(package/'esp.img'),'::/EFI/UniXNU/Payloads/'+name,str(target)],check=True);files[name]=target
 assert hashlib.sha256(files['kernel.macho'].read_bytes()).hexdigest()==manifest['deploy_kernel_sha256']
 logical,extents=packed_ramdisk.regions(files['scratch-data.img'].read_bytes());assert logical==manifest.get('data_logical_bytes',2*2**30)
 identities=set();superblocks=0;policy=None
 for offset,chunk in extents:
  for at in range(0,len(chunk),4096):
   b=bytes(chunk[at:at+4096])
   if b[32:36] in (b'NXSB',b'APSB'):
    words=struct.unpack('<1022I',b[8:]);mod=0xffffffff;s1=s2=0
    for word in words:s1=(s1+word)%mod;s2=(s2+s1)%mod
    check1=(mod-(s1+s2)%mod)%mod;check2=(mod-(s1+check1)%mod)%mod
    assert struct.unpack_from('<Q',b)[0]==check1|(check2<<32),'APFS object checksum';superblocks+=1
    if b[32:36]==b'APSB':identities.add(str(uuid.UUID(bytes=b[240:256])).upper())
  raw=bytes(chunk);marker=raw.find(b'<key>com.apple.watchdogd</key>')
  if marker>=0:
   lo=raw.rfind(b'<?xml',0,marker);hi=raw.find(b'</plist>',marker)
   if lo>=0 and hi>=0:policy=plistlib.loads(raw[lo:hi+8])
 assert identities=={'1552CFEE-78FF-48D8-8A6C-694B867D61AC'} and superblocks>0
 assert policy and policy['com.apple.watchdogd'] is True
 addon=files['kernel.macho.gpuaddon'].read_bytes();assert addon[:8]==b'NGPUADD2' and struct.unpack_from('<Q',addon,16)[0]==len(addon);at=24;entries={}
 for _ in range(struct.unpack_from('<I',addon,8)[0]):
  n,mode,size,packed=struct.unpack_from('<IIQQ',addon,at);at+=24;name=addon[at:at+n-1].decode();at+=(n+7)&~7;body=zlib.decompress(addon[at:at+packed]);at+=(packed+7)&~7;assert len(body)==size;entries[name]=(mode,body)
 assert at==len(addon) and 'bootshim/apfs_boot_util' in entries
 trust=modules(files['kernel.macho.trustcache'].read_bytes());old=temp/'old.trustcache';subprocess.run(['mcopy','-i',str(ROOT/'artifacts/b5q-esp-kernel-v10/esp.img'),'::/EFI/UniXNU/Payloads/kernel.macho.trustcache',str(old)],check=True)
 originals=modules(old.read_bytes());assert trust[:len(originals)]==originals
 trusted={m[i:i+20] for m in trust for i in range(24,len(m),24)};signed={}
 for name,(mode,body) in entries.items():
  if body[:4]==b'\xcf\xfa\xed\xfe':
   cdhashes=codesign(body);assert all(h in trusted for h in cdhashes),name;signed[name]=[h.hex() for h in cdhashes]
 assert 'bootshim/apfs_boot_util' in signed and entries['bootshim/apfs_boot_util'][0]&0o111
 report={'scope':'Actual final ESP extracted kernel, Data, addon and trust cache; local verification only','kernel_sha256':manifest['deploy_kernel_sha256'],'logical_Data_bytes':logical,'APFS_superblock_checksums_verified':superblocks,'APFS_volume_UUIDs':sorted(identities),'watchdogd_seed_policy':policy,'addon_paths':sorted(entries),'signed_and_trusted_executables':signed,'original_Apple_trust_modules_byte_identical':True,'hardware_tested':False}
 (package/'mount-verification.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
