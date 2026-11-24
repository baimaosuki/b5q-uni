/* SPDX-License-Identifier: GPL-2.0-only */
/* Samsung dispcc-kalama.c / clk-rcg2.c479..536,1714..1771. */
#pragma once
#include <stdint.h>
#include "B5qDpAux.h"
namespace B5qDp {
struct Ratio {
 uint32_t m=0,n=0;
 bool make(uint32_t output,uint32_t input){
  m=n=0;if(!output||!input||output>input)return false;
  uint32_t a=output,b=input;while(b){const uint32_t r=a%b;a=b;b=r;}
  m=output/a;n=input/a;if(m>65535||n>65535){m=n=0;return false;}return true;
 }
};
template<class Io>struct Clock {
 Io &io;uint32_t last=0;unsigned failed=0;
 explicit Clock(Io &owner):io(owner){}
 bool update(unsigned off,uint32_t cfg,const Ratio *ratio=nullptr){
  constexpr uint32_t mask=31|(7u<<8)|(3u<<12)|(1u<<20);
  if(ratio&&ratio->m!=ratio->n){
   const uint32_t diff=ratio->n-ratio->m;uint32_t d=ratio->n;
   if(d<ratio->m)d=ratio->m;if(d>2*diff)d=2*diff;
   io.write(Block::DispCc,off+8,ratio->m);io.write(Block::DispCc,off+12,(~diff)&65535);io.write(Block::DispCc,off+16,(~d)&65535);cfg|=2u<<12;
  }
  io.write(Block::DispCc,off+4,(io.read(Block::DispCc,off+4)&~mask)|(cfg&mask));
  io.write(Block::DispCc,off,io.read(Block::DispCc,off)|1);
  for(unsigned us=0;us<1000;us+=10){last=io.read(Block::DispCc,off);if(!(last&1))return true;io.delay(10);}failed=off;return false;
 }
 bool branch(unsigned off){
  io.write(Block::DispCc,off,io.read(Block::DispCc,off)|1);
  for(unsigned us=0;us<1000;us+=10){last=io.read(Block::DispCc,off);if(!(last&(1u<<31)))return true;io.delay(10);}failed=off;return false;
 }
 bool aux(){return update(0x81bc,1)&&branch(0x8058);}
 bool link(){return update(0x8170,0x101)&&branch(0x8040)&&branch(0x8048);}
 bool pixel(uint32_t pixelKHz,unsigned rate){
  if(rate!=6&&rate!=10&&rate!=20&&rate!=30)return false;Ratio ratio;
  // The DT pixel_parent is DP0_PHY_PLL_VCO_DIV_CLK (parent-map4 cfg2),
  // not the lower link-symbol clock. Samsung 4nm sets VCO/div to
  // 810MHz for RBR and1350MHz for HBR/HBR2/HBR3.
  if(!ratio.make(pixelKHz,rate==6?810000u:1350000u))return false;
  return update(0x818c,0x201,&ratio)&&branch(0x8050);
 }
};
}
