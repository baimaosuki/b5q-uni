#!/usr/bin/env python3
"""Exercise production Samsung mailbox and DP VDM/HPD state transitions."""
from pathlib import Path
import subprocess,tempfile
R=Path(__file__).resolve().parents[2]
h=r'''
#include <cassert>
#include <cstring>
#include <cstdio>
#include <vector>
#include <array>
#include <random>
#include "B5qDpPdic.h"
using namespace B5qDp;
struct Io {
 std::vector<std::vector<uint8_t>> writes;unsigned elapsed=0,reads=0,readCost=0;bool online=true,fail=false,timeout=false,wrong=false;uint8_t opcode=0;
 bool connected(){return online;}void delay(unsigned us){elapsed+=us;}uint64_t nowUs(){return elapsed;}
 bool write(uint8_t address,const uint8_t *data,unsigned n){assert(address==0x25);if(fail)return false;writes.emplace_back(data,data+n);if(data[0]==0x21)opcode=data[1];return true;}
 bool read(uint8_t address,uint8_t reg,uint8_t *out,unsigned n){assert(address==0x25);elapsed+=readCost;if(fail)return false;++reads;memset(out,0,n);
  if(reg==2){assert(n==1);*out=reads>1&&!timeout?128:0;}else if(reg==0x51){assert(n==1);*out=wrong?0xff:opcode;}else assert(reg==0x52);return true;}
};
struct M {
 PdError error=PdError::None;bool fail=false;unsigned cmd=0,pos=0;uint32_t vdo=0;bool data=false;
 bool enable(bool){return !fail;}
 bool request(unsigned c,unsigned p=0,uint32_t v=0,bool d=false){cmd=c;pos=p;vdo=v;data=d;error=fail?PdError::Io:PdError::None;return !fail;}
};
std::array<uint8_t,33> packet(uint8_t id,uint32_t vdo=0,unsigned objects=3,unsigned type=1){
 std::array<uint8_t,33>b{};b[0]=0x4b;b[1]=id;b[2]=objects;
 put32(b.data()+4,(uint32_t(id<=2?0xff00:0xff01)<<16)|0x8000|(type<<6)|id|((id==4||id==0x11)?256:0));put32(b.data()+8,vdo);return b;}
void event(AltMode &s,M &m,unsigned id,uint32_t vdo=0,unsigned objects=3,unsigned type=1){auto b=packet(id,vdo,objects,type);assert(s.event(m,id,b.data(),objects*4));}
void throughStatus(AltMode &s,M &m,uint8_t pins,bool multi,bool receptacle=true){
 assert(s.start(m)&&m.cmd==0);event(s,m,1);assert(m.cmd==0);event(s,m,2,0xff01);assert(m.cmd==0);
 event(s,m,3,5|(receptacle?64:0)|(uint32_t(pins)<<(receptacle?16:8)));assert(m.cmd==4&&m.pos==1);
 event(s,m,4,0,2);assert(m.cmd==4&&!m.data);
 event(s,m,0x10,2|128|(multi?16:0));assert(m.cmd==17&&m.pos==1&&m.vdo==(6|(uint32_t(s.pin)<<8)));
}
int main(){unsigned cases=0;
 for(unsigned n=0;n<=32;n++){Io io;Mailbox<Io> box(io);uint8_t data[32]={},out[33];assert(box.command(0x48,data,n,out,32));assert(io.writes[0].size()==n+2&&io.writes[0][0]==0x21&&io.writes[0][1]==0x48);assert(io.writes.size()==(n==32?1u:2u));if(n<32)assert((io.writes[1]==std::vector<uint8_t>{0x41,0}));cases++;}
 {Io io;Mailbox<Io>box(io);assert(box.enable(true));assert((io.writes[0]==std::vector<uint8_t>{0x21,0x55,3}));assert(box.request(17,1,0x806,true));assert((io.writes[2]==std::vector<uint8_t>{0x21,0x48,10,17,129,1,255,6,8,0,0}));}
 for(unsigned fault=0;fault<5;fault++){Io io;io.online=fault!=0;io.fail=fault==1;io.timeout=fault==2;io.wrong=fault==3;Mailbox<Io>box(io);uint8_t out[33]={};bool ok=box.command(0x55,nullptr,fault==4?33:0,out,1);assert(!ok);if(fault==2)assert(io.elapsed==500000&&box.error==PdError::Timeout);cases++;}
 for(unsigned cost:{100u,1000u,10000u,75000u}){Io io;io.timeout=true;io.readCost=cost;Mailbox<Io>box(io);uint8_t out[2]={0xaa,0xbb};assert(!box.command(0x55,nullptr,0,out,1)&&box.error==PdError::Timeout);assert(io.elapsed>=500000&&io.elapsed<=500000+2*cost+1000&&io.reads<500&&out[0]==0xaa&&out[1]==0xbb);cases++;}
 for(unsigned pins=0;pins<64;pins++)for(bool multi:{false,true}){const uint8_t p=AltMode::choose(pins,multi);assert(p==0||(p&pins));assert(!p||p==4||p==8||p==16);cases++;}
 for(unsigned pins:{4u,8u,16u,12u,20u,28u})for(bool multi:{false,true})for(bool receptacle:{false,true}){
  M m;AltMode s;throughStatus(s,m,pins,multi,receptacle);assert(!s.hpdIrq&&s.hpd&&s.phase==AltMode::Phase::Configure);event(s,m,0x11,0,2);assert(s.phase==AltMode::Phase::Active&&s.lanes()==(s.pin==8?2u:4u));
  event(s,m,6,2|128|256,3,0);assert(s.hpd&&s.hpdIrq);event(s,m,6,2,3,0);assert(!s.hpd&&!s.hpdIrq);event(s,m,6,64|2,3,0);assert(s.phase==AltMode::Phase::Off&&!s.hpd);cases++;}
 {M m;AltMode s;assert(s.start(m));auto b=packet(2,0xff01);assert(!s.event(m,2,b.data(),12)&&s.error==PdError::Sequence);}
 {M m;AltMode s;assert(s.start(m,true)&&m.cmd==1);event(s,m,1);assert(m.cmd==1);event(s,m,2,0xff01);assert(m.cmd==1);}
 for(unsigned n=0;n<12;n++){M m;AltMode s;assert(s.start(m));auto b=packet(1);assert(!s.event(m,1,b.data(),n));}
 for(unsigned type:{0u,2u,3u}){M m;AltMode s;assert(s.start(m));auto b=packet(1,0,3,type);assert(!s.event(m,1,b.data(),12));}
 {M m;AltMode s;assert(s.start(m));event(s,m,1);event(s,m,2,0xff01);m.fail=true;auto b=packet(3,5|(4u<<8));assert(!s.event(m,3,b.data(),12)&&s.error==PdError::Io);}
 std::mt19937 rng(0x77705);for(unsigned i=0;i<100000;i++){uint8_t bytes[33];for(auto &v:bytes)v=uint8_t(rng());M m;AltMode s;assert(s.start(m));(void)s.event(m,uint8_t(rng()),bytes,rng()%34);}
 printf("PASS SamsungPDIC %ucases:mailboxlength0..32/endmarker/500msbound/opcode/IO/detach/CDEpin/plug-receptacle/HPD/NAK/order/truncation/100000fuzz ASanUBSan\n",cases);
}
'''
with tempfile.TemporaryDirectory(prefix='b5q-dp-pdic-')as td:
 t=Path(td);(t/'test.cpp').write_text(h)
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-O1','-g','-fsanitize=address,undefined','-I'+str(R/'UniXNU-b5q/package'),str(t/'test.cpp'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test')],check=True)
