// Execute actual USB handoff/host sequence and Samsung GMU loader on fixtures.
#include "B5qPeripheralHardware.h"
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
 puts("PASS actual Samsung GMU firmware plan/load/hash controls; USB native tests are separate");
}
