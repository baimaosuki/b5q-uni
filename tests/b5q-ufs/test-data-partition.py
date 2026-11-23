#!/usr/bin/env python3
"""Exercise both production GPT selection modes, envelopes and LBA limits."""
import copy,json,struct,subprocess,sys,tempfile,uuid,zlib
from pathlib import Path
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'scripts/b5q-install'))
import b5q_data_format as fmt
CAPACITY=80_000_000
DISK=uuid.UUID('97bcc9bd-a523-439b-9aa3-03b45cb13b70').bytes
ROOT_UUID=uuid.UUID('1fef19e4-05ca-46ca-a6cd-81496ab54c2a').bytes
DATA_UUID=uuid.UUID('e4694868-4390-4c16-a142-fe294388c371').bytes
CONTAINER='e22a752e-523f-4ce4-a3ca-c8ad5c3753a0'
def part(name,first,last,identity):return dict(name=name,first=first,last=last,uuid=identity)
root=part('macosroot',fmt.ROOT_FIRST,fmt.ROOT_LAST,ROOT_UUID)
esp=part('esp',3162880,3367679,uuid.UUID('22cb37ea-cbfe-4fad-8ca7-7954f2de2368').bytes)
data=part('macosdata',63_000_000,70_864_319,DATA_UUID)
def wire(parts):
 table=bytearray(128*len(parts))
 for i,p in enumerate(parts):
  at=i*128;table[at:at+16]=bytes.fromhex('a2a0d0ebe5b9334487c068b6b72699c7')
  table[at+16:at+32]=p['uuid'];struct.pack_into('<QQ',table,at+32,p['first'],p['last'])
  name=p['name'].encode('utf-16le');table[at+56:at+56+len(name)]=name
 h=bytearray(4096);h[:8]=b'EFI PART';struct.pack_into('<4I4Q',h,8,0x10000,92,0,0,1,CAPACITY-1,34,CAPACITY-34);h[56:72]=DISK
 struct.pack_into('<QIII',h,72,2,len(parts),128,zlib.crc32(table));struct.pack_into('<I',h,16,zlib.crc32(h[:92]));return h,table
cases=[('tail',False,[root,esp],True),('explicit-separate',True,[root,esp,data],True),('separate-priority',True,[root,esp,data],True),('tail-with-separate-present',False,[root,esp,data],True),('missing-separate',True,[root,esp],False),('duplicate-name',True,[root,esp,data,dict(data,first=72_000_000,last=72_001_000,uuid=uuid.uuid4().bytes)],False),('zero-partition-uuid',True,[root,esp,dict(data,uuid=bytes(16))],False),('uuid-alias',True,[root,esp,dict(data,uuid=ROOT_UUID)],False),('root-overlap',True,[root,esp,dict(data,first=fmt.ROOT_LAST,last=fmt.ROOT_LAST+1000)],False),('ESP-overlap',True,[root,esp,dict(data,first=esp['first'],last=esp['last'])],False),('metadata-overlap',True,[root,esp,dict(data,first=200,last=1000)],False),('capacity-overrun',True,[root,esp,dict(data,last=CAPACITY)],False),('envelope-only',True,[root,esp,dict(data,last=data['first']+255)],False)]
runner=r'''
#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include <cstring>
#include "B5qDataFormat.h"
std::vector<uint8_t> read(const char*p){FILE*f=fopen(p,"rb");assert(f);fseek(f,0,SEEK_END);size_t n=ftell(f);rewind(f);std::vector<uint8_t>b(n);assert(fread(b.data(),1,n,f)==n);fclose(f);return b;}
int main(int argc,char**argv){assert(argc==7);auto h=read(argv[1]),t=read(argv[2]);bool separate=atoi(argv[3]),expected=atoi(argv[4]);auto envelope=read(argv[5]);B5qFormat::Gpt g{};B5qData::Identity id;assert(B5qFormat::header(h.data(),80000000,g));bool ok=B5qData::select(h.data(),t.data(),g,separate,80000000,id);assert(ok==expected);
if(!ok)return 0;assert(id.mode==(separate?2U:1U));assert(B5qFormat::equal(id.partition,t.data()+(separate?256:0)+16,16));B5qData::Volume v;assert(B5qData::open(envelope.data(),id,80000000,v));
uint64_t lba=0;assert(B5qData::absolute(v,0,1,lba)&&lba==id.first+256);assert(B5qData::absolute(v,v.blocks-1,1,lba)&&lba==id.last);assert(!B5qData::absolute(v,v.blocks,1,lba));assert(!B5qData::absolute(v,UINT64_MAX,1,lba));assert(!B5qData::absolute(v,0,UINT64_MAX,lba));assert(!B5qData::absolute(v,0,0,lba));
uint8_t ucd[B5qUfsProtocol::dataOffset]={};uint32_t utrd[8]={};assert(B5qData::request(utrd,ucd,0x8d0000000,0,v,B5qData::Direction::Write,0,1));assert(ucd[16]==0x2a&&ucd[17]==8&&B5qFormat::be32(ucd+18)==id.first+256);assert(!B5qData::request(utrd,ucd,0x8d0000000,1,v,B5qData::Direction::Write,0,1));
// A valid CRC cannot excuse the wrong GPT identity or window.
auto wrong=id;wrong.partition[0]^=1;assert(!B5qData::open(envelope.data(),wrong,80000000,v));wrong=id;wrong.disk[0]^=1;assert(!B5qData::open(envelope.data(),wrong,80000000,v));
}
'''
results=[]
with tempfile.TemporaryDirectory(prefix='b5q-data-gpt-modes-')as td:
 d=Path(td);src=d/'select.cpp';src.write_text(runner);exe=d/'select'
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=address,undefined','-I',str(R/'UniXNU-b5q/package/B5qUfs'),str(src),'-o',str(exe)],check=True)
 for name,separate,parts,expected in cases:
  h,t=wire(parts);mode='macosdata'if separate else'macosroot-tail'
  try:
   disk,parsed,rootpart=fmt.parse_gpt(h,t,CAPACITY);identity=fmt.choose(disk,parsed,rootpart,mode);config=fmt.envelope(identity,CONTAINER);fmt.validate_envelope(config,identity);ok=True
  except ValueError:ok=False;config=bytes(4096)
  assert ok==expected,(name,ok,expected)
  for fname,body in [('header',h),('table',t),('config',config)]: (d/fname).write_bytes(body)
  subprocess.run([str(exe),str(d/'header'),str(d/'table'),str(int(separate)),str(int(expected)),str(d/'config'),name],check=True)
  results.append(dict(name=name,expected_accepted=expected,passed=True))
report=dict(passed=True,scope='actual Python GPT/choose/envelope and C++ header/select/open/absolute/request, ASan+UBSan; synthetic partitions, no device access',cases=results)
(R/'artifacts/b5q-batch2-work/data-partition-modes.json').write_text(json.dumps(report,indent=2)+'\n');print('PASS',len(results),'paired Python/C++ production GPT selection cases, both modes, UUID/overlap/metadata/capacity/envelope and LBA/FUA bounds')
