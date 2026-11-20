// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "B5qPeripheralHardware.h"
#include "AdrenoFirmware.h"
namespace B5qGmu {
// gen7_gmu_vma and GEN7_GMU_CM3_{I,D}TCM_START from the pinned
// Samsung SM8550 graphics-kernel reference, not Sheng register tables.
constexpr AdrenoFirmwareRegion regions[]={{0,0x4000,0},{0x4000,0xffc000,1},{0x10004000,0x4000,2}};
inline bool plan(const uint8_t *firmware,size_t bytes,AdrenoFirmwareBlock blocks[32],size_t &count) {
 return AdrenoFirmwarePlanGmu(firmware,bytes,regions,3,blocks,32,&count)==AdrenoFirmwareSuccess;
}
template<class Write,class Copy,class Barrier>
bool load(const uint8_t *firmware,size_t bytes,uint64_t cacheBytes,bool owned,
          Write write,Copy copy,Barrier barrier) {
 AdrenoFirmwareBlock blocks[32];size_t count=0;
 if(!owned || !firmware || !plan(firmware,bytes,blocks,count))return false;
 // Prove every destination before making the first MMIO or RAM store.
 for(size_t i=0;i<count;++i) {
  const auto &b=blocks[i];if(!b.bytes)continue;
  if(b.region_identifier==1) {
   if(b.address<0x4000 || b.address-0x4000>cacheBytes || b.bytes>cacheBytes-(b.address-0x4000))return false;
  } else {
   const uint64_t origin=b.region_identifier==0?0x1b400ULL*4:0x1c400ULL*4;
   const uint64_t delta=b.address-(b.region_identifier==0?0:0x10004000);
   const uint64_t absolute=B5qHardware::gpuBase+origin+delta;
   if(absolute<B5qHardware::gmuBase || absolute-B5qHardware::gmuBase>B5qHardware::gmuBytes ||
      b.bytes>B5qHardware::gmuBytes-(absolute-B5qHardware::gmuBase))return false;
  }
 }
 for(size_t i=0;i<count;++i) {
  const auto &b=blocks[i];if(!b.bytes)continue;const uint8_t *data=firmware+b.payload_offset;
  if(b.region_identifier==1) {if(!copy(b.address-0x4000,data,b.bytes))return false;}
  else {
   const uint64_t origin=b.region_identifier==0?0x1b400ULL*4:0x1c400ULL*4;
   uint32_t at=uint32_t(B5qHardware::gpuBase+origin+b.address-(b.region_identifier==0?0:0x10004000)-B5qHardware::gmuBase);
   for(uint32_t n=0;n<b.bytes;n+=4) {
    uint32_t value=uint32_t(data[n])|uint32_t(data[n+1])<<8|uint32_t(data[n+2])<<16|uint32_t(data[n+3])<<24;
    if(!write(at+n,value))return false;
   }
  }
 }
 barrier();return true;
}
}
