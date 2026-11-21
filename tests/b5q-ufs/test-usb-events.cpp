#include "B5qUsbPolicy.h"
#include <cassert>
#include <map>
#include <vector>
#include <string>
#include <cstdio>
int main(){
 for(unsigned hardware:{0u,1u,2u})for(unsigned pending:{0u,128u}){
  std::map<unsigned,unsigned> regs={{0xc120,0x33313130},{0xc110,0x00102001},{0xc704,1u<<31},{0xc70c,1u<<22},
   {0xc708,~0u},{0xc408,4096},{0xc40c,pending},{0xc140,hardware},{0xcc08,0x123},{0xcc0c,0x456},
   {0,0x1000020},{0x10,1},{0x20,0},{0x24,1},{0xc200,0x140},{0xc2c0,1u<<17}};
  struct Event{char kind;unsigned off,value;};std::vector<Event> events;bool reset=false;
  auto read=[&](unsigned off,unsigned &v){assert(regs.count(off));assert(hardware==2||off<0xcc00);v=regs[off];if(off==0x20&&reset)v&=~2u;events.push_back({'r',off,v});return true;};
  auto write=[&](unsigned off,unsigned v){assert(regs.count(off));assert(hardware==2||off<0xcc00);events.push_back({'w',off,v});
   if(off==0xc40c||off==0xcc08)regs[off]&=~v;else regs[off]=v;
   if(off==0x20&&(v&2))reset=true;return true;};
  auto delay=[&](unsigned us){assert(us==20000||us==1000||us==100);events.push_back({'d',0,us});};
  assert(!B5qUsbPolicy::prepare(read,write,delay));
  assert(!regs[0xc708]&&(regs[0xc408]>>31)&&!regs[0xc40c]);assert((regs[0xc110]&(3u<<12))==(1u<<12)&&!(regs[0xc110]&(1u<<11)));
  if(hardware==2)assert(!regs[0xcc0c]&&!regs[0xcc08]);else assert(regs[0xcc0c]==0x456&&regs[0xcc08]==0x123);
  unsigned mask=0,drain=0,soft=0,release=0,role=0,hold=0,gap=0,stop=0;
  for(unsigned i=0;i<events.size();++i){auto e=events[i];if(e.kind=='w'){
   if(e.off==0xc704)stop=i;
   if(e.off==0xc708)mask=i;
   if(e.off==0xc40c)drain=i;
   if(e.off==0xc110&&(e.value&(1u<<11)))soft=i;
   if(e.off==0xc110&&!(e.value&(1u<<11))){if(!release)release=i;else role=i;}
  }if(e.kind=='d'&&e.value==20000)hold=i;if(e.kind=='d'&&e.value==1000)gap=i;}
  assert(stop<mask&&mask<soft&&soft<hold&&hold<release&&release<gap&&gap<role);if(pending)assert(mask<drain&&drain<soft);
  // Any failed event access returns before releasing core reset/starting Host.
  for(unsigned fault:{0xc708u,0xc408u,0xc40cu,0xc140u}){
   bool host=false;auto faultRead=[&](unsigned off,unsigned &v){if(off==fault)return false;v=regs[off];return true;};
   auto faultWrite=[&](unsigned off,unsigned v){if(off==fault)return false;if(off==0xc110)host=true;(void)v;return true;};
   assert(B5qUsbPolicy::prepare(faultRead,faultWrite,[](unsigned){})!=nullptr&&!host);
  }
 }
 puts("PASS actual DWC3 policy: Device/DRD IRQ mask+W1C drain, no OTG access on non-DRD, ordered 20ms reset + separate1ms release + Hostrole and fail-before-host");
}
