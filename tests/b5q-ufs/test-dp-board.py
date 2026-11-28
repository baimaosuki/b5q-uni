#!/usr/bin/env python3
"""Actual native AUX switch helper: CC polarity, active-low enable, restoration."""
from pathlib import Path
import hashlib,subprocess,tempfile
R=Path(__file__).resolve().parents[2]
D=R/'artifacts/b5q-p4-work/samsung-source/full/qcom/opensource/display-drivers/msm/dp/dp_power.c'
s=D.read_text()
assert 'void secdp_power_set_gpio(bool flip)'in s and 'gpio_direction_output(config->gpio, 0);'in s
dts=(R/'uefi-b5q/Resources/DTBs/b5q.dts').read_text()
assert 'qcom,aux-en-gpio = <0x7d 0xb7 0x00>;'in dts and 'qcom,aux-sel-gpio = <0x7d 0xb4 0x00>;'in dts
assert 'secdp,aux-sel-inv;'not in dts
h=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <vector>
#include <tuple>
#include <random>
#include "B5qDpBoard.h"
using namespace B5qDp;
struct Io {
 uint32_t cfg[2]{},out[2]{};bool stuck=false;unsigned elapsed=0;
 std::vector<std::tuple<unsigned,unsigned,uint32_t>>writes;
 unsigned index(unsigned pin){assert(pin==180||pin==183);return pin==183;}
 uint32_t gpioRead(unsigned pin,unsigned off){unsigned i=index(pin);assert(off==0||off==4);
  if(!off)return cfg[i];return (out[i]&~1u)|uint32_t(!stuck&&((cfg[i]&0x200)?(out[i]&2):1));}
 void gpioWrite(unsigned pin,unsigned off,uint32_t value){unsigned i=index(pin);assert(off==0||off==4);
  if(off)out[i]=value&~1u;else cfg[i]=value;writes.emplace_back(pin,off,value);}
 void delay(unsigned us){elapsed+=us;}
};
int main(){unsigned cases=0;std::mt19937 rng(0x180183);
 for(unsigned n=0;n<4096;n++)for(bool reverse:{false,true}){
  Io io;for(unsigned i=0;i<2;i++){io.cfg[i]=rng();io.out[i]=rng()&~1u;}
  const auto before=io;AuxPins p;assert(p.begin(io,reverse)&&p.owned&&io.elapsed==200);
  assert((io.cfg[0]&0x3ff)==0x200&&(io.cfg[1]&0x3ff)==0x200);
  assert(bool(io.gpioRead(180,4)&1)==reverse&&!(io.gpioRead(183,4)&1));
  assert((io.cfg[0]&~0x3ffu)==(before.cfg[0]&~0x3ffu));
  // First disable AUX, then change selection, then enable it low.
  assert(std::get<0>(io.writes[0])==183&&std::get<1>(io.writes[0])==4&&(std::get<2>(io.writes[0])&2));
  auto writes=io.writes.size();assert(!p.begin(io,!reverse)&&io.writes.size()==writes);
  assert(p.end(io)&&!p.owned&&io.elapsed==300);
  for(unsigned i=0;i<2;i++)assert(io.cfg[i]==before.cfg[i]&&io.out[i]==before.out[i]);
  writes=io.writes.size();assert(p.end(io)&&io.writes.size()==writes);cases++;
 }
 {Io io;io.stuck=true;AuxPins p;assert(!p.begin(io,false)&&p.owned);assert(!p.end(io)&&p.owned);
  io.stuck=false;assert(p.end(io)&&!p.owned);assert(p.begin(io,true)&&p.end(io));cases++;}
 printf("PASS native DP AUX switch %u GPIO180/183 cases/CC1CC2/active-low/readback/refusal/restore/noGPIO11 ASanUBSan\n",cases);
}
'''
with tempfile.TemporaryDirectory(prefix='b5q-dp-board-')as td:
 t=Path(td);(t/'test.cpp').write_text(h)
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(R/'UniXNU-b5q/package'),str(t/'test.cpp'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test')],check=True)
