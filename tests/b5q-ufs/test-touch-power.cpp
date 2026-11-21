#include "B5qTouchPower.h"
#include "B5qTouchIrq.h"
#include <cassert>
#include <array>
#include <vector>
#include <utility>
#include <cstdio>
struct Regs{
 std::array<uint8_t,256> regs={};std::vector<std::pair<unsigned,unsigned>> writes;int fail=-1;bool corrupt=false;
 bool read(uint8_t a,uint8_t &v){if(a==fail)return false;v=regs[a];if(corrupt&&a==3&&!writes.empty())v^=1;return true;}
 bool write(uint8_t a,uint8_t v){if(a==fail)return false;writes.emplace_back(a,v);regs[a]=v;return true;}
};
// Execute the production bit-bang bus against an open-drain slave. Clock
// transitions sample eight request bits, then drive ACK or read data.
struct Pins{
 bool masterSda=false,masterScl=false,slaveSda=false,clock=false;bool active=false,reading=false,ack=false;
 unsigned bit=0,byte=0,acks=0;std::vector<unsigned> bytes;uint8_t value=0xa6;int nack=-1;bool stuck=false;
 bool high(unsigned pin){return pin==21?!masterScl&&!stuck:!masterSda&&!slaveSda;}
 void delay(unsigned us){assert(us==2);}
 void low(unsigned pin,bool drive){
  if(pin==20){
   bool old=high(20);masterSda=drive;bool now=high(20);
   if(high(21)&&old!=now){
    if(old&&!now){active=true;bit=byte=0;reading=ack=false;}
    else if(!old&&now){active=false;slaveSda=false;}
   }
   return;
  }
  assert(pin==21);bool before=high(21);masterScl=drive;bool after=high(21);
  if(!active||before==after)return;
  if(after){
   if(bit<8){if(!reading)byte=(byte<<1)|high(20);++bit;}
   else {bit=9;}
  }else{
   if(bit==8){
    if(!reading){bytes.push_back(byte);slaveSda=(int(acks++)!=nack);ack=true;}
    else slaveSda=false;
   }else if(bit==9){
    bool nextRead=!reading&&(byte&1)&&bytes.size()>=3;
    bit=byte=0;reading=nextRead;slaveSda=reading&&!(value&0x80);ack=false;
   }else if(reading)slaveSda=!(value&(0x80>>bit));
  }
 }
};
int main(){
 for(unsigned before=0;before<256;before++){
  Regs r;r.regs[3]=before;r.regs[5]=0x80;r.regs[6]=0x80;uint8_t a=0,b=0;
  assert(B5qTouchPower::enable(r,a,b));assert(a==before&&b==(before|6));
  assert(r.regs[5]==0x8e&&r.regs[6]==0x98&&((before^r.regs[3])&~6u)==0);
  for(auto w:r.writes)assert(w.first==3||w.first==5||w.first==6);
 }
 for(int fail:{3,5,6}){Regs r;r.fail=fail;uint8_t a,b;assert(!B5qTouchPower::enable(r,a,b));}
 Regs corrupt;corrupt.corrupt=true;uint8_t a,b;assert(!B5qTouchPower::enable(corrupt,a,b));
 for(unsigned i=0;i<256;i++){
  Pins p;p.value=i;B5qTouchPower::Bus<Pins> bus(p);uint8_t v=0;assert(bus.read(5,v)&&v==i);
  assert((p.bytes==std::vector<unsigned>{0xc0,5,0xc1}));assert(!p.masterSda&&!p.masterScl);
 }
 Pins p;B5qTouchPower::Bus<Pins> bus(p);assert(bus.write(3,0x1f));assert((p.bytes==std::vector<unsigned>{0xc0,3,0x1f}));
 for(int ack=0;ack<3;ack++){Pins p;p.nack=ack;B5qTouchPower::Bus<Pins> b(p);assert(!b.write(3,7));assert(!p.masterScl&&!p.masterSda);}
 Pins stuck;stuck.stuck=true;B5qTouchPower::Bus<Pins> sb(stuck);uint8_t out=0;assert(!sb.read(0,out));assert(!stuck.masterSda&&!stuck.masterScl);
 uint32_t status=0;unsigned writes=0;
 auto read=[&](unsigned off){assert(off==0x1300c);return status;};auto write=[&](unsigned off,uint32_t v){assert(off==0x1300c&&!v);++writes;status=0;};
 assert(!B5qTouchIrq::acknowledge(read,write)&&!writes);status=1;assert(B5qTouchIrq::acknowledge(read,write)&&writes==1);
 auto cfg=B5qTouchIrq::disabled(0xfeed1234);assert((cfg&0xff)==0x7a&&(cfg&~0xffu)==0xfeed1200);
 puts("PASS actual open-drain I2C reads/writes/NACK/stuckclock; all256 PMIC enable values preserve unrelated rails; GPIO19 shared status isolated");
}
