#!/usr/bin/env python3
"""Allocated zero blocks must survive sparse initialization; reject corrupt maps."""
import hashlib,json,struct,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts/b5q-install'))
from apfs_sparse_init import allocation_plan
from b5q_data_format import fletcher

def seal(b):
 mod=0xffffffff;s1=s2=0
 for w in struct.unpack('<1022I',b[8:]):s1=(s1+w)%mod;s2=(s2+s1)%mod
 c1=(mod-(s1+s2)%mod)%mod;c2=(mod-(s1+c1)%mod)%mod
 struct.pack_into('<Q',b,0,c1|(c2<<32));assert fletcher(b);return b
def obj(kind):
 b=bytearray(4096);struct.pack_into('<QQII',b,8,100,10,kind,0);return b
def fixture(path,corrupt=None):
 N=16384;used=set(range(32))|{1000};nx=obj(1);nx[32:36]=b'NXSB';struct.pack_into('<IQ',nx,36,4096,N)
 struct.pack_into('<IIQQ6I3Q',nx,104,2,2,1,3,0,0,0,2,0,2,100,0,0)
 cpm=obj(12);struct.pack_into('<II',cpm,32,1,1);struct.pack_into('<4I3Q',cpm,40,5,0,4096,0,0,100,3)
 sm=obj(5);struct.pack_into('<4I',sm,32,4096,32768,126,507)
 struct.pack_into('<QQIIQIIQ',sm,48,N,1,1,0,N-len(used),512,0,0)
 struct.pack_into('<QIIQQ',sm,152,4,1,2,14,16);struct.pack_into('<Q',sm,512,7)
 cib=obj(7);struct.pack_into('<II',cib,32,0,1);struct.pack_into('<QQIIQ',cib,40,10,0,N,N-len(used),8)
 bits=bytearray(4096)
 for bit in used:bits[bit//8]|=1<<(bit%8)
 if corrupt=='free-count':struct.pack_into('<I',cib,64,N)
 if corrupt=='bitmap':bits[1000//8]^=1<<(1000%8)
 if corrupt=='bounds':struct.pack_into('<Q',sm,176,N+1)
 with path.open('wb')as f:
  f.truncate(N*4096)
  for block,b in [(0,seal(nx)),(1,seal(cpm)),(2,nx),(3,seal(sm)),(7,seal(cib)),(8,bits),(28,bytearray(b'x'*4096))]:f.seek(block*4096);f.write(b)
def covers(plan,block):return any(s['block']<=block<s['block']+s['blocks']for s in plan['segments'])
with tempfile.TemporaryDirectory()as td:
 p=Path(td)/'apfs.img';fixture(p);plan=allocation_plan(p)
 assert plan['allocated_blocks']==33 and covers(plan,1000) and covers(plan,16) and covers(plan,19) and covers(plan,16383)
 target=Path(td)/'restored.img'
 with target.open('wb')as f:f.truncate(p.stat().st_size)
 with p.open('rb')as src,target.open('r+b')as dst:
  # Model a device with stale nonzero bytes at an allocated zero block.
  dst.seek(1000*4096);dst.write(b'\xa5'*4096)
  for s in plan['segments']:
   src.seek(s['block']*4096);body=src.read(s['blocks']*4096)
   assert hashlib.sha256(body).hexdigest()==s['sha256'];dst.seek(s['block']*4096);dst.write(body)
 with target.open('rb')as f:f.seek(1000*4096);assert f.read(4096)==bytes(4096)
 for case in ('free-count','bitmap','bounds'):
  fixture(p,case)
  try:allocation_plan(p)
  except AssertionError:pass
  else:raise AssertionError('accepted '+case)
print('PASS APFS sparse production planner: allocated zero data, internal pool, tail, stale-device restore; 3 corrupt-map refusals')
