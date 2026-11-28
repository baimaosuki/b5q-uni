#!/usr/bin/env python3
"""Run source-qualified production AUX FIFO framing/errors/retry/bounds."""
from pathlib import Path
import subprocess,tempfile
R=Path(__file__).resolve().parents[2]
h=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <vector>
#include <cstring>
#include "B5qDpAux.h"
struct Io {
 struct Write{B5qDp::Block block;uint32_t off,value;};std::vector<Write>writes;
 uint32_t result=B5qDp::auxDone,control=1,trans=0;unsigned elapsed=0,starts=0,rx=0;bool active=false,reading=false,online=true,badIndex=false,deferOnce=false;
 bool connected(){return online;}
 uint64_t nowUs(){return elapsed;}
 void delay(unsigned us){elapsed+=us;}
 uint32_t read(B5qDp::Block b,uint32_t off){
  if(b==B5qDp::Block::Ahb&&off==0x20)return active?(deferOnce&&starts==1?B5qDp::auxDefer:result):0;
  if(b==B5qDp::Block::Aux&&off==0x30)return control;
  if(b==B5qDp::Block::Aux&&off==0x38)return trans;
  if(b==B5qDp::Block::Aux&&off==0x34&&reading){if(!rx++){return 0;}unsigned i=rx-2;return((badIndex?i+1:i)<<16)|((i+17)<<8);}
  assert(false);return 0;
 }
 void write(B5qDp::Block b,uint32_t off,uint32_t value){writes.push_back({b,off,value});
  if(b==B5qDp::Block::Ahb&&off==0x20){assert(!(value&(B5qDp::auxInterrupts<<2)));active=false;}
  if(b==B5qDp::Block::Aux&&off==0x30)control=value;
  if(b==B5qDp::Block::Aux&&off==0x38){trans=value;if(value&(1u<<9)){active=true;starts++;}}
  if(b==B5qDp::Block::Aux&&off==0x34&&value==((1u<<31)|1u)){reading=true;rx=0;}
 }
};
// STOP drops the read pointer on this sink; segment selection persists.
// Model transactions at register level so the real AUX framing is exercised.
struct EdidIo {
 uint8_t edid[1024]{};std::vector<uint8_t> fifo,reply;
 unsigned segment=0,offset=0,rx=0,starts=0,segmentWrites=0,offsetWrites=0,failAt=0;
 bool active=false,oldSink=false;uint32_t trans=0,control=1;
 EdidIo(){for(unsigned b=0;b<8;b++){unsigned sum=0;for(unsigned i=0;i<127;i++){edid[b*128+i]=uint8_t(b*39+i*7);sum+=edid[b*128+i];}edid[b*128+127]=uint8_t(-sum);}}
 bool connected(){return true;}void delay(unsigned){}uint64_t nowUs(){return 0;}
 uint32_t read(B5qDp::Block b,uint32_t off){using namespace B5qDp;
  if(b==Block::Ahb&&off==0x20)return active?(failAt==starts?auxNack:auxDone):0;
  if(b==Block::Aux&&off==0x30)return control;
  if(b==Block::Aux&&off==0x38)return trans;
  if(b==Block::Aux&&off==0x34){if(!rx++)return 0;unsigned i=rx-2;assert(i<reply.size());return(i<<16)|(uint32_t(reply[i])<<8);}
  assert(false);return 0;
 }
 void write(B5qDp::Block b,uint32_t off,uint32_t value){using namespace B5qDp;
  if(b==Block::Ahb&&off==0x20){active=false;return;}
  if(b==Block::Aux&&off==0x30){control=value;return;}
  if(b==Block::Aux&&off==0x34){
   if(value==((1u<<31)|1u)){rx=0;return;}
   if(value&(1u<<31))fifo.clear();fifo.push_back(uint8_t(value>>8));return;
  }
  assert(b==Block::Aux&&off==0x38);trans=value;if(!(value&(1u<<9)))return;
  active=true;++starts;assert(fifo.size()>=4);assert(value&(1u<<8));
  unsigned address=(unsigned(fifo[0]&15)<<16)|(unsigned(fifo[1])<<8)|fifo[2];
  bool reading=fifo[0]&16,mot=value&(1u<<11);unsigned n=fifo[3]+1;reply.clear();
  if(reading){assert(address==0x50&&n==16);for(unsigned i=0;i<n;i++)reply.push_back(edid[segment*256+offset+i]);offset+=n;}
  else{assert(n==1&&fifo.size()==5&&mot);if(address==0x30){assert(!oldSink);segment=fifo[4];segmentWrites++;}else{assert(address==0x50);offset=fifo[4];offsetWrites++;}}
  if(!mot)offset=0;
 }
};
struct SlowIo:Io {
 bool connected(){elapsed+=5000;return online;}
 uint32_t read(B5qDp::Block b,uint32_t off){elapsed+=10000;return Io::read(b,off);}
};
int main(){using namespace B5qDp;unsigned cases=0;
 for(bool native:{false,true})for(bool reading:{false,true})for(unsigned n=1;n<=16;n++){
  Io io;Aux<Io> aux(io);uint8_t data[16];for(unsigned i=0;i<16;i++)data[i]=uint8_t(i+1);
  const unsigned addr=native?0x12345:0x50;assert(aux.transfer(native,reading,addr,data,n,true));
  std::vector<uint32_t> bytes;for(auto w:io.writes)if(w.block==Block::Aux&&w.off==0x34)bytes.push_back(w.value);
  assert(bytes[0]==((1u<<31)|((((addr>>16)&15)|(reading?16:0))<<8))&&bytes[1]==(((addr>>8)&255)<<8)&&bytes[2]==((addr&255)<<8)&&bytes[3]==((n-1)<<8));
  assert(bytes.size()==(reading?5:n+4));if(reading)for(unsigned i=0;i<n;i++)assert(data[i]==i+17);cases++;
 }
 for(uint32_t fault:{auxAddress,auxTimeout,auxNackDefer,auxCount,auxNack,auxDefer,auxPll,auxPhy}){Io io;io.result=fault;Aux<Io> aux(io);uint8_t data[16];memset(data,0xaa,sizeof data);assert(!aux.transfer(true,true,0x202,data,6));for(auto b:data)assert(b==0xaa);assert(io.starts==((fault&(auxNackDefer|auxDefer))?7u:1u)&&io.trans==0);cases++;}
 {Io io;io.result=0;Aux<Io>aux(io);uint8_t b=0;assert(!aux.transfer(true,true,0,&b,1)&&aux.error==AuxError::Timeout&&io.elapsed>=250000);}
 {Io io;io.deferOnce=true;Aux<Io>aux(io);uint8_t b=0;assert(aux.transfer(true,true,0,&b,1)&&io.starts==2&&b==17);}
 {Io io;io.badIndex=true;Aux<Io>aux(io);uint8_t b=0xaa;assert(!aux.transfer(true,true,0,&b,1)&&aux.error==AuxError::Index&&b==0xaa);}
 {Io io;io.online=false;Aux<Io>aux(io);uint8_t b=0;assert(!aux.transfer(true,true,0,&b,1)&&aux.error==AuxError::Detached&&io.writes.empty());}
 {SlowIo io;io.result=0;Aux<SlowIo>aux(io);uint8_t b=0;
  assert(!aux.transfer(true,true,0,&b,1)&&aux.error==AuxError::Timeout&&io.elapsed>=250000&&io.elapsed<350000);cases++;}
 for(unsigned n=0;n<=20;n++){Io io;Aux<Io>aux(io);uint8_t b[20]={0};bool ok=aux.transfer(true,true,0x202,b,n);assert(ok==(n>=1&&n<=16));if(!n||n>16)assert(io.writes.empty());}
 {Io io;Aux<Io>aux(io);uint8_t b[32]={0};assert(!aux.dpcd(true,0xfffff,b,2)&&io.writes.empty());assert(aux.dpcd(true,0x202,b,32)&&io.starts==2);}
 unsigned edidCases=0;
 {EdidIo io;io.oldSink=true;Aux<EdidIo>aux(io);uint8_t out[128];assert(aux.edidBlock(0,out)&&!memcmp(out,io.edid,128)&&io.segmentWrites==0&&io.offsetWrites==8);edidCases++;}
 for(unsigned first=0;first<8;first++)for(unsigned second=0;second<8;second++){
  EdidIo io;Aux<EdidIo>aux(io);uint8_t out[128];
  assert(aux.edidBlock(first,out)&&!memcmp(out,io.edid+first*128,128));
  assert(aux.edidBlock(second,out)&&!memcmp(out,io.edid+second*128,128));edidCases++;
 }
 for(unsigned failure=1;failure<=24;failure++){EdidIo io;io.failAt=failure;Aux<EdidIo>aux(io);uint8_t out[128];memset(out,0xaa,128);
  assert(!aux.edidBlock(2,out)&&aux.error==AuxError::Nack);for(auto v:out)assert(v==0xaa);edidCases++;}
 {EdidIo io;io.edid[17]^=1;Aux<EdidIo>aux(io);uint8_t out[128];memset(out,0xaa,128);assert(!aux.edidBlock(0,out)&&aux.error==AuxError::Count);for(auto v:out)assert(v==0xaa);edidCases++;}
 printf("PASS productionEDID %u sink cases:8blocks/order/segmentreset/MOT/STOP-pointer-loss/24transactionfailures/CRC/atomicpublication ASanUBSan\n",edidCases);
 printf("PASS productionAUX FIFO%ucases/nativeI2C/readwrite1..16/8faults/bounded250mstimeout/7deferretries/shortindex/detach/overflow;ASanUBSan\n",cases);
}
'''
with tempfile.TemporaryDirectory(prefix='b5q-dp-aux-')as td:
 t=Path(td);(t/'test.cpp').write_text(h);subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-Wno-narrowing','-O1','-g','-fsanitize=address,undefined','-I'+str(R/'UniXNU-b5q/package'),str(t/'test.cpp'),'-o',str(t/'test')],check=True);subprocess.run([str(t/'test')],check=True)
