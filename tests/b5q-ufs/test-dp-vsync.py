#!/usr/bin/env python3
"""Exercise actual INTF0 W1C/enable ownership and IRQ-only frame delivery."""
from pathlib import Path
import hashlib,re,subprocess,tempfile
R=Path(__file__).resolve().parents[2]
D=R/'artifacts/b5q-p5-work/source-extra/qcom/opensource/display-drivers/msm/sde'
source=(D/'sde_hw_interrupts.c').read_bytes()
assert hashlib.sha256(source).hexdigest()=='92152ce7f874279af0bd492017c2e7463681686faee36d8da494815d60b27a08'
regs=(D/'sde_hwio.h').read_text()
assert hashlib.sha256(regs.encode()).hexdigest()=='5330d038b45a68e61063606e0003bf7767ec4c11d6eb44b4a0e9777cf881020f'
for key,value in [('INTR_EN','010'),('INTR_STATUS','014'),('INTR_CLEAR','018')]:
 assert re.search(r'#define '+key+r'\s+0x0*'+value.lstrip('0')+r'\b',regs)
assert '#define SDE_INTR_INTF_0_VSYNC BIT(25)'in source.decode()
assert '#define SDE_INTR_INTF_0_UNDERRUN BIT(24)'in source.decode()
catalog=(D/'sde_hw_catalog.c').read_text()
assert 'SDE_INTR_TOP_INTR, cfg->mdp[0].base)'in catalog
dts=(R/'uefi-b5q/Resources/DTBs/b5q.dts').read_text()
assert 'qcom,sde-off = <0x1000>;'in dts
h=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <vector>
#include <utility>
#include "B5qDpVsync.h"
using namespace B5qDp;
struct Io {
 uint32_t enabled=0,pending=0,frame=0;unsigned signals=0,barriers=0;
 std::vector<std::pair<unsigned,uint32_t>> writes;
 uint32_t read(unsigned off){
  if(off==0x1010)return enabled;if(off==0x1014)return pending;
  assert(off==0x350ac);return frame;
 }
 void write(unsigned off,uint32_t value){
  writes.emplace_back(off,value);
  if(off==0x1010)enabled=value;
  else{assert(off==0x1018&&!(value&~Vsync::mask));pending&=~value;}
 }
 void barrier(){barriers++;}
 void vsync(uint32_t value){assert(value==frame);signals++;}
};
int main(){unsigned cases=0;
 for(unsigned bit=0;bit<32;bit++){
  Vsync v;Io io;const uint32_t unrelated=(1u<<bit)&~Vsync::mask;
  io.enabled=unrelated;io.pending=unrelated|Vsync::mask;
  assert(v.begin(io)&&v.active&&io.enabled==(unrelated|Vsync::mask)&&io.pending==unrelated);
  auto n=io.writes.size();assert(!v.begin(io)&&io.writes.size()==n);
  assert(!v.service(io)&&!io.signals&&io.pending==unrelated);
  for(unsigned event=0;event<100;event++){
   io.pending=unrelated|Vsync::frameBit|((event&1)?Vsync::underrunBit:0);
   io.frame=event+1;assert(v.service(io));
   assert(io.pending==unrelated&&io.signals==event+1&&v.frames==event+1&&v.lastFrame==event+1);
   assert(!v.service(io));cases++;
  }
  assert(v.underruns==50);io.pending=unrelated|Vsync::underrunBit;
  assert(v.service(io)&&v.underruns==51&&io.signals==100);
  v.end(io);assert(!v.active&&io.enabled==unrelated&&io.pending==unrelated);
  n=io.writes.size();v.end(io);assert(io.writes.size()==n);
  io.pending=Vsync::mask;assert(!v.service(io)&&io.writes.size()==n&&io.signals==100);
  assert(v.begin(io));v.end(io);cases++;
 }
 for(uint32_t occupied:{Vsync::frameBit,Vsync::underrunBit,Vsync::mask}){
  Vsync v;Io io;io.enabled=occupied;
  assert(!v.begin(io)&&!v.active&&io.writes.empty());cases++;
 }
 {Vsync v;Io io;assert(v.begin(io));v.frames=~0u;io.pending=Vsync::frameBit;io.frame=0;
  assert(v.service(io)&&v.frames==0&&v.lastFrame==0&&io.signals==1);v.end(io);cases++;}
 printf("PASS DP hardwareVSync %u W1C/isolation/reentry/detach/framewrap cases; no timer-generated frames ASanUBSan\n",cases);
}
'''
with tempfile.TemporaryDirectory(prefix='b5q-dp-vsync-')as td:
 t=Path(td);(t/'test.cpp').write_text(h)
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(R/'UniXNU-b5q/package'),str(t/'test.cpp'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test')],check=True)
