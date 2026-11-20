// Execute actual USB handoff/host sequence and Samsung GMU loader on fixtures.
#include "B5qUsbPolicy.h"
#include "B5qGmuLoad.h"
#include "NativeAdrenoSha256.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <vector>
#include <map>
#include <string>
int main(int argc,char **argv) {
 assert(argc==2);
 assert(B5qUsbPolicy::validRam(0x8c0004000,0x80000000));
 assert(!B5qUsbPolicy::validRam(0,0x80000000));
 assert(!B5qUsbPolicy::validRam(0x8c0004001,0x80000000));
 assert(!B5qUsbPolicy::validRam(0x8c0004000,4097));
 assert(!B5qUsbPolicy::validRam(UINT64_MAX-1,8));
 {
  std::map<unsigned,unsigned> registers={{0x39004,0},{0x50018,0},{0x3902c,0},{0x39030,0},{0x39044,0},{0x39048,0},
    {0x39088,0},{0x39018,0},{0x3908c,0},{0x39024,0},{0x39028,0}};
  unsigned delays=0;
  auto read=[&](unsigned off,unsigned &v){v=registers[off];return true;};
  auto write=[&](unsigned off,unsigned v){registers[off]=(off==0x3902c||off==0x39044)?(v&~1u):v;if(off==0x39004||off==0x50018)registers[off]|=1u<<31;return true;};
  assert(!B5qUsbPolicy::clocks(read,write,[&](unsigned us){assert(us==100);++delays;}));
  assert(delays<=2000);
  // A domain which never powers on must stop before any PHY/core access.
  delays=0;registers[0x39004]=0;unsigned writes=0;
  auto stuckWrite=[&](unsigned off,unsigned v){assert(off==0x39004);registers[off]=v;++writes;return true;};
  assert(std::string(B5qUsbPolicy::clocks(read,stuckWrite,[&](unsigned us){assert(us==100);++delays;}))=="gcc-domain-timeout");
  assert(delays==1000 && writes==1);
 }
 for(std::string mode: {"ok","identity","device-timeout","halt-timeout","reset-timeout","register-fault","32-bit-only"}) {
  std::map<unsigned,unsigned> registers={{0xc120,0x55333330},{0xc110,0x2000},{0xc704,0},{0xc70c,1U<<22},{0,0x1000020},{0x10,1},{0x20,0},{0x24,1}};
  if(mode=="identity")registers[0xc120]=0;
  if(mode=="device-timeout"){registers[0xc704]=1U<<31;registers[0xc70c]=0;}
  if(mode=="halt-timeout")registers[0x24]=0;
  if(mode=="32-bit-only")registers[0x10]=0;
  unsigned writes=0,delays=0;bool reset=false;
  auto read=[&](unsigned off,unsigned &v){assert(off<B5qHardware::usbBytes);if(mode=="register-fault")return false;
   v=registers[off];if(off==0x20 && reset && mode!="reset-timeout")v&=~2U;return true;};
  auto write=[&](unsigned off,unsigned v){assert(off<B5qHardware::usbBytes);++writes;registers[off]=v;if(off==0x20&&(v&2U))reset=true;return true;};
  const char *why=B5qUsbPolicy::prepare(read,write,[&](unsigned us){assert(us==100);++delays;});
  assert((why==nullptr)==(mode=="ok"));assert(delays<=500);
  if(mode=="identity" || mode=="register-fault")assert(writes==0);
 }
 FILE *f=fopen(argv[1],"rb");assert(f);std::vector<uint8_t> image(66844);assert(fread(image.data(),1,image.size(),f)==image.size());fclose(f);
 uint8_t hash[32];NativeAdrenoSha256::hash(image.data(),image.size(),hash);assert(!memcmp(hash,B5qHardware::gmuFirmwareSha256,32));
 AdrenoFirmwareBlock plan[32];size_t count=0;assert(B5qGmu::plan(image.data(),image.size(),plan,count)&&count==15);
 std::vector<uint8_t> mmio(B5qHardware::gmuBytes,0xcc),cache(0xffc000,0xcc);unsigned writes=0,copies=0,barriers=0;
 auto write=[&](uint32_t off,uint32_t v){assert(off%4==0 && off+4<=mmio.size());memcpy(mmio.data()+off,&v,4);++writes;return true;};
 auto copy=[&](uint32_t off,const uint8_t *p,uint32_t n){assert(off+n<=cache.size());memcpy(cache.data()+off,p,n);++copies;return true;};
 auto barrier=[&](){++barriers;};
 assert(!B5qGmu::load(image.data(),image.size(),cache.size(),false,write,copy,barrier));
 assert(!B5qGmu::load(image.data(),image.size(),1,true,write,copy,barrier));
 assert(!B5qGmu::load(image.data(),image.size()-1,cache.size(),true,write,copy,barrier));assert(writes==0&&copies==0&&barriers==0);
 assert(B5qGmu::load(image.data(),image.size(),cache.size(),true,write,copy,barrier));
 assert(writes==135&&copies==1&&barriers==1);
 for(size_t i=0;i<count;++i){auto &b=plan[i];if(!b.bytes)continue;
  if(b.region_identifier==1)assert(!memcmp(cache.data()+b.address-0x4000,image.data()+b.payload_offset,b.bytes));
  else {uint64_t origin=b.region_identifier==0?0x1b400ULL*4:0x1c400ULL*4;
   uint64_t off=B5qHardware::gpuBase+origin+b.address-(b.region_identifier==0?0:0x10004000)-B5qHardware::gmuBase;
   assert(!memcmp(mmio.data()+off,image.data()+b.payload_offset,b.bytes));}
 }
 image[512]^=1;NativeAdrenoSha256::hash(image.data(),image.size(),hash);assert(memcmp(hash,B5qHardware::gmuFirmwareSha256,32));
 puts("PASS USB RAM input/clock timeouts/host reset bounds and actual Samsung GMU firmware plan/load/hash controls; no device I/O");
}
