#!/usr/bin/env python3
"""Reject every retained DPU resource; no primary display write is performed."""
from pathlib import Path
import subprocess,tempfile
R=Path(__file__).resolve().parents[2]
h=r'''
#include <cassert>
#include <cstdio>
#include <map>
#include "B5qDpDpuResources.h"
using namespace B5qDp;
struct Io {
 std::map<unsigned,uint32_t> regs;unsigned reads=0;
 uint32_t read(unsigned off){assert(off>=0x5000&&off<0x84000&&!(off&3));reads++;return regs[off];}
};
int main(){unsigned cases=0;
 auto inspect=[](Io &io){DpuResources r;r.inspect([&](unsigned off){return io.read(off);});return r;};
 {Io io;io.regs[0x160f4]=2;io.regs[DpuResources::layer(0,0,0)]=1;io.regs[DpuResources::layer(0,1,0)]=1u<<3;
  io.regs[0x45004]=0x0a500438;io.regs[0x46004]=0x0a500438;
  auto r=inspect(io);assert(r.usedCtl[0]&&r.usedLm[0]&&r.usedLm[1]&&r.usedPipe[0]&&r.usedPipe[1]);
  assert(r.choose(3840)&&r.ctl!=0&&r.lm[0]>=2&&r.count==2&&r.pipe[0]>=4&&r.pipe[1]>=4);cases++;}
 // All solo and multirect stage placements on all retained CTL/LM pairs.
 for(unsigned c=0;c<6;c++)for(unsigned m=0;m<6;m++)for(unsigned p=0;p<10;p++)for(bool rect1:{false,true}){
  Io io;unsigned e=rect1?DpuResources::rect1Ext[p]:DpuResources::pipeExt[p];
  unsigned shift=rect1?DpuResources::rect1Shift[p]:DpuResources::pipeShift[p];
  io.regs[DpuResources::layer(c,m,e)]=1u<<shift;auto r=inspect(io);
  assert(r.usedCtl[c]&&r.usedLm[m]&&r.usedPipe[p]);if(r.choose(1920))assert(r.ctl!=c&&r.lm[0]!=m&&r.pipe[0]!=p);cases++;
 }
 for(unsigned p=0;p<10;p++){
  Io io;io.regs[0x160fc]=1u<<(p<4?16+p:p-4);auto r=inspect(io);assert(r.usedPipe[p]&&r.usedCtl[0]);cases++;
 }
 for(unsigned p=0;p<6;p++){
  Io io;io.regs[DpuResources::layer(0,5,1)]=1u<<(p<4?2*p:16+2*(p-4));auto r=inspect(io);assert(r.usedPipe[p]&&r.usedLm[5]);cases++;
 }
 for(unsigned ctlMask=0;ctlMask<64;ctlMask++)for(unsigned lmMask=0;lmMask<64;lmMask++){
  Io io;for(unsigned c=0;c<6;c++)if(ctlMask&(1u<<c))io.regs[DpuResources::ctlBase[c]+0x64]=1;
  for(unsigned m=0;m<6;m++)if(lmMask&(1u<<m))io.regs[DpuResources::lmBase[m]+4]=1;
  auto r=inspect(io);bool pair=false;for(unsigned m=0;m<6;m+=2)pair=pair||!(lmMask&(3u<<m));
  assert(r.choose(3840)==(ctlMask!=63&&pair));if(r.count)assert(!(ctlMask&(1u<<r.ctl))&&!(lmMask&(1u<<r.lm[0]))&&!(lmMask&(1u<<r.lm[1])));cases++;
 }
 for(unsigned mask=0;mask<64;mask++){
  Io io;unsigned free=0;for(unsigned p=4;p<10;p++){if(mask&(1u<<(p-4)))io.regs[DpuResources::pipeBase[p]]=1;else free++;}
  auto r=inspect(io);assert(r.choose(3840)==(free>=2));assert(r.choose(1920)==(free>=1));cases++;
 }
 for(unsigned off:{0x35000u,0x160f4u}){Io io;io.regs[off]=1;auto r=inspect(io);assert(r.dpBusy&&!r.choose(1920));cases++;}
 {Io io;auto r=inspect(io);assert(!r.choose(0)&&!r.choose(5121)&&r.choose(5120));}
 puts("PASS production DPU resource discovery:all retained CTL/LM/SSPP rect0/1/highbits/fetch/pairs/full/busy/bounds; no writes");
 printf("PASS %u DPU ownership cases ASanUBSan\n",cases);
}
'''
with tempfile.TemporaryDirectory(prefix='b5q-dpu-resources-')as td:
 t=Path(td);(t/'test.cpp').write_text(h)
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(R/'UniXNU-b5q/package'),str(t/'test.cpp'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test')],check=True)
