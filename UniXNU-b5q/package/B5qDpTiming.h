/* SPDX-License-Identifier: GPL-2.0-only */
/* Samsung sde_encoder_phys_vid.c75..145 + sde_hw_intf.c268..425.
 * RGB888, progressive, no DSC/widebus. Does not allocate a DPU resource or
 * authorize DMA: the caller must own the interface before applying writes. */
#pragma once
#include "B5qDpModes.h"
namespace B5qDp {
struct IntfTiming {
 struct Register {uint16_t offset;uint32_t value;};
 Register regs[20]{};unsigned count=0;
 bool make(const Mode &m,uint32_t oldConfig){
  count=0;if(!m.valid())return false;
  const uint32_t ht=m.totalWidth(),vt=m.totalHeight();
  // Samsung shifts DP to bottom-right: add front to back, then front=0.
  // The pixel/link MSA retains the original EDID front/back porches.
  const uint32_t hs=m.hBlank,vs=m.vBlank;
  const uint32_t vstart=vs*ht+hs,vend=vt*ht-1;
  auto add=[&](unsigned off,uint32_t value){regs[count++]={uint16_t(off),value};};
  add(0x08,(ht<<16)|m.hSync);add(0x0c,vt*ht);add(0x14,uint32_t(m.vSync)*ht);
  add(0x3c,((ht-1)<<16)|hs);add(0x1c,vstart);add(0x24,vend);
  add(0x40,((ht-1)<<16)|hs);add(0x2c,vstart);add(0x34,vstart+uint32_t(m.height)*ht-1);
  add(0x44,0);add(0x48,0xff);add(0x4c,0);
  add(0x50,uint32_t(!m.hPositive)|(uint32_t(!m.vPositive)<<1));add(0xa8,3);
  add(0x04,oldConfig|(1u<<29)|(1u<<30));
  // COLOR_8BIT=3 for G/B/R; RGB component order is set in the SSPP.
  add(0x90,0x213f);add(0x60,1u<<4);
  add(0x64,((ht-1)<<16)|hs);add(0x68,0);return true;
 }
 template<class Write>void apply(Write write)const{
  for(unsigned i=0;i<count;i++)write(regs[i].offset,regs[i].value);
 }
};
}
