#!/usr/bin/env python3
"""Exercise production two-buffer ownership and real-register latch gating."""
from pathlib import Path
import subprocess,tempfile
R=Path(__file__).resolve().parents[2]
source=r'''
#include <cassert>
#include <cstdio>
#include <map>
#include <vector>
#include <cstdint>
#include "B5qDpPresentation.h"
using namespace B5qDp;
struct Io {
 std::map<unsigned,uint32_t> regs;std::vector<unsigned>writes;
 unsigned fills=0,cleans=0,copies=0,notifies=0,arms=0,disarms=0,stops=0;
 uint64_t tick=100;bool allowed=true,copyOk=true,cleanOk=true,fillOk=true,
 armOk=true,videoOk=true,stopOk=true,drainOk=true,running=true,autoFlush=true;
 uint32_t read(unsigned off){return regs[off];}
 void write(unsigned off,uint32_t value){writes.push_back(off);regs[off]=value;}
 void barrier(){}
 void delay(unsigned us){tick+=us;if(running){regs[0x3526c]=regs[0x35000]&1;
  if(regs[0x35000]&1)regs[0x350ac]++;}
  if(autoFlush)for(unsigned c=0;c<6;c++)regs[DpuResources::ctlBase[c]+0x18]=0;
 }
 bool dmaAllowed(uint64_t a,uint64_t n){return allowed&&a>=0xc0000000&&a<=0xc4000000&&n<=0xc4000000-a;}
 bool fill(const ScanoutBuffer &b,uint64_t bytes){assert(bytes<=b.bytes);fills++;return fillOk;}
 bool clean(const ScanoutBuffer &b,uint64_t bytes){assert(bytes<=b.bytes);cleans++;return cleanOk;}
 bool copy(const ScanoutBuffer &b,const void *p,const Mode &m,unsigned stride){
  assert(p&&uint64_t(stride)*m.height<=b.bytes);copies++;return copyOk;
 }
 bool arm(Presentation *p){assert(p&&p->dpu.active);arms++;return armOk;}
 bool video(){return videoOk;}
 void notify(uint32_t,uint64_t){notifies++;}
 bool disarm(){disarms++;return drainOk;}
 bool stopVideo(){stops++;return stopOk;}
 uint64_t nowUs(){return tick;}
 void latch(Presentation &p){regs[p.dpu.resources.ctlBase[p.dpu.resources.ctl]+0x18]=0;regs[0x350ac]++;}
};
const Mode mode{148500,1920,1080,280,45,88,44,4,5,true,true};
const ScanoutBuffer memory[2]={{0xc0000000,1920*1080*4},{0xc1000000,1920*1080*4}};
bool begin(Presentation &p,Io &io){DpuResources r;r.inspect([&](unsigned off){return io.read(off);});assert(r.choose(mode.width));return p.begin(io,r,mode,memory,1920*4);}
int main(){unsigned cases=0;int source=1;
 for(unsigned failure=0;failure<9;failure++){
  Presentation p;Io io;ScanoutBuffer b[2]={memory[0],memory[1]};
  if(failure==0)b[1]=b[0];if(failure==1)b[1].address=UINT64_MAX-128;
  if(failure==2)b[1].bytes=1;if(failure==3)io.allowed=false;
  if(failure==4)io.fillOk=false;if(failure==5)io.cleanOk=false;
  if(failure==6)io.armOk=false;if(failure==7)io.videoOk=false;if(failure==8)io.running=false;
  DpuResources r;assert(r.choose(mode.width));assert(!p.begin(io,r,mode,b,1920*4));
  if(failure<4)assert(!io.fills&&!io.cleans);
  if(failure<6)assert(io.writes.empty()&&!p.dpu.active);
  if(failure>=6)assert(p.dpu.active);uint64_t cancelled=99;
  io.running=true;assert(p.stop(io,cancelled)&&!cancelled&&!p.dpu.active&&!p.pendingTag);cases++;
 }
 {Presentation p;Io io;assert(begin(p,io)&&p.ready&&p.current==0);
  DpuResources free;assert(free.choose(mode.width));assert(!p.begin(io,free,mode,memory,1920*4));
  assert(!p.offer(io,0,&source)&&!p.offer(io,1,nullptr));
  assert(p.offer(io,1,&source)&&p.current==0&&p.pendingTag==1&&p.next==1);
  assert(!p.offer(io,2,&source));io.tick+=99999;assert(!p.timedOut(io));
  io.tick++;assert(p.timedOut(io)&&p.pendingTag==1&&p.dpu.pending);
  auto frame=io.regs[0x350ac];assert(!p.frame(io,frame,io.tick)); // duplicate
  assert(!p.frame(io,frame-1,io.tick)); // queued stale IRQ
  // One real IRQ is still insufficient if the CTL flush is outstanding.
  io.regs[0x350ac]++;assert(!p.frame(io,io.regs[0x350ac],io.tick)&&p.pendingTag==1);
  io.latch(p);assert(p.frame(io,io.regs[0x350ac],io.tick)==1&&p.current==1&&!p.pendingTag);
  assert(!p.frame(io,io.regs[0x350ac],io.tick));
  assert(p.offer(io,2,nullptr,true)&&p.next==0);io.latch(p);
  assert(p.frame(io,io.regs[0x350ac],io.tick)==2&&p.current==0);uint64_t cancelled=99;
  assert(p.stop(io,cancelled)&&!cancelled&&begin(p,io));cases++;
 }
 // A failed transfer/cache clean/flush does not consume the request. A
 // lost authorization never touches either framebuffer or DPU register.
 for(unsigned failure=0;failure<5;failure++){
  Presentation p;Io io;assert(begin(p,io));
  if(failure==0)io.allowed=false;if(failure==1)io.copyOk=false;if(failure==2)io.cleanOk=false;
  if(failure==3)io.regs[p.dpu.resources.ctlBase[p.dpu.resources.ctl]+0x18]=p.dpu.flush;
  if(failure==4)io.fillOk=false;auto writes=io.writes.size();auto copies=io.copies;
  assert(!p.offer(io,9,&source,failure==4)&&!p.pendingTag&&io.writes.size()==writes);
  if(!failure)assert(io.copies==copies);uint64_t c;io.allowed=true;assert(p.stop(io,c));cases++;
 }
 // Callback drain, DPU stop or link stop timeout retains the pending
 // generation. Only a later successful stop returns it as cancellation.
 for(unsigned failure=0;failure<3;failure++){
  Presentation p;Io io;assert(begin(p,io)&&p.offer(io,42,&source));
  if(failure==0)io.drainOk=false;if(failure==1)io.running=false;if(failure==2)io.stopOk=false;
  uint64_t c=99;assert(!p.stop(io,c)&&!c&&!p.ready&&p.closing&&p.pendingTag==42&&p.buffers[0].address);
  assert(!p.offer(io,43,&source)&&!p.frame(io,99,io.tick));io.drainOk=io.running=io.stopOk=true;
  assert(p.stop(io,c)&&c==42&&!p.pendingTag&&!p.buffers[0].address);cases++;
 }
 // Counter wrap is a real advance; delayed pre-wrap callbacks are stale.
 {Presentation p;Io io;assert(begin(p,io));p.lastFrame=0xffffffff;io.regs[0x350ac]=0xffffffff;
  assert(p.offer(io,7,&source));io.latch(p);assert(!io.regs[0x350ac]);
  assert(p.frame(io,0,io.tick)==7&&!p.frame(io,0xffffffff,io.tick));cases++;}
 {Presentation p;Io io;assert(begin(p,io));
  for(uint64_t tag=1;tag<=10000;tag++){
   assert(p.offer(io,tag,&source));assert(p.current==unsigned(!(tag&1)));io.latch(p);
   assert(p.frame(io,io.regs[0x350ac],io.tick)==tag&&p.current==unsigned(tag&1));
  }cases++;}
 printf("PASS DP presentation %u scenarios, 10000 alternating flips, DMA rejection/real-latch/timeout-retention/counter-wrap ASanUBSan\n",cases);
}
'''
with tempfile.TemporaryDirectory(prefix='b5q-dp-presentation-')as td:
 t=Path(td);(t/'test.cpp').write_text(source)
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(R/'UniXNU-b5q/package'),str(t/'test.cpp'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test')],check=True)
