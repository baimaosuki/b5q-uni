#!/usr/bin/env python3
"""Run the real userdata conversion CLI with fake ADB; never open a device."""
from pathlib import Path
from unittest.mock import patch
import hashlib,importlib.util,io,json,struct,subprocess,sys,tempfile,uuid,zlib
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'scripts/b5q-install'))
import b5q_data_format as fmt
spec=importlib.util.spec_from_file_location('installer',R/'scripts/b5q-install/install-data-ufs.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
CAP=fmt.ROOT_LAST+10000
parts=[('macosroot',fmt.ROOT_FIRST,fmt.ROOT_LAST,1),('userdata',fmt.USERDATA_FIRST,fmt.USERDATA_LAST,2),('esp',3162880,3367679,3)]
def gpt(case):
 table=bytearray(128*len(parts))
 for i,(name,first,last,uid)in enumerate(parts):
  if name=='userdata'and case=='wrong-bounds':first+=1
  at=128*i;table[at:at+16]=bytes([0x83])+bytes(15);table[at+16:at+32]=uid.to_bytes(16,'little');struct.pack_into('<QQ',table,at+32,first,last);b=name.encode('utf-16le');table[at+56:at+56+len(b)]=b
 h=bytearray(4096);h[:8]=b'EFI PART';struct.pack_into('<4I4Q',h,8,0x10000,92,0,0,1,CAP-1,34,CAP-34);h[56:72]=(4).to_bytes(16,'little');struct.pack_into('<QIII',h,72,2,len(parts),128,zlib.crc32(table));struct.pack_into('<I',h,16,zlib.crc32(h[:92]))
 if case=='bad-gpt-crc':h[16]^=1
 return bytes(h),bytes(table)+bytes(4096-len(table))
with (R/'artifacts/b5q-full-27.3-26C5035r/delivery/macosroot.img').open('rb')as f:ROOT_HEADER=f.read(4096)
assert hashlib.sha256(ROOT_HEADER).hexdigest()==fmt.ROOT_HEADER_SHA
cases=[]
with tempfile.TemporaryDirectory(prefix='b5q-userdata-cli-')as td:
 d=Path(td);image=d/'data.img';image.write_bytes(bytes(4096));blocks=fmt.USERDATA_LAST-fmt.USERDATA_FIRST+1-256
 manifest=dict(bytes=blocks*4096,apfs_blocks=blocks,sha256='a'*64,container_uuid='e22a752e-523f-4ce4-a3ca-c8ad5c3753a0',checkpoint_blocks={'0':hashlib.sha256(bytes(4096)).hexdigest()},tail_block_sha256=hashlib.sha256(bytes(4096)).hexdigest())
 (d/'data.json').write_text(json.dumps(manifest))
 def exercise(case,apply=True,replace=True):
  h,t=gpt(case);writes=[];committed=None
  def output(args,**kw):
   nonlocal committed
   cmd=args[-1]
   if 'exec-out'in args:
    v=dict(s.split('=',1)for s in cmd.split()if '='in s);source=v['if'];block=int(v['skip']);count=int(v['count']);assert count==1
    if source=='/dev/block/sda':return h if block==1 else t
    if source=='/dev/block/by-name/macosroot':assert block==0;return ROOT_HEADER
    assert source=='/dev/block/by-name/userdata' and block in (0,256,256+blocks-1)
    if block==0:
     if committed is not None:return committed
     if case=='initialized':return b'B5QDATA1'+bytes(4088)
     if case=='raw-apfs':return bytes(32)+b'NXSB'+bytes(4060)
     return b'ANDROID-OLD'+bytes(4085)
    if block==256:
     if case=='existing-apfs':return bytes(32)+b'NXSB'+bytes(4060)
     if len(writes):return bytes([1])+bytes(4095)if case=='bad-checkpoint'else bytes(4096)
     return b'ENCRYPTED'+bytes(4087)
    return bytes([1])+bytes(4095)if case=='bad-tail'else bytes(4096)
   if cmd=='id -u':return '2000'if case=='not-root'else'0'
   if cmd=='getprop ro.twrp.version':return ''if case=='not-twrp'else'3.7'
   if cmd=='getprop ro.product.device':return 'other'if case=='wrong-model'else'b5q'
   if cmd=='getprop ro.product.model':return 'OTHER'if case=='wrong-model'else'SM-F731B'
   if cmd=='readlink -f /sys/class/block/sda/device':return '/sys/0:0:0:1'if case=='wrong-lun'else'/sys/0:0:0:0'
   if cmd=='readlink -f /dev/block/by-name/macosroot':return '/dev/block/sda37'
   if cmd=='readlink -f /dev/block/by-name/userdata':return '/dev/block/sdb36'if case=='wrong-disk'else'/dev/block/sda36'
   if cmd=='blockdev --getss /dev/block/sda':return '512'if case=='wrong-sector'else'4096'
   if cmd=='blockdev --getsize64 /dev/block/sda':return str(CAP*4096)
   if cmd=='cat /sys/class/block/sda37/start':return str(fmt.ROOT_FIRST*8)
   if cmd=='cat /sys/class/block/sda37/size':return str((fmt.ROOT_LAST-fmt.ROOT_FIRST+1)*8)
   if cmd=='cat /sys/class/block/sda36/start':return str(fmt.USERDATA_FIRST*8+(1 if case=='wrong-sysfs'else 0))
   if cmd=='cat /sys/class/block/sda36/size':return str((fmt.USERDATA_LAST-fmt.USERDATA_FIRST+1)*8)
   if cmd=='cat /proc/mounts':return '/dev/block/dm-0 /data f2fs rw 0 0'if case=='mounted-dm'else'/dev/block/sda36 /other ext4 rw 0 0'if case=='mounted-direct'else''
   if cmd=='command -v gzip || true':return ''if case=='raw-fallback'else'/sbin/gzip'
   if cmd=='cat /proc/swaps':return 'Filename Type Size Used Priority\n'+('/dev/block/sda36 partition 1 0 -1'if case=='swap'else'')
   if 'sha256sum'in cmd:
    assert cmd.startswith('set -o pipefail; dd if=/dev/block/by-name/userdata ')
    return ('0'if case=='bad-sha'else'a')*64+'  -'
   raise AssertionError(cmd)
  def run(args,**kw):
   nonlocal committed
   if case=='remote-gzip-error' and 'gzip -dc'in args[-1]:raise subprocess.CalledProcessError(1,args)
   v=dict(s.split('=',1)for s in args[-1].split()if '='in s)
   assert v['of']=='/dev/block/by-name/userdata' and v['bs']=='4096'and v['conv']=='fsync'
   if 'input'in kw:
    assert len(writes)==1 and int(v['seek'])==0 and 'count'not in v and len(kw['input'])==4096
    committed=kw['input'];identity=fmt.choose((4).to_bytes(16,'little'),[dict(name=n,first=a,last=b,uuid=i.to_bytes(16,'little'))for n,a,b,i in parts],dict(), 'userdata');fmt.validate_envelope(committed,identity)
   else:assert int(v['seek'])==256 and 'count' not in v
   writes.append(v);return subprocess.CompletedProcess(args,0)
  class Encoder:
   def __init__(self,*args,**kwargs):self.stdout=io.BytesIO()
   def wait(self):return 1 if case=='local-gzip-error'else 0
  argv=['installer','--image',str(image),'--partition','userdata']+(['--apply']if apply else[])+(['--replace-android-data']if replace else[])
  try:
   with patch.object(sys,'argv',argv),patch.object(m,'local_image'),patch.object(m.shutil,'which',return_value='/usr/bin/gzip'),patch.object(subprocess,'Popen',side_effect=Encoder),patch.object(subprocess,'check_output',side_effect=output),patch.object(subprocess,'run',side_effect=run):m.main()
  except (ValueError,SystemExit,subprocess.CalledProcessError)as e:return False,writes,str(e)
  return True,writes,''
 for c in ['not-root','not-twrp','wrong-model','wrong-lun','wrong-sector','bad-gpt-crc','wrong-bounds','wrong-disk','wrong-sysfs','mounted-dm','mounted-direct','swap','initialized','raw-apfs','existing-apfs']:
  ok,writes,error=exercise(c);assert not ok and not writes,(c,error,writes);cases.append(c)
 ok,writes,error=exercise('ok',replace=False);assert not ok and not writes;cases.append('missing-explicit-replacement')
 for c in ('bad-sha','bad-checkpoint','bad-tail'):
  ok,writes,error=exercise(c);assert not ok and len(writes)==1,(c,error,writes);cases.append(c)
 for c in ('local-gzip-error','remote-gzip-error'):
  ok,writes,error=exercise(c);assert not ok and len(writes)==(0 if c=='remote-gzip-error'else 1),(c,error,writes);cases.append(c)
 ok,writes,error=exercise('raw-fallback');assert ok and len(writes)==2;cases.append('raw-fallback')
 ok,writes,error=exercise('ok',apply=False);assert ok and not writes,(error,writes);cases.append('check-only')
 ok,writes,error=exercise('ok');assert ok and len(writes)==2,(error,writes);cases.append('explicit-convert')
print('PASS actual userdata installer.main:',len(cases),'cases; only exact userdata target writes, no GPT/root writes; refuse mounted/dm-data/swap/existingmacOS/identity/bounds and commit only after readback')
