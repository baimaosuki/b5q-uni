// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "B5qRootFormat.h"
#include "B5qUfsProtocol.h"
namespace B5qData {
using namespace B5qFormat;
constexpr uint64_t sector=4096,guardBytes=256ULL<<20,rootTotal=17603493888ULL;
constexpr uint64_t tailFirst=lastLba+1-(30ULL<<30)/sector;
constexpr uint64_t headerBlocks=256; // immutable 1 MiB initialization envelope
constexpr uint32_t tailMode=1,partitionMode=2,userdataMode=3;
// User-authorized macOS-only reuse; GPT name and bounds stay unchanged.
constexpr uint64_t userdataFirst=3406336,userdataLast=47595510;
static const uint8_t rootHeaderSha[32]={0xd9,0x3a,0x00,0xb5,0x89,0xd6,0x4b,0x7e,0x07,0x57,0xaa,0x40,0x28,0x8a,0xaa,0x92,0x7a,0x53,0x64,0x38,0x2e,0xc5,0xa0,0xdd,0x08,0xfa,0xa3,0x62,0x9d,0x9a,0x7d,0x8b};
static const uint8_t expectedVolumeUuid[16]={0x15,0x52,0xcf,0xee,0x78,0xff,0x48,0xd8,0x8a,0x6c,0x69,0x4b,0x86,0x7d,0x61,0xac};
struct Identity { uint64_t first=0,last=0;uint8_t disk[16]={},partition[16]={};uint32_t mode=0; };
struct Volume {uint64_t first=0,blocks=0;uint8_t uuid[16]={},container[16]={};bool valid=false;};
inline bool nonzero(const uint8_t *p,unsigned n){uint8_t v=0;while(n--)v|=*p++;return v!=0;}
inline bool validIdentity(const Identity &id,uint64_t capacity) {
 if(!nonzero(id.disk,16)||!nonzero(id.partition,16)||id.last>=capacity||id.last>UINT32_MAX||id.last<=id.first||id.last-id.first+1<=headerBlocks)return false;
 if(id.mode==tailMode)return id.first==tailFirst && id.last==lastLba &&
  id.first-firstLba>=(rootTotal+guardBytes)/sector;
 if(id.mode==userdataMode)return id.first==userdataFirst && id.last==userdataLast;
 if(id.mode!=partitionMode || id.first<265 || (id.first<=lastLba && firstLba<=id.last))return false;
 // GPT overlap and protected-name checks must precede construction of Identity.
 return true;
}
inline bool partitionName(const uint8_t *entry,const char *name) {
 unsigned i=0;for(;name[i];++i)if(i>=35 || entry[56+2*i]!=uint8_t(name[i]) || entry[57+2*i])return false;
 return !entry[56+2*i] && !entry[57+2*i];
}
inline bool selectMode(const uint8_t *h,const uint8_t *table,const Gpt &g,uint32_t mode,
                   uint64_t capacity,Identity &out) {
 out={};if(mode!=tailMode && mode!=partitionMode && mode!=userdataMode)return false;
 if(!target(table,g))return false;
 const bool separate=mode!=tailMode;
 const char *name=mode==userdataMode?"userdata":separate?"macosdata":"macosroot";
 unsigned found=0,index=0;
 for(unsigned i=0;i<g.count;++i) {
  const uint8_t *e=table+size_t(i)*g.stride;
  if(!nonzero(e,16)||!partitionName(e,name))continue;
  if(++found!=1 || !nonzero(e+16,16))return false;
  index=i;out.first=separate?le64(e+32):tailFirst;out.last=le64(e+40);
  out.mode=mode;
  for(unsigned j=0;j<16;++j) {out.disk[j]=h[56+j];out.partition[j]=e[16+j];}
 }
 if(found!=1 || !validIdentity(out,capacity) || out.first<le64(h+40) || out.last>le64(h+48))return false;
 if(separate)for(unsigned i=0;i<g.count;++i) {
  if(i==index)continue;const uint8_t *e=table+size_t(i)*g.stride;if(!nonzero(e,16))continue;
  if(equal(e+16,out.partition,16) || (le64(e+32)<=out.last && out.first<=le64(e+40)))return false;
 }
 return true;
}
inline bool select(const uint8_t *h,const uint8_t *table,const Gpt &g,bool separate,
                   uint64_t capacity,Identity &out) {
 return selectMode(h,table,g,separate?partitionMode:tailMode,capacity,out);
}
inline bool open(const uint8_t h[4096],const Identity &id,uint64_t capacity,Volume &v) {
 v={};
 if(!validIdentity(id,capacity)||!equal(h,"B5QDATA1",8)||le32(h+8)!=1||le32(h+12)!=id.mode||
    le32(h+16)!=4096||le32(h+20)!=0||le64(h+24)!=id.first||le64(h+32)!=id.last||
    le64(h+40)!=id.first+headerBlocks||le64(h+48)!=id.last-id.first+1-headerBlocks||
    le64(h+56)!=rootTotal||!equal(h+64,rootHeaderSha,32)||!equal(h+96,id.disk,16)||
    !equal(h+112,id.partition,16)||!equal(h+128,expectedVolumeUuid,16)||!nonzero(h+144,16)||
    crc32(h,4092)!=le32(h+4092))return false;
 for(unsigned i=160;i<4092;++i)if(h[i])return false;
 v.first=id.first+headerBlocks;v.blocks=id.last-v.first+1;for(unsigned i=0;i<16;++i){v.uuid[i]=h[128+i];v.container[i]=h[144+i];}v.valid=true;return true;
}
inline bool absolute(const Volume &v,uint64_t block,uint64_t count,uint64_t &lba) {
 if(!v.valid||!count||block>=v.blocks||count>v.blocks-block||v.first>UINT32_MAX||block>UINT32_MAX-v.first)return false;
 lba=v.first+block;
 return count-1<=UINT32_MAX-lba;
}
enum class Direction {Read,Write,Sync};
inline bool request(uint32_t *utrd,uint8_t *ucd,uint64_t dma,uint8_t lun,
 const Volume &v,Direction direction,uint64_t block,uint32_t count,unsigned slot=1) {
 using namespace B5qUfsProtocol;
 if(lun!=0 || !v.valid || slot!=1)return false;
 if(direction!=Direction::Read && direction!=Direction::Write && direction!=Direction::Sync)return false;
 uint64_t lba=0;uint32_t bytes=0;
 if(direction==Direction::Sync) {if(block||count)return false;}
 else if(!count || count>32 || !absolute(v,block,count,lba))return false;
 else bytes=count*4096;
 uint8_t cdb[16]={};cdb[0]=direction==Direction::Sync?0x35:direction==Direction::Write?0x2a:0x28;
 if(bytes) {cdb[1]=direction==Direction::Write?8:0;putBe32(cdb+2,uint32_t(lba));cdb[7]=count>>8;cdb[8]=count;}
 descriptor(utrd,dma,bytes);
 if(direction==Direction::Write)utrd[0]=(utrd[0]&~(3U<<25))|(1U<<25);
 ucd[0]=1;ucd[1]=bytes?(direction==Direction::Write?0x20:0x40):0;ucd[2]=lun;ucd[3]=uint8_t(slot);
 putBe32(ucd+12,bytes);for(unsigned i=0;i<16;++i)ucd[16+i]=cdb[i];
 if(bytes) {auto *prd=reinterpret_cast<uint32_t*>(ucd+prdOffset);prd[0]=uint32_t(dma+dataOffset);prd[1]=uint32_t((dma+dataOffset)>>32);prd[3]=bytes-1;}
 return true;
}
}
