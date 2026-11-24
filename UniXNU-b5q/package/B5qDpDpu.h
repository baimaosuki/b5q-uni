/* SPDX-License-Identifier: GPL-2.0-only */
/* Original b5q catalog, sde_hw_ctl.c, sde_hw_lm.c, sde_hw_intf.c and
 * sde_hw_pingpong.c. Only the exclusively selected resources are written.
 * Firmware must separately qualify the scanout device-address aperture. */
#pragma once
#include "B5qDpDpuResources.h"
#include "B5qDpPlane.h"
#include "B5qDpTiming.h"
namespace B5qDp {
struct Dpu {
 DpuResources resources{};Plane planes[2]{};Mode mode{};
 uint32_t flush=0,fetch=0,pendingFrame=0;bool prepared=false,active=false,started=false,pending=false;
 struct Saved {uint32_t offset,value;};Saved saved[160]{};unsigned savedCount=0;
 static constexpr unsigned pipeFlush[DpuResources::pipes]={0,1,2,18,11,12,24,25,13,14};
 static constexpr unsigned mixerFlush[DpuResources::mixers]={6,7,8,9,10,20};
 bool make(const DpuResources &r,const Mode &m,uint64_t address,uint64_t bytes,unsigned stride){
  if(active)return false;
  *this={};
  if(!m.valid()||m.width>5120||r.dpBusy||r.ctl>=r.ctls||r.usedCtl[r.ctl]||
     r.count!=(m.width>2560?2u:1u))return false;
  unsigned x=0;
  for(unsigned i=0;i<r.count;i++){
   const unsigned lm=r.lm[i],p=r.pipe[i];
   if(lm>=r.mixers||p<4||p>=r.pipes||r.usedLm[lm]||r.usedPp[lm]||r.usedPipe[p])return false;
   if(i&&(lm!=r.lm[0]+1||(r.lm[0]&1)||p==r.pipe[0]||r.usedMerge[lm/2]))return false;
   const unsigned w=r.count==1?m.width:i?m.width-x:(m.width+1)/2;
   if(!planes[i].make(address,bytes,m.width,m.height,stride,x,w))return false;
   x+=w;fetch|=1u<<(p-4);flush|=(1u<<pipeFlush[p])|(1u<<mixerFlush[lm]);
  }
  if(r.count==2)flush|=1u<<23;
  flush|=1u<<31;resources=r;mode=m;prepared=true;return true;
 }
 // Caller holds the DPU resource/role lock. The fresh read-only ownership
 // check and DMA gate precede every write, including partial setup.
 template<class Io>bool apply(Io &io){
  if(!prepared||active||!io.dmaAllowed(planes[0].address,uint64_t(planes[0].stride)*mode.height))return false;
  DpuResources fresh;fresh.inspect([&](unsigned off){return io.read(off);});
  const auto &r=resources;
  if(fresh.dpBusy||fresh.usedCtl[r.ctl])return false;
  for(unsigned i=0;i<r.count;i++)
   if(fresh.usedLm[r.lm[i]]||fresh.usedPipe[r.pipe[i]]||fresh.usedPp[r.lm[i]]||
      (r.count==2&&fresh.usedMerge[r.lm[0]/2]))return false;
  const uint32_t ctl=r.ctlBase[r.ctl];
  // Each setup write below is to a free resource. Keep its prior state
  // so a successful disconnect can reuse the same resources, not leak one
  // CTL/LM/pipe at every hotplug. W1C/flush trigger registers aren't state.
  auto write=[&](unsigned off,uint32_t value){
   bool sideEffect=off==ctl+0x18||off==ctl+0x100||off==ctl+0x110;
   for(unsigned i=0;i<r.count;i++)sideEffect=sideEffect||off==r.pipeBase[r.pipe[i]]+0x138;
   if(!sideEffect){
    bool known=false;for(unsigned i=0;i<savedCount;i++)known=known||saved[i].offset==off;
    if(!known)saved[savedCount++]={off,io.read(off)};
   }
   io.write(off,value);
  };
  for(unsigned i=0;i<r.count;i++){
   const unsigned lm=r.lm[i],p=r.pipe[i];const uint32_t base=r.pipeBase[p],mix=r.lmBase[lm];
   planes[i].apply([&](unsigned off){return io.read(base+off);},[&](unsigned off,uint32_t v){write(base+off,v);});
   write(mix+4,(uint32_t(mode.height)<<16)|planes[i].width);
   const uint32_t old=io.read(mix);write(mix,(old&~(1u<<31))|(i?1u<<31:0u));
   // Base layer has no per-stage alpha/blend register.
   for(unsigned ext=0;ext<5;ext++)write(r.layer(r.ctl,lm,ext),ext==r.pipeExt[p]?1u<<r.pipeShift[p]:0);
  }
  if(r.count==2)write(r.mergeBase[r.lm[0]/2]+4,3); // BLEND_3D_H_ROW_INT: 1|((2-1)<<1).
  // INTF0 receives its left PP, with paired MERGE_3D enabled if needed.
  write(0x3525c,(io.read(0x3525c)&~15u)|r.lm[0]);
  IntfTiming timing;timing.make(mode,io.read(0x35004));
  timing.apply([&](unsigned off,uint32_t v){write(0x35000+off,v);});
  write(ctl+0x14,0xf0000000);write(ctl+0xec,0);write(ctl+0xf0,0);
  write(ctl+0xf4,1);write(ctl+0xf8,0);
  write(ctl+0xe4,r.count==2?1u<<(r.lm[0]/2):0);
  write(ctl+0x134,1);write(ctl+0xfc,fetch);
  if(r.count==2)write(ctl+0x100,1u<<(r.lm[0]/2));
  write(ctl+0x110,1);write(ctl+0x18,flush);io.barrier();active=true;return true;
 }
 // Original video encoder flushes CTL before enabling INTF timing. Read
 // the actual status/frame counter; no software tick proves first light.
 template<class Io>bool start(Io &io){
  if(!active||started||!io.dmaAllowed(planes[0].address,uint64_t(planes[0].stride)*mode.height))return false;
  const uint32_t frame=io.read(0x350ac);io.write(0x35000,1);io.barrier();started=true;
  for(unsigned us=0;us<80000;us+=100){
   if((io.read(0x3526c)&1)&&io.read(0x350ac)!=frame)return true;io.delay(100);
  }return false; // caller must quiesce; keep all DMA/resource ownership
 }
 template<class Io>bool flip(Io &io,uint64_t address,uint64_t bytes,unsigned stride){
  if(!active||!started||pending)return false;
  const auto &r=resources;const uint32_t ctl=r.ctlBase[r.ctl];
  if(io.read(ctl+0x18)&flush||!io.dmaAllowed(address,uint64_t(stride)*mode.height))return false;
  Plane next[2];unsigned x=0;uint32_t pipeMask=0;
  for(unsigned i=0;i<r.count;i++){
   if(!next[i].make(address,bytes,mode.width,mode.height,stride,x,planes[i].width))return false;
   x+=planes[i].width;pipeMask|=1u<<pipeFlush[r.pipe[i]];
  }
  for(unsigned i=0;i<r.count;i++){
   const uint32_t base=r.pipeBase[r.pipe[i]];
   io.write(base+0x14,next[i].address);io.write(base+0x24,next[i].stride);planes[i]=next[i];
  }
  pendingFrame=io.read(0x350ac);pending=true;io.write(ctl+0x18,pipeMask);io.barrier();return true;
 }
 template<class Io>bool latched(Io &io){
  if(!pending)return false;
  if(io.read(resources.ctlBase[resources.ctl]+0x18)&flush||io.read(0x350ac)==pendingFrame)return false;
  pending=false;return true;
 }
 // Native owner stops presentation/IRQ callbacks first, but retains the
 // DMA allocation and these mappings until this function returns true.
 template<class Io>bool quiesce(Io &io){
  if(!active)return true;
  const auto &r=resources;const uint32_t ctl=r.ctlBase[r.ctl];
  io.write(0x35000,0);io.barrier();bool idle=false;
  for(unsigned us=0;us<80000;us+=100){if(!(io.read(0x3526c)&1)){idle=true;break;}io.delay(100);}
  if(!idle)return false;
  io.write(ctl+0xfc,0);io.write(ctl+0xf4,0);io.write(ctl+0xe4,0);
  if(r.count==2)io.write(ctl+0x100,1u<<(r.lm[0]/2));
  io.write(ctl+0x110,1);io.write(ctl+0x18,flush);io.barrier();idle=false;
  for(unsigned us=0;us<80000;us+=100){if(!(io.read(ctl+0x18)&flush)){idle=true;break;}io.delay(100);}
  if(!idle)return false;
  while(savedCount){const auto v=saved[--savedCount];io.write(v.offset,v.value);}
  io.barrier();active=prepared=started=pending=false;return true;
 }
};
}
