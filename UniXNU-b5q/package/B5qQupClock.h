// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>
namespace B5qQupClock {
// Samsung gcc-kalama.c HWCG bit 1 and clk-branch.c: an idle hardware-gated
// AHB branch may report CLK_OFF despite the vote. Never clear HW_CTL to poll it.
template<class Read,class Delay>
bool branch(Read read,Delay delay,unsigned off,uint32_t &last){
 for(unsigned poll=0;poll<2000;++poll){
  last=read(off);
  if((last&(1u<<1)) || !(last&(1u<<31)))return true;
  delay(10);
 }
 return false;
}
// Samsung clk-rcg2.c: DFS enable at CMD+14, eight CFG levels at CMD+1c+4*i.
// With DFS enabled the SE's CLK_SEL owns performance selection: do not write
// DFS or the live RCG. The caller writes/validates the returned level at SE+7c.
// Dedicated QUP I2C hub S8 uses ordinary clk_rcg2_ops, not DEFINE_RCG_DFS;
// pass dfsCapable=false and never read a fictitious hub DFS/table register.
template<class Read,class Write,class Delay>
bool xo(Read read,Write write,Delay delay,unsigned rcg,unsigned &level,uint32_t &dfsValue,bool dfsCapable=true){
 level=8;dfsValue=dfsCapable?read(rcg+0x14):0;
 if(dfsValue&1u){
  for(unsigned i=0;i<8;++i){
   const uint32_t cfg=read(rcg+0x1c+4*i);
   if(((cfg>>8)&7u)==0 && (cfg&31u)<=1u){level=i;return true;}
  }
  return false;
 }
 write(rcg+4,(read(rcg+4)&~0x371fu)|1u);
 write(rcg,read(rcg)|1u);
 for(unsigned poll=0;poll<2000;++poll){
  if(!(read(rcg)&1u)){
   if((read(rcg+4)&0x371fu)!=1u)return false;
   level=0;return true;
  }
  delay(10);
 }
 return false;
}
}
