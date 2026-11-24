#!/usr/bin/env python3
"""Exercise the production CR/EQ/downshift decisions with sink faults."""
from pathlib import Path
import subprocess,tempfile
R=Path(__file__).resolve().parents[2]
h=r'''
#include <cassert>
#include <cstdio>
#include <cstring>
#include <vector>
#include "B5qDpTraining.h"
using namespace B5qDp;
struct Io {
 bool online=true,ioFail=false,phyFail=false,crFail=false,eqFail=false,loseCr=false;unsigned downshift=0,rate=0,p=0,elapsed=0,statusReads=0;std::vector<unsigned> rates,patterns;uint8_t level=0;
 bool connected(){return online;}void delay(unsigned us){elapsed+=us;}
 bool phy(unsigned r,unsigned n){assert(n==1||n==2||n==4);rate=r;rates.push_back(r);return !phyFail;}
 bool levels(unsigned v,unsigned pre,unsigned r){assert(v<=2&&pre<=3-v&&r==rate);return true;}
 bool pattern(unsigned n){p=n;patterns.push_back(n);return true;}
 bool dpcd(bool reading,uint32_t address,uint8_t *b,unsigned n){
  if(ioFail)return false;if(reading){assert(address==0x202&&n==6);statusReads++;memset(b,0,n);b[0]=b[1]=crFail||(downshift&&rate>downshift)?0:0x11;
   if(p!=1&&!crFail){if(loseCr)b[0]=b[1]=0;else if(!eqFail){b[0]=b[1]=0x77;b[2]=1;}}b[4]=b[5]=0x55;return true;}
  assert(address==0x100||address==0x102||address==0x103||address==0x107||address==0x108);if(address==0x103)level=b[0];return true;
 }
};
int main(){unsigned cases=0;uint8_t d[16]={0x14,30,0xc4,128};LinkCaps caps;assert(caps.parse(d,4)&&caps.pattern()==7&&caps.delay(false)==100&&caps.delay(true)==400);
 Mode m{148500,1920,1080,280,45,88,44,4,5,true,true};assert(m.valid());
 for(unsigned lanes:{1u,2u,4u})for(unsigned rate:{6u,10u,20u,30u}){d[1]=rate;d[2]=uint8_t(128|64|lanes);assert(caps.parse(d,4));Io io;Training<Io>t(io);bool ok=t.run(caps,m);assert(ok==m.fits(lanes,rate));if(ok)assert(t.ready&&io.p==0&&t.attempts==1);else assert(!t.ready&&t.error==TrainError::Bandwidth);cases++;}
 d[1]=30;d[2]=0xc4;assert(caps.parse(d,4));
 for(unsigned fault=0;fault<7;fault++){Io io;io.online=fault!=0;io.ioFail=fault==1;io.phyFail=fault==2;io.crFail=fault==3;io.eqFail=fault==4;io.loseCr=fault==5;io.downshift=fault==6?10:0;Training<Io>t(io);const bool ok=t.run(caps,m);assert(ok==(fault==6));assert(io.statusReads<100&&t.attempts<=4);if(ok)assert(t.rate==10&&t.ready&&t.attempts==3);else assert(!t.ready);cases++;}
 for(unsigned v=0;v<256;v++)for(unsigned pre=0;pre<256;pre++){Io io;Training<Io>t(io);t.lanes=4;t.last[4]=v;t.last[5]=pre;t.adjust();assert(t.voltage<=2&&t.pre+t.voltage<=3);cases++;}
 for(unsigned n=0;n<256;n++){uint8_t copy[16];memcpy(copy,d,16);copy[14]=n;LinkCaps c;bool ok=c.parse(copy,2);assert(ok==((n&127)<=4));if(ok)assert(c.lanes==2&&c.delay(true)<=16000);}
 printf("PASS productionDPtraining %ucases:1-2-4lanes/rates6-10-20-30/CR-EQ-faults/downshift/IO-detach/levelsclamp/intervalbound ASanUBSan\n",cases);
}
'''
with tempfile.TemporaryDirectory(prefix='b5q-dp-training-')as td:
 t=Path(td);(t/'test.cpp').write_text(h)
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-O1','-g','-fsanitize=address,undefined','-I'+str(R/'UniXNU-b5q/package'),str(t/'test.cpp'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test')],check=True)
