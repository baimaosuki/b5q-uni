#!/usr/bin/env python3
"""Run the real serialized board port poll with cached Samsung mailbox events."""
from pathlib import Path
import subprocess,tempfile
R=Path(__file__).resolve().parents[2]
source=(R/'UniXNU-b5q/package/B5qUsbBoard.cpp').read_text()
def function(name):
 start=source.index(name);at=source.index('{',start);depth=0
 for end in range(at,len(source)):
  depth+=(source[end]=='{')-(source[end]=='}')
  if not depth:return source[start:end+1]
poll=function('extern "C" bool b5q_dp_port_poll(')
stop=function('extern "C" void b5q_dp_port_stop(')
# The transport is mocked; the production orchestration and AltMode parser
# remain real. No synthetic implementation of the state transitions is tested.
poll=poll.replace('B5qDp::Mailbox<PdicIo>','TestMailbox')
stop=stop.replace('B5qDp::Mailbox<PdicIo>','TestMailbox')
h=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <array>
#include <map>
#include <vector>
#include "B5qMax77705.h"
#include "B5qDpPdic.h"
#include "B5qDpPort.h"
using namespace B5qDp;
uint64_t nowMs;uint64_t dpNow(){return nowMs;}
bool locked,openOk=true,sampleOk=true,interruptOk=true;
B5qMax77705::Cable cableSample;
uint8_t pdInterrupt,vdmInterrupt;
struct Max {
 int *lock=nullptr;
 bool read(uint8_t address,uint8_t reg,uint8_t &v){
  assert(locked&&address==0x25);if(!sampleOk)return false;
  if(reg==0x0a)v=cableSample.cc0;else if(reg==0x0b)v=cableSample.cc1;
  else if(reg==0x0d)v=cableSample.pd;else if(reg==8)v=cableSample.bc;
  else if(reg==4){if(!interruptOk)return false;v=pdInterrupt;pdInterrupt=0;}
  else if(reg==5){if(!interruptOk)return false;v=vdmInterrupt;vdmInterrupt=0;}
  else assert(false);return true;
 }
}maxInstance,*maxim=&maxInstance;
bool openMaxim(){return openOk;}void IOLockLock(int*){assert(!locked);locked=true;}
void IOLockUnlock(int*){assert(locked);locked=false;}
template<class... A>void IOLog(const char *,A...){}
struct PdicIo{};
unsigned enables,disables,gets;bool boxFail=false;
std::map<unsigned,std::array<uint8_t,33>> replies;
std::vector<unsigned> requests,positions;
struct TestMailbox {
 PdError error=PdError::None;
 explicit TestMailbox(PdicIo&){}
 bool enable(bool on){assert(locked);if(on)enables++;else disables++;error=boxFail?PdError::Io:PdError::None;return !boxFail;}
 bool request(unsigned cmd,unsigned pos=0,uint32_t=0,bool=false){assert(locked);requests.push_back(cmd);positions.push_back(pos);error=boxFail?PdError::Io:PdError::None;return !boxFail;}
 bool get(unsigned id,uint8_t out[33]){assert(locked);gets++;if(boxFail||!replies.count(id)){error=PdError::Io;return false;}
  for(unsigned i=0;i<33;i++)out[i]=replies[id][i];return true;}
};
B5qDp::AltMode dpAlt;bool dpStarted=false,dpFailed=false;uint32_t dpCable=0,dpPending=0;uint64_t dpDeadline=0,dpRetryAt=0,dpStatusAt=0;unsigned dpStartAttempts=0,dpStatusAttempts=0;
uint32_t dpDeferSignature=~0u,dpIrqBits=0;
std::array<uint8_t,33> packet(unsigned id,uint32_t vdo=0,unsigned count=3){
 std::array<uint8_t,33>b{};b[0]=0x4b;b[1]=id;b[2]=count;
 put32(b.data()+4,(uint32_t(id<=2?0xff00:0xff01)<<16)|0x8000|(id==6?0:64)|id|((id==4||id==0x11)?256:0));put32(b.data()+8,vdo);return b;
}
'''
test=r'''
void reset(bool powered=true){
 dpAlt={};dpStarted=dpFailed=false;dpCable=dpPending=0;dpDeadline=nowMs=dpRetryAt=dpStatusAt=0;dpStartAttempts=dpStatusAttempts=0;
 dpDeferSignature=~0u;dpIrqBits=0;
 locked=false;sampleOk=interruptOk=openOk=true;boxFail=false;enables=disables=gets=0;pdInterrupt=vdmInterrupt=0;requests.clear();positions.clear();
 cableSample={};cableSample.cc0=0x40|(powered?1:2);cableSample.pd=128;cableSample.bc=0x80;cableSample.valid=true;
 replies={{1,packet(1)},{2,packet(2,0xff01)},{3,packet(3,5|64|(28u<<16))},{4,packet(4,0,2)},
          {0x10,packet(0x10,2|128|16)},{0x11,packet(0x11,0,2)},{6,packet(6,2|128)}};
}
void active(B5qDpPortState &out){
 vdmInterrupt=15;pdInterrupt=12;assert(b5q_dp_port_poll(&out));assert(out.configured&&out.hpd&&out.lanes==2&&out.reverse==0);
 assert(dpAlt.phase==AltMode::Phase::Active&&dpStarted&&!dpFailed&&!locked);
}
int main(){unsigned cases=0;B5qDpPortState out{};
 // No optional DP mailbox operation may consume the initial Source->VBUS
 // window, including a native Source and the VCONN-only fallback.
 for(unsigned cc:{0x42u,0x48u,0x88u}){
  reset(false);cableSample.cc0=cc;cableSample.bc=0;boxFail=true;
  assert(b5q_dp_port_poll(&out)&&out.attached&&!out.configured&&!dpStarted&&!locked);
  assert(!enables&&!disables&&!gets&&requests.empty()&&!dpAlt.generation);
  cableSample.bc=0x80;boxFail=false;
  assert(b5q_dp_port_poll(&out)&&dpStarted&&enables==1);cases++;
 }
 for(bool powered:{false,true}){
  reset(powered);active(out);assert(enables==1&&disables==0&&gets==6);
  assert((requests==(powered?std::vector<unsigned>{1,4,17}:std::vector<unsigned>{4,17})));
  unsigned prior=gets;vdmInterrupt=15;pdInterrupt=8;assert(b5q_dp_port_poll(&out)&&out.configured&&gets==prior);cases++;
  uint32_t generation=out.generation;
  replies[6]=packet(6,2);pdInterrupt=16;assert(b5q_dp_port_poll(&out)&&out.configured&&!out.hpd&&out.lanes==2&&out.generation==generation);cases++;
  replies[6]=packet(6,2|128|256);pdInterrupt=16;assert(b5q_dp_port_poll(&out)&&out.configured&&out.hpd&&out.hpdIrq&&out.generation==generation);
  assert(b5q_dp_port_poll(&out)&&!out.hpdIrq&&out.hpd);cases++;
  replies[6]=packet(6,2|64);pdInterrupt=16;assert(b5q_dp_port_poll(&out)&&!out.configured&&!dpStarted&&dpFailed);unsigned before=enables;
  assert(b5q_dp_port_poll(&out)&&enables==before);cases++;
 }

 // Real board event lengths must allow a second ModeVDO, and keep its
 // objectposition through Enter and Configure on later polls.
 reset();replies[3]=packet(3,2|(4u<<8),4);put32(replies[3].data()+12,5|64|(28u<<16));
 put32(replies[4].data()+4,le32(replies[4].data()+4)+256);
 put32(replies[0x11].data()+4,le32(replies[0x11].data()+4)+256);
 active(out);assert(dpAlt.modePosition==2&&(positions==std::vector<unsigned>{0,2,2}));cases++;
 reset();vdmInterrupt=7;replies[3]=packet(3,5|(4u<<8),4);put32(replies[3].data()+4,(0x04e8u<<16)|0x8000|64|3);
 assert(b5q_dp_port_poll(&out)&&dpAlt.phase==AltMode::Phase::Modes&&dpStarted&&dpAlt.modesRequested);
 replies[3]=packet(3,2|(4u<<8),4);put32(replies[3].data()+12,5|64|(28u<<16));
 put32(replies[4].data()+4,le32(replies[4].data()+4)+256);put32(replies[0x11].data()+4,le32(replies[0x11].data()+4)+256);
 vdmInterrupt=12;pdInterrupt=12;assert(b5q_dp_port_poll(&out)&&out.configured&&dpAlt.modePosition==2);cases++;
 // Coalesced/missed VDM interrupts are recovered in the native order.
 reset();vdmInterrupt=8;
 for(unsigned i=0;i<3;i++){assert(b5q_dp_port_poll(&out));nowMs+=50;}
 assert(dpAlt.phase==AltMode::Phase::Status&&gets==4);pdInterrupt=12;assert(b5q_dp_port_poll(&out)&&out.configured);cases++;
 // Early Attention/Status must wait for Enter, not reject and disable USB.
 reset();pdInterrupt=20;assert(b5q_dp_port_poll(&out)&&dpAlt.phase==AltMode::Phase::Identity&&dpStarted);
 vdmInterrupt=15;assert(b5q_dp_port_poll(&out)&&dpAlt.phase==AltMode::Phase::Configure);pdInterrupt=8;assert(b5q_dp_port_poll(&out)&&out.configured);cases++;
 reset();assert(b5q_dp_port_poll(&out));nowMs=3001;assert(!b5q_dp_port_poll(&out)&&out.error==unsigned(PdError::Timeout)&&!dpStarted&&dpFailed);cases++;
 for(unsigned failure=0;failure<4;failure++){
  reset();active(out);if(failure==0)sampleOk=false;if(failure==1)cableSample.cc1=2;
  if(failure==2)cableSample.cc0=0;if(failure==3)interruptOk=false;
  (void)b5q_dp_port_poll(&out);assert(!out.configured&&!out.hpd&&!dpStarted&&!locked);cases++;
 }
 reset();replies[1][0]=0x4a;vdmInterrupt=1;assert(!b5q_dp_port_poll(&out)&&dpFailed&&!dpStarted);cases++;
 reset();boxFail=true;assert(!b5q_dp_port_poll(&out)&&dpFailed&&!locked);cases++;
 reset();active(out);b5q_dp_port_stop();assert(!dpStarted&&!dpFailed&&dpPending==0&&!locked);cases++;
 printf("PASS %u actual board PDIC polls:automaticVDM/poweredhub/missedIRQ/duplicates/HPD-pulse/lane-retention/exit/deadline/water/IO/malformed/lockownership ASanUBSan\n",cases);
}
'''
with tempfile.TemporaryDirectory(prefix='b5q-dp-port-')as td:
 t=Path(td);(t/'test.cpp').write_text(h+'\n'+poll+'\n'+stop+'\n'+test)
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(R/'UniXNU-b5q/package'),str(t/'test.cpp'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test')],check=True)
