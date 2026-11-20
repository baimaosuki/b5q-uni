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
 B5qUsbPolicy::Handoff h={B5qUsbPolicy::magic,1,0x40,7,0,0x8c0000000,0x100000000};
 assert(B5qUsbPolicy::accepts(&h,sizeof(h),0x8c0004000,0x80000000));
 assert(!B5qUsbPolicy::accepts(nullptr,sizeof(h),0x8c0004000,0x80000000));
 for(unsigned flags=0;flags<16;++flags){h.flags=flags;assert(B5qUsbPolicy::accepts(&h,sizeof(h),0x8c0004000,0x80000000)==(flags==7));}h.flags=7;
 h.sid=0x60;assert(!B5qUsbPolicy::accepts(&h,sizeof(h),0x8c0004000,0x80000000));h.sid=0x40;
 assert(!B5qUsbPolicy::accepts(&h,sizeof(h)-1,0x8c0004000,0x80000000));
 assert(!B5qUsbPolicy::accepts(&h,sizeof(h),0x8bffff000,4096));
 assert(!B5qUsbPolicy::accepts(&h,sizeof(h),0x9bffff000,8192));
 assert(!B5qUsbPolicy::accepts(&h,sizeof(h),UINT64_MAX-1,8));
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
 puts("PASS USB DMA gates/host reset bounds and actual Samsung GMU firmware plan/load/hash controls; no device I/O");
}
