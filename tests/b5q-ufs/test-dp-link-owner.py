#!/usr/bin/env python3
"""Test the actual native Owner lifecycle; transport/session have separate tests."""
from pathlib import Path
import subprocess,tempfile
R=Path(__file__).resolve().parents[2]
s=(R/'UniXNU-b5q/package/B5qDpLink.cpp').read_text()
def method(signature):
 start=s.index(signature,s.index('struct Owner {'));brace=s.index('{',start);depth=0
 for at in range(brace,len(s)):
  depth+=(s[at]=='{')-(s[at]=='}')
  if not depth:return s[start:at+1]
body="""struct Owner {
 Hardware io;B5qDp::Session<Hardware> session;uint32_t generation=0;
 uint64_t retryAt=0;bool accepted=false,startPass=true,poolPass=true,drainPass=true;
 struct {uint64_t PoolBytes=0x1f00000;}dma;
 struct {void close(){}}pool;
 struct {struct{bool active=false;}dpu;bool timedOut(int){return false;}}presentation;
 int scan=0,lock=0;int *scanLock=&lock;
 IOService *display=nullptr,*provider=nullptr;
 Owner():session(io){}
 bool poolReady(){return poolPass;}
 bool startDisplay(){return startPass;}
 static bool drain(Owner *p){return p->drainPass;}
"""+method(' bool stop(){')+method(' void update(')+'};'
usb=(R/'UniXNU-b5q/package/QcomDwc3.cpp').read_text()
start=usb.index('        if(dpEnabled&&!b5q_dp_link_stop()){');brace=usb.index('{',start);depth=0
for at in range(brace,len(usb)):
 depth+=(usb[at]=='{')-(usb[at]=='}')
 if not depth:roleGate=usb[start:at+1];break
assert start<usb.index('        leaveRole(gRoleApplied);',start)
h=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include "B5qDpPort.h"
#include "B5qDpModes.h"
#include "B5qMax77705.h"
uint64_t tick=0;uint64_t nowUs(){return tick;}
template<class...Args>void log(const char *,Args...args){((void)args,...);}
#define IOLog(...) log(__VA_ARGS__)
bool canStop=true,attached=true;unsigned transitions=0,powerOffs=0,sleeps=0;
bool b5q_dp_link_stop(){return canStop;}
bool b5q_usb_cable_state(B5qMax77705::Cable *c){c->valid=true;c->cc0=attached?0x41:0;return true;}
bool b5q_usb_otg(bool value){assert(!value);powerOffs++;return true;}
void IOSleep(unsigned ms){assert(ms==100);sleeps++;}
constexpr unsigned kIOServiceSynchronous=1;
struct IOService{bool disconnectPass=true;unsigned released=0;IOService *getProvider(){return nullptr;}void detach(IOService *){}void release(){released++;}void terminate(unsigned){}};
bool b5q_dp_display_disconnect(IOService *p){return p->disconnectPass;}
void b5q_dp_lid_online(bool){}
void IOLockLock(int*){}void IOLockUnlock(int*){}
struct Hardware {
 bool opened=false,mxOwned=false,fault=false,openPass=true,closePass=true;
 unsigned wantedReverse=0,opens=0,closes=0;
 bool connected(){return opened;}
 bool open(bool reverse){opens++;wantedReverse=reverse;opened=true;return openPass;}
 bool close(){closes++;if(!closePass)return false;opened=false;return true;}
};
namespace B5qDp {
template<class Io>struct Session {
 Io &io;bool stopPass=true,discoverPass=true,trainPass=true,healthy=true;
 unsigned stops=0,discovers=0,trains=0,lanes=2,rate=20,attempts=1;
 struct{unsigned failed=0;}clock,phy;struct{unsigned count=1;unsigned fitPool(uint64_t){return count;}}modes;
 unsigned error=0;Mode selected{148500,1920,1080,280,45,88,44,4,5,true,true};
 struct Aux {Session &s;unsigned error=0,reads=0;
  bool dpcd(bool read,unsigned address,uint8_t *out,unsigned size){
   assert(read&&address==0x202&&size==6);reads++;memset(out,0,size);
   if(s.healthy){out[0]=out[1]=0x77;out[2]=1;}return true;
  }
 }aux;
 explicit Session(Io &i):io(i),aux{*this}{}
 bool stop(){stops++;return stopPass;}
 bool discover(unsigned n,bool){discovers++;lanes=n;return discoverPass;}
 bool train(){trains++;return trainPass;}
};
}
'''
gate='void roleTransition(bool dpEnabled){for(unsigned once=0;once<1;once++){'+roleGate+'transitions++;}}\n'
test=r'''
int main(){unsigned cases=0;
 auto port=[](){B5qDpPortState p{};p.attached=p.configured=p.hpd=true;p.lanes=2;p.reverse=0;p.generation=1;p.pin=8;return p;};
 {Owner o;auto p=port();o.update(p);assert(o.accepted&&o.io.opens==1&&o.session.trains==1);
  o.update(p);assert(o.accepted&&o.io.opens==1&&o.session.trains==1&&o.session.aux.reads==1);
  o.session.healthy=false;o.update(p);assert(o.accepted&&o.io.opens==2&&o.session.trains==2);
  o.session.healthy=true;p.hpdIrq=true;o.update(p);assert(o.accepted&&o.io.opens==3);
  p.hpdIrq=false;p.hpd=false;o.update(p);assert(!o.accepted&&!o.io.opened);
  p.hpd=true;p.reverse=1;o.update(p);assert(o.accepted&&o.io.wantedReverse==1);cases++;}
 for(unsigned invalid=0;invalid<6;invalid++){
  Owner o;auto p=port();if(invalid==0)p.attached=false;if(invalid==1)p.configured=false;
  if(invalid==2)p.hpd=false;if(invalid==3)p.reverse=-1;if(invalid==4)p.reverse=2;if(invalid==5)p.lanes=1;
  o.update(p);assert(!o.accepted&&!o.io.opens);cases++;
 }
 {Owner o;auto p=port();o.update(p);assert(o.accepted);o.session.stopPass=false;p.generation++;
  auto opens=o.io.opens,closes=o.io.closes;o.update(p);assert(!o.accepted&&o.io.opened&&o.io.opens==opens&&o.io.closes==closes);
  o.session.stopPass=true;o.update(p);assert(o.io.opens==opens);tick+=1000000;o.update(p);assert(o.accepted&&o.io.opens==opens+1);cases++;}
 for(unsigned failure=0;failure<4;failure++){
  Owner o;auto p=port();if(!failure)o.io.openPass=false;if(failure==1)o.session.discoverPass=false;
  if(failure==2)o.session.trainPass=false;if(failure==3)o.io.fault=true;
  o.update(p);assert(!o.accepted&&!o.io.opened&&o.io.opens==1);o.update(p);assert(o.io.opens==1);
  o.io.openPass=o.session.discoverPass=o.session.trainPass=true;o.io.fault=false;tick+=1000000;
  o.update(p);assert(o.accepted&&o.io.opened&&o.io.opens==2);cases++;
 }
 {Owner o;auto p=port();o.update(p);o.io.closePass=false;assert(!o.stop()&&!o.accepted&&o.io.opened);
  o.io.closePass=true;assert(o.stop()&&!o.io.opened);cases++;}
 for(bool enabled:{false,true})for(bool stop:{false,true})for(bool present:{false,true}){
  canStop=stop;attached=present;transitions=powerOffs=sleeps=0;roleTransition(enabled);
  const bool held=enabled&&!stop;
  assert(transitions==unsigned(!held)&&sleeps==unsigned(held)&&powerOffs==unsigned(held&&!present));cases++;
 }
 {Owner o;auto p=port();o.poolPass=false;o.update(p);assert(!o.accepted&&!o.io.opens);o.poolPass=true;tick+=1000000;o.startPass=false;o.update(p);assert(!o.accepted);o.startPass=true;tick+=1000000;o.update(p);assert(o.accepted);cases++;}
 {Owner o;IOService display;o.display=&display;display.disconnectPass=false;auto closes=o.io.closes;assert(!o.stop()&&o.display==&display&&o.io.closes==closes);display.disconnectPass=true;assert(o.stop()&&!o.display&&display.released==1);cases++;}
 printf("PASS actual native DP Owner %u attach/HPD/polarity/linkloss/retry/failure/stop-retention cases\n",cases);
}
'''
with tempfile.TemporaryDirectory(prefix='b5q-dp-owner-')as td:
 t=Path(td);(t/'test.cpp').write_text(h+body+gate+test)
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(R/'UniXNU-b5q/package'),str(t/'test.cpp'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test')],check=True)
