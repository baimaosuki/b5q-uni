/* SPDX-License-Identifier: GPL-2.0-only */
/* Samsung sde_hw_sspp.c: linear, unscaled, solo DMA pipe path.
 * BGRA bytes are DRM ARGB8888 on little-endian SM8550. This describes
 * register writes only; it neither allocates a pipe nor authorizes DMA. */
#pragma once
#include <stdint.h>
namespace B5qDp {
struct Plane {
 uint32_t address=0,stride=0,width=0,height=0,x=0;
 // The caller supplies an already qualified device-address allocation.
 // Check the entire strided image, not only the last visible crop.
 bool make(uint64_t deviceAddress,uint64_t allocationBytes,unsigned imageWidth,
           unsigned imageHeight,unsigned pitch,unsigned cropX,unsigned cropWidth){
  *this={};
  if(!imageWidth||imageWidth>5120||!imageHeight||imageHeight>0x3fff||
     !cropWidth||cropWidth>2560||cropX>imageWidth||cropWidth>imageWidth-cropX||
     pitch<imageWidth*4||pitch>65535||(pitch&3)||(deviceAddress&3)||!deviceAddress)return false;
  const uint64_t bytes=uint64_t(pitch)*imageHeight;
  if(bytes>allocationBytes||deviceAddress>0x100000000ULL-bytes)return false;
  address=uint32_t(deviceAddress);stride=pitch;width=cropWidth;height=imageHeight;x=cropX;return true;
 }
 template<class Read,class Write>bool apply(Read read,Write write)const{
  if(!address||!width||!height)return false;
  // sde_hw_sspp_update_multirect(SDE_SSPP_RECT_SOLO).
  write(0x170,0);
  // sde_hw_sspp_setup_format(DRM_FORMAT_ARGB8888), no rotation/UBWC.
  const uint32_t op=(read(0x38)&~((1u<<13)|(1u<<14)|1u|(1u<<31)))|(1u<<31);
  write(0x30,0x237ff);write(0x34,0x03020001);write(0x38,op);write(0x138,1u<<31);
  // sde_hw_sspp_setup_rects: right-hand source crop still uses the full
  // image stride, but the destination coordinates are local to its LM.
  const uint32_t size=(height<<16)|width;
  write(0,size);write(8,x);write(0xc,size);write(0x10,0);
  write(0x24,stride);write(0x28,0);write(0xb4,0);
  // No edge fetch/repetition or scaling: all color components share ROI.
  constexpr unsigned pixelExt[]={0x100,0x110,0x120};
  for(unsigned offset:pixelExt){
   write(offset,0);write(offset+4,0);write(offset+8,size);
  }
  // Solo layout, one plane; clear the other three addresses explicitly.
  write(0x14,address);write(0x18,0);write(0x1c,0);write(0x20,0);
  // sde_hw_sspp_setup_secure(SOLO,false); preserve non-plane bits.
  write(0x70,read(0x70)&~15u);
  // DT cdp-setting[RT]={read=1,write=1}, linear RGB preload64.
  write(0x134,9);return true;
 }
};
}
