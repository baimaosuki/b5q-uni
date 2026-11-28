/* SPDX-License-Identifier: GPL-2.0-only */
#pragma once
#include <stdint.h>
#include <stddef.h>
#include "B5qDpCta.h"
namespace B5qDp {
struct Mode {
 uint32_t pixelKHz=0;uint16_t width=0,height=0,hBlank=0,vBlank=0,hFront=0,hSync=0,vFront=0,vSync=0;
 bool hPositive=false,vPositive=false;
 uint32_t totalWidth()const{return uint32_t(width)+hBlank;}
 uint32_t totalHeight()const{return uint32_t(height)+vBlank;}
 bool valid()const {
  return pixelKHz>=10000&&pixelKHz<=675000&&width>=320&&width<=7680&&height>=200&&height<=4320&&
   hBlank&&vBlank&&hFront&&vFront&&hSync&&vSync&&uint32_t(hFront)+hSync<=hBlank&&uint32_t(vFront)+vSync<=vBlank&&
   totalWidth()<=8191&&totalHeight()<=8191;
 }
 uint32_t refreshMilliHz()const{return valid()?uint32_t(uint64_t(pixelKHz)*1000000/(uint64_t(totalWidth())*totalHeight())):0;}
 bool fits(unsigned lanes,unsigned bandwidthCode)const {
  if(!valid()||(lanes!=1&&lanes!=2&&lanes!=4)||(bandwidthCode!=6&&bandwidthCode!=10&&bandwidthCode!=20&&bandwidthCode!=30))return false;
  // 8b/10b transport,24bitRGB; retain3%linkheadroom for blanking/TU.
  return uint64_t(pixelKHz)*24*103<=uint64_t(lanes)*bandwidthCode*270000*8/10*100;
 }
};
struct Modes {
 static constexpr unsigned capacity=32;Mode values[capacity]{};unsigned count=0;uint8_t extensions=0;
 bool add(const Mode &mode){
  if(!mode.valid())return false;
  for(unsigned i=0;i<count;i++)if(values[i].pixelKHz==mode.pixelKHz&&values[i].width==mode.width&&values[i].height==mode.height&&values[i].hBlank==mode.hBlank&&values[i].vBlank==mode.vBlank)return true;
  if(count==capacity)return false;values[count++]=mode;return true;
 }
 // EDID1.x detailedtiming18B packing. Interlaced/non-digital/ambiguoussync
 // modes are not silently converted into guessed progressive timings.
 bool detailed(const uint8_t *d){
  const uint32_t clock=uint32_t(d[0]|uint16_t(d[1])<<8)*10;if(!clock)return true;
  if((d[17]&0x80)||(d[17]&0x18)!=0x18)return false;
  Mode m;m.pixelKHz=clock;m.width=d[2]|uint16_t(d[4]&0xf0)<<4;m.hBlank=d[3]|uint16_t(d[4]&15)<<8;
  m.height=d[5]|uint16_t(d[7]&0xf0)<<4;m.vBlank=d[6]|uint16_t(d[7]&15)<<8;
  m.hFront=d[8]|uint16_t(d[11]&0xc0)<<2;m.hSync=d[9]|uint16_t(d[11]&0x30)<<4;
  m.vFront=(d[10]>>4)|uint16_t(d[11]&0x0c)<<2;m.vSync=(d[10]&15)|uint16_t(d[11]&3)<<4;
  m.hPositive=d[17]&2;m.vPositive=d[17]&4;return add(m);
 }
 bool advertisedVic(uint8_t vic){
  for(const auto &v:ctaTimings)if(v.vic==vic){
   Mode m;m.pixelKHz=v.pixelKHz;m.width=v.width;m.height=v.height;m.hBlank=v.hBlank;m.vBlank=v.vBlank;
   m.hFront=v.hFront;m.hSync=v.hSync;m.vFront=v.vFront;m.vSync=v.vSync;m.hPositive=v.hPositive;m.vPositive=v.vPositive;
   return add(m);
  }return false;
 }
 bool parse(const uint8_t *data,size_t bytes){
  *this={};static const uint8_t magic[]={0,255,255,255,255,255,255,0};
  if(!data||bytes<128||bytes%128||bytes>1024)return false;
  for(unsigned i=0;i<8;i++)if(data[i]!=magic[i])return false;
  if(data[18]!=1||data[19]>4||!(data[20]&0x80)||size_t(data[126]+1)*128!=bytes)return false;
  for(size_t at=0;at<bytes;at+=128){uint8_t sum=0;for(unsigned i=0;i<128;i++)sum+=data[at+i];if(sum)return false;}
  extensions=data[126];
  for(unsigned at=54;at+18<=126;at+=18)detailed(data+at);
  for(unsigned block=1;block<=extensions;block++){
   const uint8_t *e=data+block*128;if(e[0]!=2)continue;
   const unsigned dtd=e[2];if(dtd==0)continue;if(dtd<4||dtd>127){*this={};return false;}
   // All CTA datablocks must end before its detailedtiming area.
   for(unsigned at=4;at<dtd;){const unsigned next=at+1+(e[at]&31);if(next>dtd){*this={};return false;}
    // Only normal Video Data Block entries advertise RGB modes. A VIC in
    // the YCbCr420-only extended block cannot be offered by this RGB driver.
    if((e[at]>>5)==2)for(unsigned i=at+1;i<next;i++)advertisedVic(e[i]&127);
    at=next;
   }
   for(unsigned at=dtd;at+18<=127;at+=18)detailed(e+at);
  }
  return count!=0;
 }
 const Mode *best(unsigned lanes,unsigned maxRate)const{
  const Mode *result=nullptr;uint64_t score=0;
  for(unsigned i=0;i<count;i++){const auto &m=values[i];if(!m.fits(lanes,maxRate))continue;
   const uint64_t current=uint64_t(m.width)*m.height*1000+m.refreshMilliHz();if(current>score){result=&m;score=current;}}
  return result;
 }
 // 64-byte row alignment and 4KiB slot alignment; both scanout buffers
 // must fit entirely in the validated stock splash tail.
 static uint32_t scanoutStride(const Mode &mode){return (uint32_t(mode.width)*4+63)&~63u;}
 static uint64_t scanoutSlot(const Mode &mode){return (uint64_t(scanoutStride(mode))*mode.height+4095)&~4095ULL;}
 unsigned fitPool(uint64_t bytes){
  unsigned kept=0;for(unsigned i=0;i<count;i++)if(values[i].width<=5120&&scanoutSlot(values[i])<=bytes/2)values[kept++]=values[i];
  count=kept;return kept;
 }
};
}
