#!/usr/bin/env python3
"""Run the production complete link session against register-level sinks."""
from pathlib import Path
import subprocess,tempfile
R=Path(__file__).resolve().parents[2]
h=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <map>
#include <vector>
#include <utility>
#include <cstring>
#include "B5qDpSession.h"
using namespace B5qDp;
struct Io {
 std::map<std::pair<Block,unsigned>,uint32_t> regs;
 std::vector<uint8_t> fifo,reply,edid;std::vector<unsigned> trainedRates;
 uint64_t now=0,detachAt=~0ULL;unsigned segment=0,offset=0,rx=0,starts=0,rate=0;
 unsigned nackAt=0,dropAbove=0,slowUs=0,auxControl=0,powerAccesses=0;uint32_t auxState=0;
 uint8_t power=0xa2,revision=0x14;
 bool pending=false,online=true,clockFault=false,haltFault=false,pllFault=false,videoFault=false,eqOnly=false,corruptEdid=false;
 Io(){
  edid.resize(256);const uint8_t magic[]={0,255,255,255,255,255,255,0};memcpy(edid.data(),magic,8);
  edid[18]=1;edid[19]=4;edid[20]=128;edid[126]=1;
  edid[128]=2;edid[129]=3;edid[130]=7;edid[132]=0x42;edid[133]=97;edid[134]=16;
  for(unsigned b=0;b<2;b++){uint8_t sum=0;for(unsigned i=0;i<127;i++)sum+=edid[b*128+i];edid[b*128+127]=uint8_t(-sum);}
 }
 bool connected(){return online&&now<detachAt;}
 bool prepareRate(unsigned rate){assert(rate==6||rate==10||rate==20||rate==30);return true;}
 bool finishRates(){return true;}
 uint64_t nowUs(){return now;}void delay(unsigned us){now+=us;}
 static bool branch(unsigned off){return off==0x8058||off==0x8050||off==0x8048||off==0x8040;}
 uint32_t read(Block b,unsigned off){
  if(b==Block::Ahb&&off==0)return 0x10020003;
  if(b==Block::Ahb&&off==0x20)return pending?(nackAt==starts?auxNack:auxDone):0;
  if(b==Block::Aux&&off==0x30)return auxControl;
  if(b==Block::Aux&&off==0x38)return auxState;
  if(b==Block::Aux&&off==0x34){if(!rx++)return 0;unsigned i=rx-2;assert(i<reply.size());return(i<<16)|(uint32_t(reply[i])<<8);}
  if(b==Block::DispCc&&branch(off)){uint32_t v=regs[{b,off}];return (v&1)||haltFault?v&~(1u<<31):v|(1u<<31);}
  if(b==Block::DispCc&&(off==0x81bc||off==0x8170||off==0x818c))return clockFault?1:regs[{b,off}]&~1u;
  if(b==Block::Pll&&off==0x1f8)return pllFault?0:1;
  if(b==Block::Pll&&off==0x1d0)return pllFault?0:3;
  if(b==Block::Phy&&off==0xe4)return pllFault?0:3;
  if(b==Block::Link&&off==0x40){uint32_t p=regs[{b,4}];return p==128?(videoFault?0:1):p<<3;}
  return regs[{b,off}];
 }
 void write(Block b,unsigned off,uint32_t value){
  regs[{b,off}]=value;
  if(b==Block::DispCc&&branch(off)){
   // Parent rate/PLL must not be changed while an old link clock is live.
   regs[{b,off}]&=~(1u<<31);return;
  }
  if(b==Block::Ahb&&off==0x20){pending=false;return;}
  if(b==Block::Aux&&off==0x30){auxControl=value;return;}
  if(b==Block::Aux&&off==0x34){
   if(value==((1u<<31)|1u)){rx=0;return;}
   if(value&(1u<<31))fifo.clear();fifo.push_back(uint8_t(value>>8));return;
  }
  if(b!=Block::Aux||off!=0x38)return;
  auxState=value;if(!(value&(1u<<9)))return;
  assert(auxControl&1);starts++;now+=slowUs;pending=true;reply.clear();assert(fifo.size()>=4);
  const bool reading=fifo[0]&16,native=!(value&(1u<<8));
  const unsigned addr=(unsigned(fifo[0]&15)<<16)|(unsigned(fifo[1])<<8)|fifo[2],n=fifo[3]+1;
  if(native){
   if(reading){
    reply.resize(n);
    if(addr==0){assert(n==16);reply[0]=revision;reply[1]=20;reply[2]=4|128|64;reply[3]=128;}
    else if(addr==0x600){assert(n==1);powerAccesses++;reply[0]=power;}
    else{assert(addr==0x202&&n==6);const bool good=!dropAbove||rate<=dropAbove;
     reply[0]=reply[1]=good?0x77:eqOnly?0x11:0;reply[2]=good?1:0;}
   }else{
    assert(fifo.size()==n+4);
    if(addr==0x100){assert(n==2);rate=fifo[4];trainedRates.push_back(rate);}
    else if(addr==0x600){assert(n==1);power=fifo[4];powerAccesses++;}
    else assert(addr==0x102||addr==0x103||addr==0x107||addr==0x108);
   }
  }else if(reading){
   assert(addr==0x50&&n==16&&segment*256+offset+n<=edid.size());
   for(unsigned i=0;i<n;i++)reply.push_back(edid[segment*256+offset+i]^(corruptEdid&&offset==16&&i==1?1:0));
   offset+=n;if(!(value&(1u<<11)))offset=0;
  }else{
   assert(n==1&&fifo.size()==5);if(addr==0x30)segment=fifo[4];else{assert(addr==0x50);offset=fifo[4];}
  }
 }
};
int main(){unsigned cases=0;
 for(unsigned route:{2,4})for(bool reverse:{false,true}){
  Io io;Session<Io> s(io);assert(s.discover(route,reverse)&&s.auxOn&&s.modes.count==2&&s.edidBytes==256);
  assert(io.power==0xa1&&s.sinkPowered);
  assert(s.train()&&s.trained&&!s.streaming&&s.lanes==route&&s.selected.width==(route==4?3840:1920));
  assert(s.video()&&s.streaming);assert(s.stop()&&!s.auxOn&&!s.clocksOwned&&!s.streaming);
  assert(io.power==0xa2&&!s.sinkPowered);
  assert(!(io.read(Block::Aux,0x30)&1));
  for(unsigned off:{0x8058,0x8050,0x8048,0x8040})assert(!(io.read(Block::DispCc,off)&1));
  assert(s.discover(route,!reverse)&&s.train());assert(s.stop());cases++;
 }
 for(bool eq:{false,true}){
  // A sink whose fast rate fails must fall back to its advertised 1080p
  // mode, instead of giving up after trying the preferred 4K mode once.
  Io io;io.dropAbove=10;io.eqOnly=eq;Session<Io> s(io);assert(s.discover(4,false));
  assert(s.train()&&s.selected.width==1920&&s.rate==10&&s.attempts>=3);assert(s.stop());cases++;
 }
 for(unsigned failure=1;failure<=35;failure++){
  Io io;io.nackAt=failure;Session<Io>s(io);bool ok=s.discover(4,false);
  assert(!ok&&!s.trained&&!s.streaming&&!s.auxOn&&!s.clocksOwned);assert(s.error==LinkError::Caps||s.error==LinkError::Edid||s.error==LinkError::Power);cases++;
 }
 {Io io;io.corruptEdid=true;Session<Io>s(io);assert(!s.discover(4,false)&&s.error==LinkError::Edid&&!s.auxOn);cases++;}
 {Io io;io.online=false;Session<Io>s(io);assert(!s.discover(4,false)&&s.error==LinkError::Detached&&io.regs.empty());cases++;}
 {Io io;Session<Io>s(io);assert(!s.discover(1,false)&&s.error==LinkError::Caps&&io.regs.empty());cases++;}
 {Io io;io.clockFault=true;Session<Io>s(io);assert(!s.discover(4,false)&&s.error==LinkError::Clock&&!s.streaming);cases++;}
 {Io io;Session<Io>s(io);assert(s.discover(4,false));io.pllFault=true;assert(!s.train()&&s.error==LinkError::Training&&!s.auxOn);cases++;}
 {Io io;Session<Io>s(io);assert(s.discover(4,false)&&s.train());io.videoFault=true;
  assert(!s.video()&&s.error==LinkError::Stream&&!s.trained&&!s.streaming&&!s.auxOn);cases++;}
 {Io io;Session<Io>s(io);assert(s.discover(4,false));io.detachAt=io.now+100;
  assert(!s.train()&&s.error==LinkError::Detached&&!s.trained&&!s.auxOn);cases++;}
 {Io io;Session<Io>s(io);assert(s.discover(4,false));io.dropAbove=1;io.slowUs=300000;
  const uint64_t start=io.now;assert(!s.train()&&s.error==LinkError::Timeout&&!s.auxOn);
  assert(io.now-start<=6500000);cases++;}
 {Io io;Session<Io>s(io);assert(!s.train()&&s.error==LinkError::Caps);assert(!s.video()&&!s.streaming);cases++;}
 {Io io;io.revision=0x10;Session<Io>s(io);assert(s.discover(4,false)&&s.train()&&s.stop()&&!io.powerAccesses);cases++;}
 {Io io;Session<Io>s(io);assert(s.discover(4,false)&&s.train());io.nackAt=io.starts+1;
  assert(!s.stop()&&!s.clocksOwned&&!s.auxOn&&!s.sinkPowered);io.nackAt=0;
  assert(s.discover(4,false)&&s.train()&&s.stop());cases++;}
 {Io io;Session<Io>s(io);assert(s.discover(4,false)&&s.train());io.haltFault=true;
  assert(!s.stop()&&s.clocksOwned&&!s.trained&&!s.streaming);
  assert(!s.discover(4,false)&&s.error==LinkError::Clock&&s.clocksOwned);
  io.haltFault=false;assert(s.stop()&&!s.clocksOwned&&!s.auxOn);cases++;}
 printf("PASS production DP session %u full AUX/EDID/PHY/clock/training/modefallback/video/detach/failure/teardown/deadline cases ASanUBSan\n",cases);
}
'''
with tempfile.TemporaryDirectory(prefix='b5q-dp-session-')as td:
 t=Path(td);(t/'test.cpp').write_text(h)
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-Wno-sign-compare','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(R/'UniXNU-b5q/package'),str(t/'test.cpp'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test')],check=True)
