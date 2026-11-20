// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "B5qPeripheralHardware.h"
#include <stddef.h>

namespace B5qUsbPolicy {
// A firmware-owned handoff, not an assertion inferred from a DT SID or a flag
// on the kernel command line. No producer is claimed in the current firmware.
struct Handoff {
 uint64_t magic;
 uint32_t version,sid,flags,reserved;
 uint64_t physical,bytes;
};
constexpr uint64_t magic=0x31414d4455513542ULL; // B5QUDMA1
enum { Powered=1,PhyReady=2,IdentityVerified=4 };
inline bool accepts(const void *data,size_t length,uint64_t physical,uint64_t bytes) {
 if(!data || length!=sizeof(Handoff) || !bytes || bytes>UINT64_MAX-physical)return false;
 Handoff copy;__builtin_memcpy(&copy,data,sizeof(copy));const Handoff *h=&copy;
 return h->magic==magic && h->version==1 && h->sid==B5qHardware::usbSid &&
   h->flags==(Powered|PhyReady|IdentityVerified) && !h->reserved && h->bytes &&
   h->bytes<=UINT64_MAX-h->physical && h->physical<=physical &&
   physical-h->physical<=h->bytes && bytes<=h->bytes-(physical-h->physical);
}
// Qualcomm DWC3 host programming only. Caller must first prove clocks/PHY and
// DMA ownership. Never maps or changes apps_smmu, RPMh, GPIO or Type-C policy.
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
