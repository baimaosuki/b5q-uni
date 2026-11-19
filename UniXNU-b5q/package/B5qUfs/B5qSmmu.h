// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>
// Queue must be quiescent. Only exact UFS SID and an unused bank can change.
template<class Read,class Write>
static bool b5qConfigureUfsStream(uint64_t dma,uint64_t dmaLength,Read read,Write write) {
 uint32_t idr0=read(0x20),idr1=read(0x24),idr2=read(0x28);
 unsigned groups=idr0&255,banks=idr1&255,pages=1U<<(((idr1>>28)&7)+1);
 if(!(idr0&(1U<<30))||!(idr2&(1U<<12))||(idr1>>31)||!groups||groups>128||banks<2||banks>128||pages>128||(pages+banks)*4096>0x100000)return false;
 const unsigned bits[]={32,36,40,42,44,48};for(unsigned shift=0;shift<=8;shift+=4){unsigned code=(idr2>>shift)&15;if(code>=6||dma>=(1ULL<<bits[code])||dmaLength>(1ULL<<bits[code])-dma)return false;}
 int slot=-1,freeSlot=-1;unsigned matches=0;
 for(unsigned i=0;i<groups;++i){uint32_t smr=read(0x800+4*i);if(!(smr>>31)){freeSlot=int(i);continue;}
  uint32_t mask=(smr>>16)&0x7fff;if(((smr^0x60U)&0xffff&~mask)==0){if(mask||++matches>1)return false;slot=int(i);}}
 if(slot<0)slot=freeSlot;if(slot<0)return false;
 int bank=-1;
 for(unsigned b=banks;b-->1;){bool used=false;for(unsigned i=0;i<groups;++i){uint32_t smr=read(0x800+4*i),s2=read(0xc00+4*i);if((smr>>31)&&((s2>>16)&3)==0&&(s2&255)==b)used=true;}if(!used&&read((pages+b)*4096)==0){bank=int(b);break;}}
 if(bank<0)return false;
 write(0x1000+4*unsigned(bank),0x10000);write(0x1800+4*unsigned(bank),1);
 if(read(0x1000+4*unsigned(bank))!=0x10000||read(0x1800+4*unsigned(bank))!=1)return false;
 // Invalidate the exact UFS mapping before atomically publishing its new bank.
 write(0x800+4*unsigned(slot),0);write(0xc00+4*unsigned(slot),unsigned(bank));write(0x800+4*unsigned(slot),0x80000060U);
 return read(0x800+4*unsigned(slot))==0x80000060U&&read(0xc00+4*unsigned(slot))==unsigned(bank);
}
