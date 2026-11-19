// SPDX-License-Identifier: BSD-2-Clause-Patent
// Byte-only GPT and root-manifest checks; shared by the real driver and host tests.
#pragma once
#include <stdint.h>
#include <stddef.h>
namespace B5qFormat {
constexpr uint64_t firstLba=49692663, lastLba=62275574;
constexpr uint64_t partitionBytes=(lastLba-firstLba+1)*4096ULL;
inline uint32_t le32(const uint8_t *p) { return uint32_t(p[0])|(uint32_t(p[1])<<8)|(uint32_t(p[2])<<16)|(uint32_t(p[3])<<24); }
inline uint64_t le64(const uint8_t *p) { return le32(p)|(uint64_t(le32(p+4))<<32); }
inline uint32_t be32(const uint8_t *p) { return (uint32_t(p[0])<<24)|(uint32_t(p[1])<<16)|(uint32_t(p[2])<<8)|p[3]; }
inline void putBe32(uint8_t *p,uint32_t v) { for(unsigned i=0;i<4;++i)p[i]=v>>(24-8*i); }
inline void putBe64(uint8_t *p,uint64_t v) { putBe32(p,uint32_t(v>>32));putBe32(p+4,uint32_t(v)); }
inline uint32_t crc32(const uint8_t *p,size_t size) { uint32_t crc=~0U;for(size_t i=0;i<size;++i){crc^=p[i];for(unsigned b=0;b<8;++b)crc=(crc>>1)^(0xedb88320U&uint32_t(-int(crc&1)));}return ~crc; }
inline bool equal(const void *a,const void *b,size_t n) { const auto *p=static_cast<const uint8_t*>(a),*q=static_cast<const uint8_t*>(b);uint8_t d=0;while(n--)d|=*p++^*q++;return !d; }
inline bool inside(uint64_t offset,uint64_t size,uint64_t limit) { return size && offset<=limit && size<=limit-offset; }
struct Gpt { uint64_t entriesLba;uint32_t count,stride,crc; };
inline bool header(const uint8_t *h,uint64_t blocks,Gpt &out) {
 if(!equal(h,"EFI PART",8)||le32(h+8)!=0x10000||le32(h+12)<92||le32(h+12)>4096||le32(h+20)||le64(h+24)!=1||le64(h+32)!=blocks-1)return false;
 uint8_t copy[4096];for(unsigned i=0;i<4096;++i)copy[i]=h[i];uint32_t expected=le32(h+16);for(unsigned i=16;i<20;++i)copy[i]=0;
 if(crc32(copy,le32(h+12))!=expected)return false;
 out={le64(h+72),le32(h+80),le32(h+84),le32(h+88)};
 uint64_t bytes=uint64_t(out.count)*out.stride;
 return blocks>lastLba && le64(h+40)<=firstLba && le64(h+48)>=lastLba && out.entriesLba>=2 && out.entriesLba<=64 && out.count && out.count<=4096 && out.stride>=128 && out.stride<=1024 && !(out.stride%8) && bytes<=1024*1024 && (bytes+4095)/4096<=265-out.entriesLba;
}
inline bool target(const uint8_t *entries,const Gpt &g) {
 if(crc32(entries,size_t(g.count)*g.stride)!=g.crc)return false;
 unsigned found=0;
 for(unsigned i=0;i<g.count;++i){const uint8_t *e=entries+size_t(i)*g.stride;bool nonzero=false;for(unsigned j=0;j<16;++j)nonzero|=e[j]!=0;if(!nonzero)continue;
  uint64_t first=le64(e+32),last=le64(e+40);if(last<first)return false;
  bool name=true;const char wanted[]="macosroot";for(unsigned j=0;j<sizeof(wanted);++j)if(e[56+2*j]!=uint8_t(wanted[j])||e[57+2*j])name=false;
  if(name){if(first!=firstLba||last!=lastLba||++found!=1)return false;}
  else if(first<=lastLba&&firstLba<=last)return false;
 }
 return found==1;
}
struct Entry { char name[32];uint64_t offset,bytes;uint32_t block,flags;uint8_t sha256[32]; };
inline bool manifestEntries(const uint8_t *h,Entry out[6],uint64_t &total) {
 if(!equal(h,"SHNGROOT",8)||le32(h+8)!=2||le32(h+12)!=6)return false;
 total=le64(h+16);if(total<1048576||total>partitionBytes||total%1048576)return false;
 const char *names[]={"OS","SystemOS","App","OS.vroot","SystemOS.vroot","App.vroot"};uint64_t end=1048576;
 for(unsigned i=0;i<6;++i){const uint8_t *e=h+24+i*128;auto &r=out[i];unsigned n=0;for(;n<31&&names[i][n];++n)if(e[n]!=uint8_t(names[i][n]))return false;
  for(unsigned j=n;j<32;++j)if(e[j])return false;
  for(unsigned j=0;j<32;++j)r.name[j]=char(e[j]);r.offset=le64(e+32);r.bytes=le64(e+40);r.block=le32(e+48);r.flags=le32(e+52);for(unsigned j=0;j<32;++j)r.sha256[j]=e[56+j];
  if(r.offset%1048576||r.offset<end||!inside(r.offset,r.bytes,total)||r.block!=(i<3?512U:4096U)||r.flags!=(i<3?1U:3U))return false;
  for(unsigned j=88;j<128;++j)if(e[j])return false;
  end=r.offset+r.bytes;
 }
 return true;
}
}
