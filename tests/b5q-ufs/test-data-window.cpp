#include <cassert>
#include <cstring>
#include <cstdio>
#include <climits>
#include <initializer_list>
#include <mutex>
#include <thread>
#include <atomic>
#include "B5qDataFormat.h"
using namespace B5qData;
static void le(uint8_t *p,uint64_t v,unsigned bytes=8){for(unsigned i=0;i<bytes;++i)p[i]=uint8_t(v>>(i*8));}
static void seal(uint8_t *p){le(p+4092,crc32(p,4092),4);}
static void config(uint8_t *p,const Identity &id){
 memset(p,0,4096);memcpy(p,"B5QDATA1",8);le(p+8,1,4);le(p+12,id.mode,4);le(p+16,4096,4);
 le(p+24,id.first);le(p+32,id.last);le(p+40,id.first+headerBlocks);le(p+48,id.last-id.first+1-headerBlocks);
 le(p+56,rootTotal);memcpy(p+64,rootHeaderSha,32);memcpy(p+96,id.disk,16);memcpy(p+112,id.partition,16);memcpy(p+128,expectedVolumeUuid,16);p[144]=8;seal(p);
}
int main(){
 Identity id;id.first=tailFirst;id.last=lastLba;id.mode=tailMode;id.disk[0]=1;id.partition[0]=2;
 alignas(16) uint8_t h[4096];config(h,id);Volume v;
 assert(open(h,id,lastLba+1000,v));assert(v.first==tailFirst+256 && v.blocks==7864064);
 uint64_t absoluteLba=0;assert(absolute(v,0,1,absoluteLba)&&absoluteLba==tailFirst+256);
 assert(absolute(v,v.blocks-1,1,absoluteLba)&&absoluteLba==lastLba);
 assert(!absolute(v,v.blocks,1,absoluteLba));assert(!absolute(v,UINT64_MAX,1,absoluteLba));
 assert(!absolute(v,0,UINT64_MAX,absoluteLba));assert(!absolute(v,0,0,absoluteLba));
 assert(!absolute(v,v.blocks-1,2,absoluteLba));
 for(unsigned at: {0U,8U,12U,16U,20U,24U,32U,40U,48U,56U,64U,96U,112U,128U,144U,160U,4092U}) {
  uint8_t bad[4096];memcpy(bad,h,4096);bad[at]^=1;assert(!open(bad,id,lastLba+1000,v));
 }
 for(unsigned at:{0U,8U,12U,16U,20U,24U,32U,40U,48U,56U,64U,96U,112U,160U}) {
  uint8_t bad[4096];memcpy(bad,h,4096);bad[at]^=1;seal(bad);assert(!open(bad,id,lastLba+1000,v));
 }
 assert(open(h,id,lastLba+1000,v));
 alignas(16) uint32_t utrd[8]={};alignas(16) uint8_t ucd[2048]={};
 for(auto dir:{Direction::Read,Direction::Write,Direction::Sync}) {
  bool sync=dir==Direction::Sync;
  assert(request(utrd,ucd,0x8d0000000,0,v,dir,0,sync?0:1));assert(ucd[3]==1);
  if(sync){assert(ucd[16]==0x35);for(unsigned i=17;i<32;++i)assert(!ucd[i]);}
  else{assert(be32(ucd+18)==v.first && ucd[24]==1);assert(ucd[16]==(dir==Direction::Read?0x28:0x2a));}
 }
 assert(!request(utrd,ucd,0x8d0000000,1,v,Direction::Write,0,1));
 assert(!request(utrd,ucd,0x8d0000000,0,v,Direction::Write,0,1,0));
 assert(!request(utrd,ucd,0x8d0000000,0,v,Direction::Write,0,33));
 assert(!request(utrd,ucd,0x8d0000000,0,v,Direction(77),0,1));
 assert(!request(utrd,ucd,0x8d0000000,0,v,Direction::Sync,1,0));
 assert(!request(utrd,ucd,0x8d0000000,0,v,Direction::Sync,0,1));
 assert(!request(utrd,ucd,0x8d0000000,0,v,Direction::Write,UINT64_MAX,1));
 id.first=firstLba;assert(!validIdentity(id,lastLba+1000));id.first=tailFirst;
 assert((tailFirst-firstLba)*4096-rootTotal>=guardBytes);
 puts("PASS production Data config CRC/GPT UUID/root hash/bounds gates; LBA0 maps only to Data; first/last/-1/+1/count overflow; tag1/LUN0/direction/FUA/SYNC10; root+guard nonoverlap");
}
