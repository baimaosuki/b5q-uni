// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>
namespace B5qDisplay {
inline bool supported(unsigned angle){return angle==0||angle==90||angle==270;}
inline void toPhysical(unsigned x,unsigned y,unsigned w,unsigned h,unsigned angle,unsigned &px,unsigned &py){
 px=angle==90?y:angle==270?h-1-y:x;py=angle==90?w-1-x:angle==270?x:y;
}
inline void fromPhysical(unsigned x,unsigned y,unsigned pw,unsigned ph,unsigned angle,unsigned &lx,unsigned &ly){
 lx=angle==90?ph-1-y:angle==270?y:x;ly=angle==90?x:angle==270?pw-1-x:y;
}
inline bool dimensions(unsigned pw,unsigned ph,unsigned lw,unsigned lh,unsigned angle){return supported(angle)&&lw==(angle?ph:pw)&&lh==(angle?pw:ph);}
// CoreDisplay/SkyLight scale-resolutions entries are CFData, big-endian
// width/height plus the HiDPI flag word. Backing size stays native.
inline void hidpiMode(unsigned w,unsigned h,uint8_t (&out)[12]){
 const unsigned words[3]={w,h,1u};
 for(unsigned n=0;n<3;n++)for(unsigned b=0;b<4;b++)out[n*4+b]=uint8_t(words[n]>>(24-8*b));
}
template<class Pixel>bool copy(volatile void *dst,uint64_t db,uint64_t ds,const void *src,uint64_t sb,uint64_t ss,unsigned w,unsigned h,unsigned angle,unsigned bpp,Pixel pixel){
 if(!supported(angle)||!dst||!src||!w||!h||w>16384||h>16384||(uintptr_t(dst)&3)||ds&3||ss<uint64_t(w)*bpp||ss>UINT64_MAX/h||sb<ss*h)return false;
 const unsigned pw=angle?h:w,ph=angle?w:h;
 if(ds<uint64_t(pw)*4||ds>UINT64_MAX/ph||db<ds*ph)return false;
 for(unsigned y=0;y<h;y++)for(unsigned x=0;x<w;x++){
  unsigned px,py;toPhysical(x,y,w,h,angle,px,py);
  const uint8_t *p=static_cast<const uint8_t*>(src)+uint64_t(y)*ss+uint64_t(x)*bpp;
  auto *out=reinterpret_cast<volatile uint32_t*>(static_cast<volatile uint8_t*>(dst)+uint64_t(py)*ds);
  out[px]=pixel(p);
 }
 return true;
}
}
