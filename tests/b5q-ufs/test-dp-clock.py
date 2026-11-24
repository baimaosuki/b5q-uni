#!/usr/bin/env python3
"""Check Samsung DP RCG framing, exact rates and bounded failures."""
from pathlib import Path
import subprocess,tempfile
R=Path(__file__).resolve().parents[2]
h=r'''
#include <cassert>
#include <cstdio>
#include <map>
#include <tuple>
#include <vector>
#include "B5qDpClock.h"
using namespace B5qDp;
struct Io {
 std::map<unsigned,uint32_t> regs;std::vector<std::tuple<unsigned,uint32_t>>writes;bool updateStuck=false,branchStuck=false;unsigned elapsed=0;
 uint32_t read(Block b,unsigned off){assert(b==Block::DispCc);uint32_t v=regs[off];if(off==0x81bc||off==0x8170||off==0x818c)return updateStuck?v:v&~1u;return branchStuck?v|0x80000000u:v&~0x80000000u;}
 void write(Block b,unsigned off,uint32_t value){assert(b==Block::DispCc);regs[off]=value;writes.emplace_back(off,value);}
 void delay(unsigned us){elapsed+=us;}
};
int main(){unsigned cases=0;
 for(unsigned rate:{6u,10u,20u,30u})for(unsigned pixel:{25175u,27000u,74250u,148500u,241500u,297000u,533250u,594000u}){
  Io io;Clock<Io>c(io);assert(c.aux()&&c.link()&&c.pixel(pixel,rate));assert((io.regs[0x81c0]&0x71f)==1&&(io.regs[0x8174]&0x71f)==0x101&&(io.regs[0x8190]&0x71f)==0x201);
  const unsigned parent=rate==6?810000:1350000;const unsigned m=io.regs[0x8194],n=((~io.regs[0x8198])&65535)+m;assert(uint64_t(parent)*m==uint64_t(pixel)*n);assert(m&&m<=65535&&n<=65535);cases++;
 }
 {Io io;io.updateStuck=true;Clock<Io>c(io);assert(!c.aux()&&io.elapsed==1000&&c.failed==0x81bc);}
 {Io io;io.branchStuck=true;Clock<Io>c(io);assert(!c.link()&&io.elapsed==1000&&c.failed==0x8040);}
 {Io io;Clock<Io>c(io);assert(!c.pixel(0,20)&&!c.pixel(148500,9)&&io.writes.empty());}
 for(unsigned out=1;out<65536;out++){Ratio r;assert(r.make(out,65535)&&uint64_t(out)*r.n==uint64_t(65535)*r.m);cases++;}
 printf("PASS SamsungDPclock %ucases:exactMND/DP0VCOparent/RCGpreservation/4linkrates/32displayclocks/1msbounds ASanUBSan\n",cases);
}
'''
with tempfile.TemporaryDirectory(prefix='b5q-dp-clock-')as td:
 t=Path(td);(t/'test.cpp').write_text(h)
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-O1','-g','-fsanitize=address,undefined','-I'+str(R/'UniXNU-b5q/package'),str(t/'test.cpp'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test')],check=True)
