// SPDX-License-Identifier: BSD-2-Clause-Patent
// TouchComm wire facts from pinned Samsung synaptics_reg/interrupt/fn sources.
#pragma once
#include <stdint.h>
#include <stddef.h>
namespace B5qTouch {
struct Point{uint16_t x,y;uint8_t kind;};
struct DeltaStats { unsigned palm=0,invalid=0; };
inline void releaseAll(Point out[12]) {for(unsigned i=0;i<12;++i)out[i]={};}
inline unsigned hid(unsigned value){return (value>4095?4095:value)*32767u/4095u;}
inline bool bits(const uint8_t *p,size_t n,unsigned &offset,unsigned width,uint32_t &value){
 if(!width||width>32||offset>n*8||width>n*8-offset)return false;
 value=0;for(unsigned i=0;i<width;++i)value|=uint32_t((p[(offset+i)/8]>>((offset+i)%8))&1)<<i;offset+=width;return true;
}
inline bool appInfo(const uint8_t *data,size_t n,unsigned &objects) {
 // synaptics_ts_application_info, 16-byte customer_config_id; max_objects+36.
 if(!data||n<38||data[2]||data[3])return false;
 unsigned count=unsigned(data[36])|(unsigned(data[37])<<8);
 if(!count||count>12)return false;objects=count;return true;
}
inline bool parse(const uint8_t *cfg,size_t cn,const uint8_t *data,size_t n,Point out[12],unsigned maximum) {
 if(!cfg||!data||!out||!cn||cn>512||n>4096||!maximum||maximum>12)return false;
 Point pending[12]={};
 unsigned bit=0,id=0,loop=0,iteration=0,objects=0,active=0;
 bool looping=false,activeOnly=false,activeKnown=false;
 for(unsigned ip=0,steps=0;ip<cn&&steps<8192;++steps) {
  unsigned op=cfg[ip++];if(op==0){if(looping)return false;for(unsigned i=0;i<12;++i)out[i]=pending[i];return true;}
  if(op==1||op==2){if(looping)return false;loop=ip;looping=true;activeOnly=op==1;iteration=0;id=0;objects=activeOnly&&activeKnown?active:maximum;
   if(!objects||(activeOnly&&!activeKnown&&bit==n*8)){
    bool end=false;
    while(ip<cn){unsigned skip=cfg[ip++];if(skip==3){end=true;break;}if(skip<4)return false;if(skip!=4){if(ip>=cn)return false;++ip;}}
    if(!end)return false;looping=false;
   }continue;}
  if(op==3){if(!looping)return false;++iteration;
   if(iteration<objects&&(!activeOnly||activeKnown||bit<n*8)){ip=loop;id=iteration;}else looping=false;continue;}
  if(op==4){bit=(bit+7)&~7u;if(bit>n*8)return false;continue;}
  if(ip>=cn)return false;unsigned width=cfg[ip++];uint32_t v=0;
  bool known=op==0x18||op==6||op==7||op==8||op==9;
  if(known){if(!bits(data,n,bit,width,v))return false;}
  else {if(!width||bit>n*8||width>n*8-bit)return false;bit+=width;continue;}
  if(op==0x18){if(v>maximum)return false;active=v;activeKnown=true;}
  else if(op==6){if(v>=maximum)return false;id=v;}
  else if(op==7){if(id>=maximum||v>255)return false;pending[id].kind=uint8_t(v);}
  else if(op==8){if(id>=maximum||v>4095)return false;pending[id].x=uint16_t(v);}
  else if(op==9){if(id>=maximum||v>4095)return false;pending[id].y=uint16_t(v);}
 }
 return false;
}
// Samsung C1 events are deltas, 16 bytes per contact. Keep other active IDs.
inline bool sec(const uint8_t *data,size_t n,Point out[12],DeltaStats *stats=nullptr) {
 if(!data||!out||!n||n>4096||n%16)return false;
 Point pending[12];for(unsigned i=0;i<12;++i)pending[i]=out[i];
 for (size_t at = 0; at < n; at += 16) {
  const uint8_t *p = data + at;
  const unsigned id = (p[0] >> 2) & 15;
  const unsigned action = p[0] >> 6;
  // Samsung synaptics_ts_irq_thread+0x170 and sec_common_fn+0x8874:
  // wire IDs are zero-based and only 0..9 are valid. A corrupt ID makes
  // the frame unusable; the report owner then releases every slot.
  if (id >= 10) return false;
  if (action == 0) {pending[id]={};continue;}
  if (action == 3) {
   pending[id] = {};
   continue;
  }
  const unsigned type = ((p[6] >> 6) << 2) | (p[7] >> 6);
  // Original mask 0x69 includes ttype5 with a separate palm flag
  // (irq_thread 0x9e14..0x9e4c). A desktop pointer must lift that palm.
  // Preserve original normal/glove/wet types 0,3,6, without stale slots.
  if (type==5) {pending[id]={};if(stats)++stats->palm;continue;}
  if ((0x49u & (1u << type)) == 0) {
   pending[id]={};if(stats)++stats->invalid;continue;
  }
  pending[id] = {uint16_t((p[1] << 4) | (p[3] >> 4)), uint16_t((p[2] << 4) | (p[3] & 15)), 1};
 }
 for(unsigned i=0;i<12;++i)out[i]=pending[i];
 return true;
}
template<class Read> bool continuation(Read read,uint8_t *out,unsigned length) {
 if(!out||length>4096)return false;if(!length)return true;
 unsigned at=0,remaining=length+1;uint8_t chunk[258];
 while(remaining){unsigned n=remaining>256?256:remaining;
  // Samsung V1 supplies the sole final padding byte locally.
  if(n==1)break;
  if(!read(chunk,n+2)||chunk[0]!=0xa5||chunk[1]!=3)return false;
  unsigned take=n;if(take>length-at)take=length-at;
  for(unsigned i=0;i<take;++i)out[at+i]=chunk[i+2];at+=take;remaining-=n;
  if(!remaining&&n>take&&chunk[n+1]!=0x5a)return false;
 }
 return at==length;
}
}
