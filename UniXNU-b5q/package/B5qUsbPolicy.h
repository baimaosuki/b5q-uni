// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "B5qPeripheralHardware.h"
#include <stddef.h>

namespace B5qUsbPolicy {
// Warm controller takeover reuses the Samsung firmware DMA environment.
// boot_args RAM is diagnostic input, not proof of a particular SMMU mapping.
inline bool validRam(uint64_t physical,uint64_t bytes) {
 return physical && bytes && !(physical&4095) && !(bytes&4095) && bytes<=UINT64_MAX-physical;
}
// Verified SM8550 GCC RCG/GDSC/branch operations. Does not reset core/PHY or
// touch a shared SMMU context; all waits are finite.
template<class Read,class Write,class Delay>
const char *clocks(Read read,Write write,Delay delay) {
 auto wait=[&](unsigned off,uint32_t mask,uint32_t expected,unsigned polls=1000) {
  for(unsigned i=0;i<polls;++i){uint32_t v=0;if(!read(off,v))return false;
   if((v&mask)==expected)return true;delay(100);}return false;
 };
 const unsigned domains[]={0x39004,0x50018};
 for(unsigned off:domains) {
  uint32_t v=0;if(!read(off,v))return "gcc-domain-read";
  if(!(v&(1u<<31))) {
   if(!write(off,(v&~1u)|(1u<<11)) || !wait(off,1u<<31,1u<<31))return "gcc-domain-timeout";
  }
 }
 const uint32_t roots[2][2]={{0x3902c,0x105},{0x39044,0}};
 for(const auto &root:roots) {
  uint32_t cfg=0,cmd=0;if(!read(root[0]+4,cfg))return "gcc-root-read";
  if((cfg&0x71f)!=root[1]) {
   if(!write(root[0]+4,(cfg&~0x71fu)|root[1]) || !read(root[0],cmd) ||
      !write(root[0],cmd|1u) || !wait(root[0],1,0,100))return "gcc-root-timeout";
  }
 }
 const unsigned branches[]={0x39088,0x39018,0x3908c,0x39024,0x39028};
 for(unsigned off:branches) {
  uint32_t v=0;if(!read(off,v) || !write(off,v|1u) || !wait(off,1u<<31,0))return "gcc-branch-timeout";
 }
 return nullptr;
}
// Warm DWC3 host programming after clocks are available. Preserve the
// bootloader PHY state; no apps_smmu, RPMh, GPIO or Type-C policy changes.
template<class Read,class Write,class Delay>
const char *prepare(Read read,Write write,Delay delay) {
 uint32_t id=0,gctl=0,cap=0,status=0,command=0;
 if(!read(0xc120,id) || (id&0xffff0000U)!=0x55330000U)return "core-identity";
 if(!read(0xc110,gctl))return "global-control";
 // Stop the previous device-side engine before changing role; its old event
 // buffers must not continue DMA while the native host owns the controller.
 uint32_t dctl=0;
 if(!read(0xc704,dctl))return "device-control";
 if(dctl&(1U<<31)) {
  if(!write(0xc704,dctl&~(1U<<31)))return "device-stop";
  bool stopped=false;
  for(unsigned i=0;i<500;++i){uint32_t s=0;if(!read(0xc70c,s))return "device-status";
   if(s&(1U<<22)){stopped=true;break;}delay(100);}
  if(!stopped)return "device-stop-timeout";
 }
 if(!write(0xc110,(gctl&~(3U<<12))|(1U<<12)))return "host-role";
 uint32_t phy2=0,phy3=0;
 if(!read(0xc200,phy2) || !write(0xc200,phy2&~((1u<<6)|(1u<<8))) ||
    !read(0xc2c0,phy3) || !write(0xc2c0,phy3&~(1u<<17)))return "PHY-unsuspend";
 if(!read(0,cap) || (cap&255)<0x20 || (cap&255)>0x80 || (cap&3))return "cap-length";
 uint32_t capability=0;
 if(!read(0x10,capability) || !(capability&1U))return "64-bit-DMA-unavailable";
 const uint32_t op=cap&255;
 if(!read(op,command) || !write(op,command&~1U))return "host-stop";
 bool halted=false;
 for(unsigned i=0;i<500;++i){if(!read(op+4,status))return "host-status";
  if(status&1U){halted=true;break;}delay(100);}
 if(!halted)return "host-stop-timeout";
 if(!write(op,(command&~1U)|2U))return "host-reset";
 for(unsigned i=0;i<500;++i){if(!read(op,command)||!read(op+4,status))return "host-reset-status";
  if(!(command&2U) && !(status&(1U<<11)))return nullptr;delay(100);}
 return "host-reset-timeout";
}
}
