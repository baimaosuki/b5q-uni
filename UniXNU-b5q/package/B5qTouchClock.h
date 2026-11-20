// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>
namespace B5qTouchClock {
// Samsung gcc-kalama.c: voted wrap1 branches; SE4 RCG_CFG is 0x184f4,
// NOT its CBCR. No register from SE4 is read by this clock helper.
constexpr unsigned vote=0x52008, s4=0x184e4;
constexpr unsigned halts[]={0x23294,0x23284,0x2327c,0x23280,s4};
constexpr uint32_t enables=(1u<<18)|(1u<<19)|(1u<<20)|(1u<<21)|(1u<<26);
template<class Read,class Write,class Delay>
bool enable(Read read,Write write,Delay delay,unsigned &failed,uint32_t &last) {
 write(vote,read(vote)|enables);
 for(unsigned off:halts){
  bool running=false;
  for(unsigned poll=0;poll<2000;++poll){last=read(off);if(!(last&(1u<<31))){running=true;break;}delay(10);}
  if(!running){failed=off;return false;}
 }
 failed=0;return true;
}
}
