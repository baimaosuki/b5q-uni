#!/usr/bin/env python3
"""Check stock TFA plans against an independent original-container decoder."""
from pathlib import Path
import struct,hashlib,subprocess,tempfile,zlib
R=Path(__file__).resolve().parents[2]
stock=R/'artifacts/firmware-b5q/F7310ZCS7EYF3/vendor/firmware/tfa98xx.cnt'
b=stock.read_bytes()
assert hashlib.sha256(b).hexdigest()=='540934d3f79bbbef1c1503f3e531f2e2cf92a1ec0c735a898f3bed5d7b350f49'
assert zlib.crc32(b[14:])==struct.unpack_from('<I',b,10)[0]
def ptr(at):v=struct.unpack_from('<I',b,at)[0];return v>>24,v&0xffffff
def text(at):kind,off=ptr(at);assert kind==3;return b[off:b.index(0,off)].decode()
expected=[]
for d in range(2):
    kind,off=ptr(46+4*d);address=b[off+2];assert kind==0 and address in (0x34,0x35)
    regs=[];selected=None
    for i in range(b[off]):
        kind,at=ptr(off+12+4*i)
        if kind in (1,4,5):break
        if kind==16:regs.append(struct.unpack_from('<HH',b,at))
    for i in range(b[off]):
        kind,at=ptr(off+12+4*i)
        if kind==1 and text(at+4)=='default':selected=at
    assert selected
    for i in range(b[selected]-1):
        kind,at=ptr(selected+8+4*i)
        if kind==17:break
        assert kind==16;regs.append(struct.unpack_from('<HH',b,at))
    for value,field in regs:
        bits=(field&15)+1;shift=(field>>4)&15;mask=((1<<bits)-1)<<shift
        expected.append((address,field>>8,mask,value<<shift))
rows=','.join('{'+','.join(map(str,row))+'}'for row in expected)
code=r'''
#include <cassert>
#include <cstdio>
#include <vector>
#include <map>
#include <fstream>
#include <iterator>
#include "B5qTfaContainer.h"
struct Expected {uint8_t addr,reg;uint16_t mask,value;};
Expected expected[]={ROWS};
int main(int argc,char **argv){assert(argc==2);std::ifstream f(argv[1],std::ios::binary);std::vector<uint8_t>b((std::istreambuf_iterator<char>(f)),{});using namespace B5qTfa;
 Container c;assert(c.init(b.data(),b.size()));Program top,bottom;
 assert(c.program(0x35,"default",top)&&c.program(0x34,"default",bottom));
 assert(top.count+bottom.count==sizeof(expected)/sizeof(expected[0]));unsigned n=0;
 for(auto p:{top,bottom})for(unsigned i=0;i<p.count;++i){auto u=p.updates[i];auto e=expected[n++];assert(u.address==e.addr&&u.reg==e.reg&&u.mask==e.mask&&u.value==e.value);}
 for(unsigned point=0;point<top.count*2;++point){unsigned calls=0;assert(!apply(top,[&](uint8_t,uint8_t,uint16_t &v){v=0x5a5a;return calls++!=point;},[&](uint8_t,uint8_t,uint16_t){return calls++!=point;}));assert(calls==point+1);}
 std::map<uint16_t,uint16_t>regs;auto read=[&](uint8_t a,uint8_t r,uint16_t &v){v=regs[uint16_t(a)<<8|r];return true;};auto write=[&](uint8_t a,uint8_t r,uint16_t v){regs[uint16_t(a)<<8|r]=v;return true;};assert(apply(top,read,write)&&apply(bottom,read,write));
 assert((regs[0x3526]&15)==0&&(regs[0x3426]&15)==1); // original stereo slot assignments
 Program refused;assert(!c.program(0,"default",refused)&&!c.program(0x34,"unknown",refused)&&!refused.count);
 for(size_t size=0;size<b.size();++size){Container shortc;assert(!shortc.init(b.data(),size));}
 for(size_t at=0;at<b.size();++at){b[at]^=1;Container corrupt;assert(!corrupt.init(b.data(),b.size()));b[at]^=1;}
 // Valid-CRC malformed pointers/bitfields must be rejected atomically.
 for(unsigned at:{46u,50u}){auto altered=b;altered[at+3]=255;uint32_t crc=B5qFormat::crc32(altered.data()+14,altered.size()-14);memcpy(altered.data()+10,&crc,4);Container bad;assert(bad.init(altered.data(),altered.size()));assert(!bad.program(0x34,"default",refused)&&!refused.count);}
 puts("PASS actualSamsung5096Bcnt:2defaultprofiles match independentdecoder,stereoslots,RMWfaultstop,alltruncations/all5096bitcorruptions,badpointers ASanUBSan");
}
'''.replace('ROWS',rows)
with tempfile.TemporaryDirectory(prefix='b5q-tfa-container-')as td:
    td=Path(td);(td/'test.cpp').write_text(code)
    subprocess.run(['c++','-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-Wno-misleading-indentation',
        '-fsanitize=address,undefined','-I'+str(R/'UniXNU-b5q/package'),str(td/'test.cpp'),'-o',str(td/'test')],check=True)
    subprocess.run([str(td/'test'),str(stock)],check=True)
