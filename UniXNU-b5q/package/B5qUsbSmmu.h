// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>
namespace B5qUsbSmmu {
struct Plan {unsigned slot=0,bank=0,pages=0;uint32_t cbar=0;};
inline bool freeCbar(uint32_t cbar) {
 const unsigned type=(cbar>>16)&3,vmid=cbar&255;
 return type==0 || type==2 || (type==1 && vmid==255);
}
// HALIOMMUDxe a6020ff8, allocator RVA21a0: CBAR records are its
// allocation metadata. Never inspect occupied S2CRs or context registers.
template<class Read> bool plan(Read read,Plan &out) {
 const uint32_t id0=read(0x20),id1=read(0x24);
 const unsigned groups=id0&255,banks=id1&255,pages=1u<<(((id1>>28)&7)+1);
 if((id1>>31)||!groups||groups>128||banks<2||banks>128||pages>128||(pages+banks)*4096u>0xd0000)return false;
 unsigned slot=~0u;
 // Slot zero is never ours, even if its SMR is invalid.
 for(unsigned i=0;i<groups;++i){
  const uint32_t smr=read(0x800+4*i);
  if(!(smr&0x80000000u)){if(i && slot==~0u)slot=i;continue;}
  const uint32_t mask=(smr>>16)&0x7fff;
  // Refuse an existing exact or masked USB route rather than replace it.
  if(!((smr^0x40u)&0xffffu&~mask))return false;
 }
 if(slot==~0u)return false;
 for(unsigned b=banks-1;b-->0;){
  const uint32_t cbar=read(0x1000+4*b);
  if(freeCbar(cbar)){out={slot,b,pages,cbar};return true;}
 }
 return false;
}
// Configure only the selected unallocated bank; publish the match last.
template<class Read,class Write,class Barrier,class Delay>
bool install(Read read,Write write,Barrier barrier,Delay delay,const Plan &p,uint64_t pa){
 if(!p.slot || !pa || (pa&4095) || (pa>>40) ||
    (read(0x800+4*p.slot)&0x80000000u) || read(0x1000+4*p.bank)!=p.cbar || !freeCbar(p.cbar))return false;
 const unsigned cb=(p.pages+p.bank)*4096;
 write(0x1800+4*p.bank,1);write(0x1000+4*p.bank,0x1f300);
 write(cb,0);write(cb+0x10,2u|(7u<<15));write(cb+0x30,28u|(1u<<8)|(1u<<10)|(3u<<12)|(1u<<23));
 write(cb+0x20,uint32_t(pa));write(cb+0x24,uint32_t(pa>>32));write(cb+0x28,0);write(cb+0x2c,0);
 write(cb+0x38,0xff);write(cb+0x3c,0);barrier();write(cb+0x610,0);write(cb+0x7f0,0);barrier();
 unsigned poll=0;for(;poll<1000 && (read(cb+0x7f4)&1);++poll)delay(10);
 if(poll==1000)return false;
 write(cb+0x58,read(cb+0x58));write(cb,0x1027);barrier();
 if(read(cb)!=0x1027 || read(cb+0x38)!=0xff || read(cb+0x20)!=uint32_t(pa) ||
    read(cb+0x24)!=uint32_t(pa>>32) || read(0x1000+4*p.bank)!=0x1f300 ||read(0x1800+4*p.bank)!=1)return false;
 write(0xc00+4*p.slot,p.bank);barrier();
 if(read(0xc00+4*p.slot)!=p.bank)return false;
 write(0x800+4*p.slot,0x80000040);barrier();
 return read(0x800+4*p.slot)==0x80000040;
}
}
