// SPDX-License-Identifier: BSD-2-Clause-Patent
// Historical test filename retained for older local preflight entry points.
#include "B5qMax77705.h"
#include <cassert>
#include <cstdio>
#include <vector>
struct Bus {
 unsigned failed=0xff,reads=0;bool torn=false;
 std::vector<unsigned> regs;
 bool read(uint8_t address,uint8_t reg,uint8_t &value){
  assert(address==0x25);regs.push_back(reg);++reads;
  if(reg==failed)return false;
  value=reg==0x0a?uint8_t(torn&&reads==5?0x41:0x81):reg==0x0d||reg==8?0x80:0;
  return true;
 }
 bool write(uint8_t,uint8_t,uint8_t){assert(false);return false;}
};
int main(){
 Bus b;B5qMax77705::Cable c;
 assert(B5qMax77705::readCable(b,c)&&c.valid&&c.role()==2&&c.power()==1&&c.orientation()==1&&!c.sourceVbus(2));
 assert((b.regs==std::vector<unsigned>{0x0a,0x0b,0x0d,8,0x0a}));
 for(unsigned fail:{0x0au,0x0bu,0x0du,8u}){
  Bus bad;bad.failed=fail;assert(!B5qMax77705::readCable(bad,c)&&!c.valid&&!c.role()&&c.orientation()==-1);
 }
 Bus bad;bad.torn=true;assert(!B5qMax77705::readCable(bad,c)&&!c.role());
 for(unsigned power:{1u,2u})for(unsigned data:{0u,128u})for(unsigned pin:{0u,1u,2u,3u}){
  c={uint8_t(power|(pin<<6)),0,uint8_t(data),0x80,true};
  assert(c.role()==(data?2:1));assert(c.sourceVbus(c.role())==(power==2));
  assert(c.orientation()==(pin==1||pin==2?int(pin-1):-1));
  const auto sig=c.signature();c.bc=0;assert(c.signature()!=sig);
  c.cc1=2;assert(!c.role()&&!c.sourceVbus(2)&&c.orientation()==-1);
 }
 puts("PASS original CC/PD snapshot:5statusreads,no opcode/interrupt writes,allpower/data/orientation pairs,water,I2C/torn rejection");
}
