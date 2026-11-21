// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>
#include "B5qQupClock.h"
#include "GeniI2c.h"
namespace B5qTouchClock {
// Samsung gcc-kalama.c: voted wrap1 branches; enable polls SE4's CBCR,
// not its RCG_CFG. SE4 CMD/CFG/DFS = 0x184f0/0x184f4/0x18504;
// USB's SE6 uses 0x18760/0x18764/0x18774, with CBCR 0x18754.
// clk-rcg2.c defines CFG at CMD+4 and SE_CMD_DFSR at CMD+0x14.
constexpr unsigned vote=0x52008, s4=0x184e4;
constexpr unsigned rcg=0x184f0, cfg=rcg+4, dfs=rcg+0x14;
constexpr unsigned halts[]={0x23294,0x23284,0x2327c,0x23280,s4};
constexpr uint32_t enables=(1u<<18)|(1u<<19)|(1u<<20)|(1u<<21)|(1u<<26);
// Samsung clk-rcg2.c: preserve DFS ownership and select an existing XO level
// through the engine's GENI_CLK_SEL. Only a non-DFS RCG may be reprogrammed.
template<class Read,class Write,class Delay>
bool xo(Read read,Write write,Delay delay,uint32_t &dfsState,unsigned &level,uint32_t &selectedCfg){
 uint32_t lastCfg=0;
 auto observedRead=[&](unsigned off){
  const uint32_t value=read(off);
  if(off==cfg || (off>=rcg+0x1c && off<rcg+0x3c))lastCfg=value;
  return value;
 };
 const bool ok=B5qQupClock::xo(observedRead,write,delay,rcg,level,dfsState);
 selectedCfg=ok?lastCfg:0;return ok;
}
template<class Read,class Write>
bool selectLevel(Read read,Write write,unsigned level,uint32_t &readback){
 readback=~0u;if(level>=8)return false;
 write(GENI_CLK_SEL,level);readback=read(GENI_CLK_SEL);return readback==level;
}
template<class Read,class Update,class Delay,class Observe>
bool enable(Read read,Update update,Delay delay,unsigned &failed,uint32_t &last,Observe observe) {
 // The vote is shared with USB and other QUP clients. The caller must use
 // sm8550_gcc_update32 so the entire RMW/readback holds the existing GCC lock.
 failed=vote;last=0; // No CBCR has been read if the locked update fails.
 if(!update(vote,0u,enables))return false;
 for(unsigned off:halts){
  const bool running=B5qQupClock::branch(read,delay,off,last);
  observe(off,last,running);
  if(!running){failed=off;return false;}
 }
 failed=0;return true;
}
template<class Read,class Update,class Delay>
bool enable(Read read,Update update,Delay delay,unsigned &failed,uint32_t &last) {
 return enable(read,update,delay,failed,last,[](unsigned,uint32_t,bool){});
}
}
