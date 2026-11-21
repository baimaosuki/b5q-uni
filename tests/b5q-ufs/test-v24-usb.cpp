#include "B5qUsbSmmu.h"
#include "B5qMax77705.h"
#include "B5qUsbIrq.h"
#include <map>
#include <vector>
#include <cassert>
#include <cstdio>
struct Smmu {
 std::map<unsigned,uint32_t> regs;std::vector<unsigned> reads,writes;unsigned barriers=0;
 Smmu(){regs[0x20]=8;regs[0x24]=8;for(unsigned i=0;i<8;i++){regs[0x800+i*4]=0x80001c00|(2u<<16);regs[0x1000+i*4]=0x1f000;}regs[0x804]=0;regs[0x1018]=0x20000;}
 uint32_t read(unsigned off){assert(off!=0xc00);reads.push_back(off);return regs[off];}
 void write(unsigned off,uint32_t val){assert(off!=0xc00);writes.push_back(off);regs[off]=val;}
};
struct Pmic {
 std::map<unsigned,uint8_t> regs;std::vector<unsigned>writes;bool fail=false;
 Pmic(){regs[0xb2]=4;regs[0xc3]=0x60;regs[0xb7]=0x85;}
 bool read(uint8_t addr,uint8_t reg,uint8_t &v){assert(addr==0x69);v=regs[reg];return !fail;}
 bool write(uint8_t addr,uint8_t reg,uint8_t v){assert(addr==0x69);writes.push_back(reg);regs[reg]=v;return !fail;}
};
int main(){
 for(uint32_t type=0;type<4;type++)for(unsigned vmid=0;vmid<256;vmid++)assert(B5qUsbSmmu::freeCbar(type<<16|vmid)==(type==0||type==2||(type==1&&vmid==255)));
 Smmu m;B5qUsbSmmu::Plan p;auto rd=[&](unsigned o){return m.read(o);};auto wr=[&](unsigned o,uint32_t v){m.write(o,v);};
 assert(B5qUsbSmmu::plan(rd,p)&&p.slot==1&&p.bank==6&&p.pages==2);
 for(unsigned o:m.reads)assert((o>=0x800&&o<0x820)||(o>=0x1000&&o<0x1020)||o==0x20||o==0x24);
 assert(B5qUsbSmmu::install(rd,wr,[&]{++m.barriers;},[](unsigned){},p,0x8c0001000));
 assert(m.regs[0xc04]==6&&m.regs[0x804]==0x80000040&&m.writes.back()==0x804);
 for(unsigned o:m.writes)assert(o<0x2000||(o>=0x8000&&o<0x9000));
 assert(m.regs[0x1018]==0x1f300&&m.regs[0x101c]==0x1f000); // bypass bank untouched
 for(unsigned o:m.reads)assert(o<0x2000||(o>=0x8000&&o<0x9000));
 {Smmu x;x.regs[0x1018]=0x1f000;B5qUsbSmmu::Plan q;assert(!B5qUsbSmmu::plan([&](unsigned o){return x.read(o);},q));assert(x.writes.empty());}
 {Smmu x;x.regs[0x804]=0x80000040;B5qUsbSmmu::Plan q;assert(!B5qUsbSmmu::plan([&](unsigned o){return x.read(o);},q));assert(x.writes.empty());}
 {Smmu x;x.regs[0x804]=0x80000000|(0x40u<<16);B5qUsbSmmu::Plan q;assert(!B5qUsbSmmu::plan([&](unsigned o){return x.read(o);},q));}
 {Smmu x;x.regs[0x804]=0x80001234;B5qUsbSmmu::Plan q;assert(!B5qUsbSmmu::plan([&](unsigned o){return x.read(o);},q));}
 {Smmu x;B5qUsbSmmu::Plan q;auto r=[&](unsigned o){return x.read(o);};assert(B5qUsbSmmu::plan(r,q));x.regs[0x1018]=0x1f000;assert(!B5qUsbSmmu::install(r,[&](unsigned o,uint32_t v){x.write(o,v);},[]{},[](unsigned){},q,0x8c0001000));assert(x.writes.empty());}
 {Smmu x;B5qUsbSmmu::Plan q;auto r=[&](unsigned o){return x.read(o);};assert(B5qUsbSmmu::plan(r,q));x.regs[0x87f4]=1;assert(!B5qUsbSmmu::install(r,[&](unsigned o,uint32_t v){x.write(o,v);},[]{},[](unsigned){},q,0x8c0001000));assert(x.regs[0x804]==0);}
 for(auto pair:std::vector<std::pair<unsigned,unsigned>>{{0,10},{4,14},{5,15},{8,10},{12,14},{13,14},{10,10},{14,14},{15,15}}){
  Pmic x;x.regs[0xb7]=0x80|pair.first;unsigned waited=0;assert(B5qMax77705::otg(x,true,[&](unsigned n){waited+=n;}));
  assert((x.regs[0xb7]&15)==pair.second&&(x.regs[0xb7]&0xf0)==0x80&&x.regs[0xc3]==0x60&&(x.regs[0xb9]&0xc0)==0x40);
  assert(waited==((pair.first==8||pair.first==12||pair.first==13)?1000u:0u));
  assert(B5qMax77705::otg(x,false,[](unsigned){}));assert(!(x.regs[0xb7]&2));
 }
 {Pmic x;x.regs[0xb2]=0;assert(!B5qMax77705::otg(x,true,[](unsigned){}));assert(x.writes.empty());}
 {Pmic x;x.regs[0xb2]=0x24;assert(!B5qMax77705::otg(x,true,[](unsigned){}));assert(x.writes.empty());}
 {Pmic x;x.fail=true;assert(!B5qMax77705::otg(x,true,[](unsigned){}));}
 assert(B5qMax77705::role(2,0)==2&&B5qMax77705::role(1,0)==1&&B5qMax77705::role(2,2)==0);
 {B5qUsbIrq::Window w;for(unsigned n=0;n<8192;n++)assert(!w.observe(100,1000));assert(w.observe(100,1000));assert(!w.observe(1100,1000));}
 puts("PASS production CBAR planner/install:display+slot0+bypass isolated,existingSID/full/race/TLBtimeout negatives;max77705state/readback/rails;IRQtimewindow");
}
