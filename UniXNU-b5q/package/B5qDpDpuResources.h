/* SPDX-License-Identifier: GPL-2.0-only */
/* Original b5q DT catalog and Samsung sde_hw_ctl.c stage register layout.
 * Conservative resource discovery only; this does not establish DMA access. */
#pragma once
#include <stdint.h>
namespace B5qDp {
struct DpuResources {
 static constexpr unsigned ctls=6,mixers=6,pipes=10;
 static constexpr uint32_t ctlBase[ctls]={0x16000,0x17000,0x18000,0x19000,0x1a000,0x1b000};
 static constexpr uint32_t lmBase[mixers]={0x45000,0x46000,0x47000,0x48000,0x49000,0x4a000};
 static constexpr uint32_t pipeBase[pipes]={0x5000,0x7000,0x9000,0xb000,0x25000,0x27000,0x29000,0x2b000,0x2d000,0x2f000};
 static constexpr uint32_t mergeBase[3]={0x4f000,0x50000,0x51000};
 static constexpr uint32_t layerOffsets[5]={0,0x40,0x70,0xa0,0xb8};
 static constexpr unsigned pipeExt[pipes]={0,0,0,0,0,0,2,2,4,4};
 static constexpr unsigned pipeShift[pipes]={0,3,6,26,18,21,0,4,0,4};
 static constexpr unsigned pipeBits[pipes]={3,3,3,3,3,3,4,4,4,4};
 static constexpr unsigned rect1Ext[pipes]={3,3,3,3,2,2,2,2,4,4};
 static constexpr unsigned rect1Shift[pipes]={0,4,8,12,8,12,16,20,8,12};
 bool usedCtl[ctls]{},usedLm[mixers]{},usedPipe[pipes]{},usedPp[mixers]{},usedMerge[3]{};bool dpBusy=false;
 unsigned ctl=ctls,lm[2]={mixers,mixers},pipe[2]={pipes,pipes},count=0;
 static uint32_t layer(unsigned c,unsigned m,unsigned e){
  return ctlBase[c]+(e?layerOffsets[e]+m*4:m==5?0x24:m*4);
 }
 template<class Read>void inspect(Read read){
  *this={};dpBusy=(read(0x35000)&1)!=0; // DP INTF0, not either DSI interface.
  uint32_t activeInterfaces=0;
  for(unsigned c=0;c<ctls;c++){
   const uint32_t active=read(ctlBase[c]+0xf4),fetch=read(ctlBase[c]+0xfc);
   usedCtl[c]=active||fetch||read(ctlBase[c]+0x14)||read(ctlBase[c]+0x64)||read(ctlBase[c]+0x18);
   activeInterfaces|=active;
   const uint32_t merge=read(ctlBase[c]+0xe4);
   usedCtl[c]=usedCtl[c]||merge;
   for(unsigned m=0;m<3;m++)usedMerge[m]=usedMerge[m]||bool(merge&(1u<<m));
   if(active&1)dpBusy=true;
   for(unsigned p=0;p<pipes;p++)usedPipe[p]=usedPipe[p]||bool(fetch&(1u<<(p<4?16+p:p-4)));
   for(unsigned m=0;m<mixers;m++){
    uint32_t values[5];bool routed=false;
    for(unsigned e=0;e<5;e++){values[e]=read(layer(c,m,e));routed=routed||values[e];}
    usedCtl[c]=usedCtl[c]||routed;usedLm[m]=usedLm[m]||routed;
    for(unsigned p=0;p<pipes;p++){
     const uint32_t mask=(1u<<pipeBits[p])-1;
     const bool solo=(values[pipeExt[p]]>>pipeShift[p])&mask;
     const bool rect1=(values[rect1Ext[p]]>>rect1Shift[p])&15;
     // Missing stage MSB in EXT1 for VIG0..3 and DMA0/1.
     const bool high=p<4?(values[1]&(1u<<(2*p))):p<6?(values[1]&(1u<<(16+2*(p-4)))):false;
     usedPipe[p]=usedPipe[p]||solo||rect1||high;
    }
   }
  }
  // Retained nonzero source/mixer configuration is treated as reserved,
  // even when not currently routed. Do not recycle firmware state silently.
  for(unsigned m=0;m<mixers;m++)usedLm[m]=usedLm[m]||read(lmBase[m]+4);
  for(unsigned p=0;p<pipes;p++)usedPipe[p]=usedPipe[p]||read(pipeBase[p])||read(pipeBase[p]+0x16c);
  // LM->PP is fixed by original catalog parser; each pair feeds one
  // MERGE_3D. An active interface can own its PP even with no layer yet.
  for(unsigned i=0;i<4;i++)if((activeInterfaces&(1u<<i))||(read(0x35000+i*0x1000)&1)){
   const unsigned pp=read(0x3525c+i*0x1000)&15;
   if(pp<mixers)usedPp[pp]=true;
  }
  for(unsigned m=0;m<3;m++){
   usedMerge[m]=usedMerge[m]||read(mergeBase[m]+4);
   if(usedMerge[m])usedPp[2*m]=usedPp[2*m+1]=true;
  }
  for(unsigned m=0;m<mixers;m++)usedLm[m]=usedLm[m]||usedPp[m];
 }
 bool choose(unsigned width){
  ctl=ctls;lm[0]=lm[1]=mixers;pipe[0]=pipe[1]=pipes;count=0;
  if(dpBusy||!width||width>5120)return false;
  const unsigned needed=width>2560?2:1;
  for(unsigned c=ctls;c--;)if(!usedCtl[c]){ctl=c;break;}
  if(ctl==ctls)return false;
  if(needed==2){
   for(unsigned m=mixers;m>=2;m-=2)if(!usedLm[m-2]&&!usedLm[m-1]&&!usedMerge[(m-2)/2]){lm[0]=m-2;lm[1]=m-1;break;}
  }else for(unsigned m=mixers;m--;)if(!usedLm[m]){lm[0]=m;break;}
  if(lm[0]==mixers)return false;
  unsigned found=0;for(unsigned p=pipes;p-->4&&found<needed;)if(!usedPipe[p])pipe[found++]=p;
  if(found!=needed)return false;count=needed;return true;
 }
};
}
