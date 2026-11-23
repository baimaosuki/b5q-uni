#!/usr/bin/env python3
"""Production Python/C++ envelope cross-check and read-only installer negatives."""
from pathlib import Path
import hashlib,importlib.util,json,struct,subprocess,sys,tempfile,uuid,zlib
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts/b5q-install'))
import b5q_data_format as f

def rejected(call):
 try:call()
 except (ValueError,AssertionError):return
 raise AssertionError('negative input accepted')
def entry(name,first,last,id_):
 b=bytearray(128);b[:16]=bytes.fromhex('a2a0d0ebe5b9334487c068b6b72699c7');b[16:32]=id_;struct.pack_into('<QQ',b,32,first,last);b[56:56+len(name.encode('utf-16le'))]=name.encode('utf-16le');return b
capacity=f.ROOT_LAST+10000;table=entry('macosroot',f.ROOT_FIRST,f.ROOT_LAST,bytes.fromhex('01000000000000000000000000000000'))+entry('esp',3162880,3367679,bytes.fromhex('02000000000000000000000000000000'))
h=bytearray(4096);h[:8]=b'EFI PART';struct.pack_into('<4I4Q',h,8,0x10000,92,0,0,1,capacity-1,34,capacity-34);h[56:72]=bytes.fromhex('03000000000000000000000000000000');struct.pack_into('<QIII',h,72,2,2,128,zlib.crc32(table));struct.pack_into('<I',h,16,zlib.crc32(h[:92]))
disk,parts,root=f.parse_gpt(h,table,capacity);identity=f.choose(disk,parts,root,'macosroot-tail');config=f.envelope(identity,'e22a752e-523f-4ce4-a3ca-c8ad5c3753a0');f.validate_envelope(config,identity)
with (ROOT/'artifacts/b5q-full-27.3-26C5035r/delivery/macosroot.img').open('rb') as source:actual=hashlib.sha256(source.read(4096)).hexdigest()
assert actual==f.ROOT_HEADER_SHA
for offset in (0,8,12,16,24,32,40,48,56,64,96,112,128,144,160,4092):
 bad=bytearray(config);bad[offset]^=1;rejected(lambda:f.validate_envelope(bad,identity))
for badid in [dict(identity,first=f.ROOT_FIRST),dict(identity,last=f.ROOT_LAST-1),dict(identity,disk=bytes(16)),dict(identity,partition=bytes(16))]:rejected(lambda:f.validate_envelope(config,badid))
rejected(lambda:f.choose(disk,parts,root,'userdata'));rejected(lambda:f.choose(disk,parts,root,'macosdata'))
for offset in (0,8,12,16,24,32,40,48,56,72,80,84,88):
 bad=bytearray(h);bad[offset]^=1;rejected(lambda:f.parse_gpt(bad,table,capacity))
bad=bytearray(table);bad[100]^=1;rejected(lambda:f.parse_gpt(h,bad,capacity))
# The generated wire bytes must be accepted by the exact C++ driver parser.
with tempfile.TemporaryDirectory(prefix='b5q-data-format-') as td:
 d=Path(td);(d/'config.bin').write_bytes(config);src=d/'test.cpp'
 src.write_text('''#include <cstdio>
#include <cassert>
#include "B5qDataFormat.h"
int main(int argc,char **argv){assert(argc==2);FILE*f=fopen(argv[1],"rb");uint8_t h[4096];assert(f&&fread(h,1,4096,f)==4096);fclose(f);
B5qData::Identity id;id.mode=1;id.first=B5qData::tailFirst;id.last=B5qFormat::lastLba;id.disk[0]=3;id.partition[0]=1;
B5qData::Volume v;assert(B5qData::open(h,id,B5qFormat::lastLba+10000,v));assert(v.blocks==7864064);}
''')
 subprocess.run(['c++','-std=c++17','-fsanitize=address,undefined','-I',str(ROOT/'UniXNU-b5q/package/B5qUfs'),str(src),'-o',str(d/'test')],check=True);subprocess.run([str(d/'test'),str(d/'config.bin')],check=True)
print('PASS Python/C++ production Data envelope identity, root-header SHA, GPT CRC/geometry and wrong-window/alias negatives; no device access')
# Exercise the real CLI state machine with a fake ADB transport. No phone,
# partition, or host block device is opened. Validate all generated writes.
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('installer',ROOT/'scripts/b5q-install/install-data-ufs.py')
installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)
with tempfile.TemporaryDirectory(prefix='b5q-installer-cli-') as td:
 d=Path(td);image=d/'Data.img';image.write_bytes(bytes(4096));manifest=d/'Data.json'
 apfs_blocks=identity['last']-identity['first']+1-256
 m=dict(bytes=apfs_blocks*4096,apfs_blocks=apfs_blocks,sha256='a'*64,container_uuid='e22a752e-523f-4ce4-a3ca-c8ad5c3753a0',checkpoint_blocks={'0':'b'*64},tail_block_sha256='c'*64)
 manifest.write_text(json.dumps(m));real_header=(ROOT/'artifacts/b5q-full-27.3-26C5035r/delivery/macosroot.img').open('rb').read(4096)
 def cli(case,apply=False):
  writes=[];committed=False
  def check(args,**kwargs):
   nonlocal committed
   cmd=args[-1]
   if 'exec-out' in args:
    fields=dict(x.split('=',1) for x in cmd.split() if '=' in x)
    src=fields['if'];block=int(fields['skip']);n=int(fields['count'])
    assert src in ('/dev/block/sda','/dev/block/by-name/macosroot')
    if src=='/dev/block/sda':
     assert block in (1,2)
     if block==1:
      bad=bytearray(h)
      if case=='gpt-crc':bad[16]^=1
      return bytes(bad)
     return bytes(table)+bytes(n*4096-len(table))
    if block==0:return bytes(4096) if case=='root-hash' else real_header
    start=identity['first']-f.ROOT_FIRST
    assert start<=block<=start+256+apfs_blocks-1
    if block==start:return (bytes([1])+bytes(4095)) if case=='header-used' else config if committed else bytes(4096)
    if block==start+256:return bytes([1])+bytes(4095) if case=='apfs-used' else bytes(4096)
    return bytes(4096)
   if cmd=='id -u':return '2000' if case=='not-root' else '0'
   if cmd=='getprop ro.twrp.version':return '' if case=='not-twrp' else '3.7'
   if cmd=='getprop ro.product.device':return 'other' if case=='wrong-model' else 'b5q'
   if cmd=='getprop ro.product.model':return 'OTHER' if case=='wrong-model' else 'SM-F731B'
   if cmd.startswith('readlink -f /dev/block/'):return '/dev/block/sdb28' if case=='wrong-disk' else '/dev/block/sda28'
   if cmd=='readlink -f /sys/class/block/sda/device':return '/sys/0:0:0:1' if case=='wrong-lun' else '/sys/0:0:0:0'
   if cmd.startswith('blockdev --getss'):return '512' if case=='512-sector' else '4096'
   if cmd.startswith('blockdev --getsize64'):return str(capacity*4096)
   if cmd.endswith('/start'):return str(f.ROOT_FIRST*8+(1 if case=='sysfs-start' else 0))
   if cmd.endswith('/size'):return str((f.ROOT_LAST-f.ROOT_FIRST+1)*8)
   if cmd=='cat /proc/swaps':return 'Filename Type Size Used Priority'
   if cmd=='cat /proc/mounts':return '/dev/block/sda28 /data apfs rw 0 0' if case=='mounted' else ''
   if 'sha256sum' in cmd:return ('0' if case=='readback-sha' else 'a')*64+'  -'
   raise AssertionError(cmd)
  def run(args,**kwargs):
   nonlocal committed
   cmd=args[-1];assert 'dd of=/dev/block/by-name/macosroot ' in cmd
   fields=dict(x.split('=',1)for x in cmd.split()if '=' in x)
   start=int(fields['seek']);count=int(fields['count']);assert fields['bs']=='4096' and fields['conv']=='fsync'
   if 'input'in kwargs:assert start==identity['first']-f.ROOT_FIRST and count==1;committed=True
   else:assert start==identity['first']-f.ROOT_FIRST+256 and count==apfs_blocks
   writes.append((start,count));return subprocess.CompletedProcess(args,0)
  # Fixture byte hashes are deterministic; this substitution only affects
  # post-write mock sectors, not the production local_image test above.
  real_sha=hashlib.sha256
  def sha(data=b''):
   if data==bytes(4096):
    class Hash:
     def hexdigest(self):return 'b'*64 if case!='checkpoint-fail' else '0'*64
    return Hash()
   return real_sha(data)
  # Use identical checkpoint/tail digest for the mock sectors.
  m['tail_block_sha256']='b'*64;manifest.write_text(json.dumps(m))
  argv=['install-data-ufs.py','--image',str(image)]+(['--apply']if apply else [])
  try:
   with patch.object(sys,'argv',argv),patch.object(installer,'local_image'),patch.object(subprocess,'check_output',side_effect=check),patch.object(subprocess,'run',side_effect=run),patch.object(hashlib,'sha256',side_effect=sha):installer.main()
  except (ValueError,SystemExit,AssertionError) as e:return False,writes,str(e)
  return True,writes,''
 assert cli('ok')[0] and cli('ok')[1]==[]
 for case in ('not-root','not-twrp','wrong-model','wrong-disk','wrong-lun','512-sector','gpt-crc','root-hash','sysfs-start','header-used','apfs-used','mounted'):
  ok,writes,error=cli(case,True);assert not ok and not writes,(case,error,writes)
 for case in ('readback-sha','checkpoint-fail'):
  ok,writes,error=cli(case,True);assert not ok and len(writes)==1,(case,error,writes)
 ok,writes,error=cli('ok',True);assert ok and len(writes)==2,(error,writes)
print('PASS real installer.main: check-only, validated payload/envelope write order, 14 refusal/failure cases, no envelope commit on readback failure')
