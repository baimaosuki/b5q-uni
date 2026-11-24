#!/usr/bin/env python3
"""Original b5q PHY sequence and electrical reset/clock/LTSSM causal model."""
from pathlib import Path
import re,subprocess,tempfile
R=Path(__file__).resolve().parents[2];P=R/'UniXNU-b5q/package'
s=(R/'uefi-b5q/Resources/DTBs/b5q.dts').read_text();a=s.index('qcom,phy-status-offset = <0x214>');seq=re.search(r'qcom,phy-sequence = <([^>]+)>',s[a:])[1];raw=[int(v,16)for v in seq.split()]
table=[tuple(int(v,0)for v in row)for row in re.findall(r'\{(0x[0-9a-f]+),(0x[0-9a-f]+),(\d+)\}',(P/'B5qPcieInputs.h').read_text())];assert table==list(zip(raw[::3],raw[1::3],raw[2::3]))and len(table)==115
source=r'''
#include "B5qPcieCore.h"
#include <cassert>
#include <cstdint>
#include <map>
#include <cstdio>
struct IO {
 unsigned time=0,enAt=0,resetAt=0,released=0,phyWrites=0,ltssmAt=0,fault=0;bool powerOn=false,en=false,perst=false;
 std::map<unsigned,uint32_t>regs;
 bool power(){powerOn=true;return true;}
 bool radio(bool on){assert(powerOn&&!perst);en=on;enAt=time;time+=55000;return true;}
 void pin(unsigned pin,uint32_t,int level){assert(powerOn);if(pin==94){perst=level;if(!level)resetAt=time;else{assert(en&&time-enAt>=100000&&time-resetAt>=100000);released=time;}}}
 bool gcc(uint32_t r,uint32_t c,uint32_t v){assert(powerOn);regs[r]=(regs[r]&~c)|v;return true;}
 bool rcg(uint32_t r){assert(powerOn);regs[r]=0;return true;} // successful selfclear
 uint32_t readGcc(uint32_t r){return r==0x6b004||r==0x6c000?1u<<31:regs[r];}
 bool clkref(){return true;}void delay(unsigned n){time+=n;assert(time<2000000);}
 bool openController(){assert(powerOn&&en);return true;}bool openPhy(){assert(!perst);return true;}
 void phy(unsigned off,uint32_t val){assert(!perst&&phyWrites<115);const auto &p=B5qPcieInputs::phy[phyWrites++];assert(p.offset==off&&p.value==val);}
 uint32_t readPhy(uint32_t r){assert(r==0x214&&phyWrites==115);return 0;}
 void parf(unsigned r,uint32_t,uint32_t v){if(r==0x1b0){assert(v==256&&perst&&released&&time-released>=1000&&phyWrites==115);ltssmAt=time;}}
 void dbi(unsigned,uint32_t,uint32_t){}
 uint32_t readDbi(unsigned r){assert(ltssmAt);if(fault)return r==0x728?fault:0;
  bool ready=time-ltssmAt>=20000;return r==0x728?(ready?0x11:2):(ready?16:0);}
};
int main(){IO ok;uint32_t d[4]={};assert(!B5qPcie::train(ok,d)&&d[0]==0x11&&d[1]==16&&d[2]==21);
 for(unsigned state:{1u,2u,13u}){IO bad;bad.fault=state;assert(B5qPcie::train(bad,d)==-16&&d[0]==state&&d[1]==0&&d[2]==1000&&!d[3]);}
 puts("PASS original115PHY entries exact; WLAN_EN/PERST100ms/clocks/LTSSM1ms causalmodel; realraw728/72c/PHY214 retained on3bounded linktimeouts");}
'''
with tempfile.TemporaryDirectory(prefix='b5q-pcie-timing-')as td:
 t=Path(td);(t/'t.cpp').write_text(source);subprocess.run(['c++','-std=c++17','-O1','-g','-fsanitize=address,undefined','-I'+str(P),str(t/'t.cpp'),'-o',str(t/'test')],check=True);subprocess.run([str(t/'test')],check=True)
