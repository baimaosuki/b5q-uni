#!/usr/bin/env python3
"""Execute production state machines with physical feedback and self-clear."""
from pathlib import Path
import subprocess,tempfile
R=Path(__file__).resolve().parents[2];P=R/'UniXNU-b5q/package'
def function(text,signature):
 start=text.index(signature);at=text.index('{',start);end=at+1;depth=1
 while depth:depth+=(text[end]=='{')-(text[end]=='}');end+=1
 return text[start:end]
def execute(name,body):
 with tempfile.TemporaryDirectory(prefix='b5q-'+name+'-')as td:
  td=Path(td);src=td/'test.cpp';src.write_text(body)
  subprocess.run(['c++','-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-Wno-unused-parameter','-fsanitize=address,undefined','-I'+str(P),'-I'+str(R/'sources/UniXNU-sheng/package'),str(src),'-o',str(td/'test')],check=True)
  subprocess.run([str(td/'test')],check=True)
base=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <vector>
#include <map>
#include <cstring>
#include <stdexcept>
'''
# Run the actual shared trigger helper: the register model clears UPDATE
# on the write itself, before any readback, matching successful silicon.
s=(P/'Sm8550Gcc.c').read_text();trigger=function(s,'bool sm8550_gcc_trigger32(').replace('volatile uint32_t *reg','Register *reg').replace('__asm__ volatile("dsb sy" ::: "memory");','').replace('__asm__ volatile("dsb sy":::"memory");','')
body=base+r'''
#include "B5qPcieCore.h"
struct Register {uint32_t value=0;bool stuck=false;unsigned triggers=0;operator uint32_t()const{return value;}void operator|=(uint32_t v){value|=v;triggers++;if(!stuck)value&=~1u;}};
struct IOLock{} lock;IOLock *get_gcc_lock(){return &lock;}void IOLockLock(IOLock*){}void IOLockUnlock(IOLock*){}unsigned waits=0;void IODelay(unsigned){waits++;}
TRIGGER
struct IO{
 std::map<uint32_t,Register> regs;unsigned pulses=0;bool stuck=false;
 bool power(){return true;}bool radio(bool){return true;}void pin(unsigned,uint32_t,int){}
 bool gcc(uint32_t off,uint32_t clear,uint32_t set){assert(off!=0x6b074&&off!=0x6b058);regs[off].value=(regs[off].value&~clear)|set;return true;}
 bool rcg(uint32_t off){assert(off==0x6b074||off==0x6b058);regs[off].stuck=stuck;++pulses;return sm8550_gcc_trigger32(&regs[off],1,100);}
 uint32_t readGcc(uint32_t off){if(off==0x6b004||off==0x6c000)return 1u<<31;return regs[off];}
 bool clkref(){return true;}void delay(unsigned){}bool openController(){return true;}bool openPhy(){return true;}
 void parf(uint32_t,uint32_t,uint32_t){}void dbi(uint32_t,uint32_t,uint32_t){}void phy(uint32_t,uint32_t){}
 uint32_t readPhy(uint32_t){return 0;}uint32_t readDbi(uint32_t off){return off==0x72c?16:0x11;}
};
int main(){IO io;assert(B5qPcie::train(io)==0&&io.pulses==2&&waits==0);IO bad;bad.stuck=true;assert(B5qPcie::train(bad)==-12&&waits==100);puts("PASS real RCG immediate selfclear accepted, stuck UPDATE bounded failure; full PCIe115-write production train");}
'''
execute('rcg',body.replace('TRIGGER',trigger))
# Execute the actual board poll and actual controller role loop together.
us=(P/'B5qUsbBoard.cpp').read_text();q=(P/'QcomDwc3.cpp').read_text()
start=us.index('struct PdicIo {');end=us.index('extern "C" bool b5q_dp_port_poll',start)
poll=function(us,'extern "C" bool b5q_dp_port_poll')
helpers=us[start:end].rsplit('}',1)[0] # omit namespace closing brace
body=base+r'''
#include "B5qMax77705.h"
#include "B5qDpPdic.h"
#include "B5qDpPort.h"
#include "B5qUsbHostRole.h"
void *gHost=(void*)1;void *gHostNub=(void*)1;
B5qMax77705::Cable gAppliedCable;
int gAppliedOrientation=-1;
uint64_t ticks=0;unsigned polls=0,leaves=0,otgOff=0;bool otg=true;uint8_t cc=0x4a,cc1=1,bc=0;
struct Bus {void *lock=nullptr;uint8_t opcode=0;
 bool read(uint8_t,uint8_t reg,uint8_t &v){v=reg==0xa?cc:reg==0xb?cc1:reg==0xd?0x87:reg==8?bc:0;return true;}
 bool readBuffer(uint8_t,uint8_t reg,uint8_t *p,unsigned n){memset(p,0,n);if(reg==2)*p=0x80;else if(reg==0x51)*p=opcode;return true;}
 bool writeBuffer(uint8_t,const uint8_t *p,unsigned n){if(n>1&&p[0]==0x21)opcode=p[1];return true;}
}bus,*maxim=&bus;
bool openMaxim(){return true;}void IOLockLock(void*){}void IOLockUnlock(void*){}
void IODelay(unsigned us){ticks+=us;}void IOSleep(unsigned ms){ticks+=ms*1000;}
uint64_t mach_absolute_time(){return ticks*1000;}void absolutetime_to_nanoseconds(uint64_t n,uint64_t *out){*out=n;}
template<class... T>void IOLog(const char*,T...){ }
HELPERS
POLL
const int kRoleHost=2,kRoleNone=0,kRoleDevice=1,THREAD_UNINT=0,kSecondScale=1,kMillisecondScale=1000;
constexpr unsigned kXhciRegisterBytes=0x8000;
int gRoleWanted=2,gRoleApplied=2,gCoreRole=2;uint32_t gCableWanted=0,gCableApplied=0,gDpLanes=0;
void *gRoleLock=nullptr;bool gDeviceStackAllowed=true,gSuperSpeed=true,gPhyResetPending=false;uint32_t native_usb_stats[54]={};
namespace B5qFeatures{enum{DisplayPort=64};unsigned option(const char*,unsigned){return 1;}}
bool b5q_usb_cable_state(B5qMax77705::Cable *out){return B5qMax77705::readCable(bus,*out);}
bool b5q_usb_otg(bool on){otg=on;if(on){bc=0x80;cc1=9;}else{bc=0;cc1=1;otgOff++;}return true;}
void cableChanged(){B5qMax77705::Cable c;b5q_usb_cable_state(&c);gCableWanted=c.signature();gRoleWanted=c.role();}
bool b5q_dp_link_stop(){return true;}void b5q_dp_link_update(const B5qDpPortState*){}
void leaveRole(int){leaves++;b5q_usb_otg(false);}bool enterRole(int role){return b5q_usb_otg(role==kRoleHost);}
bool qmpInit(bool){return true;}void selectUtmiClock(){}void retryDevicePower(){}void hostStats(){}void deviceStats(){}
void clock_interval_to_deadline(unsigned,unsigned,uint64_t *p){*p=0;}
void IOLockSleepDeadline(void*,void*,uint64_t,int){if(++polls>15)throw 1;ticks+=1000000;}
using wait_result_t=int;
ROLE
int main(){
 B5qMax77705::Cable before;assert(b5q_usb_cable_state(&before));gCableApplied=gCableWanted=before.signature();gAppliedCable=before;gAppliedOrientation=before.orientation();
 b5q_usb_otg(true);B5qMax77705::Cable after;assert(b5q_usb_cable_state(&after));assert(before.signature()==after.signature());
 try{roleThread(nullptr,0);}catch(int){}
 assert(otg&&otgOff==0&&leaves==0&&dpAlt.generation==0&&dpFailed&&polls==16);
 auto signature=after.signature();bus.read(0x25,0xa,cc);cc=0x8a;B5qMax77705::Cable reverse;b5q_usb_cable_state(&reverse);assert(reverse.signature()!=signature);
 cc=0;B5qMax77705::Cable detached;b5q_usb_cable_state(&detached);assert(!detached.attached());
 puts("PASS actual TypeC/DP/role physical OTG->BC80/CC1=09 feedback:15x1s polls +3snonDPtimeout,0leaveRole/0OTGoff/stablegeneration; true orientation/detach detected");
}
'''
execute('typec-feedback',body.replace('HELPERS',helpers).replace('POLL',poll).replace('ROLE',function(q,'void roleThread(')))
# Flip5 physical touch data, timer advancement, ordered pulse and drag.
body=base+r'''
#include "B5qTouchMouse.h"
struct Event{uint32_t at;uint8_t button;};
int main(){
 for(unsigned roll:{90u,120u,150u})for(unsigned quiet:{80u,120u,180u}){
  B5qTouchMouse p;std::vector<Event> events;uint32_t now=10;uint8_t last=0;
  auto send=[&](const uint8_t *r){if(r[1]!=last){events.push_back({now,r[1]});last=r[1];}};
  int id=1,x=16000,y=16000;p.update(1,&id,&x,&y,now,false,send);
  now+=quiet;x+=roll*32767/4095;p.update(1,&id,&x,&y,now,false,send);
  now+=40;p.update(0,nullptr,nullptr,nullptr,now,false,send);assert(events.size()==1&&events[0].button==1);
  now+=31;p.advance(now,send);assert(events.size()==1);now++;p.advance(now,send);assert(events.size()==2&&events[1].button==0&&events[1].at-events[0].at>=32);
  now+=80;p.update(1,&id,&x,&y,now,false,send);assert(last==0); // second contact stays neutral until its own lift
  now+=80;p.update(1,&id,&x,&y,now,false,send);assert(last==0);
  now+=50;p.update(0,nullptr,nullptr,nullptr,now,false,send);assert(last==1);
  now+=32;p.advance(now,send);assert(last==0);
  assert(events.size()==4&&events[3].at-events[2].at>=32);
 }
 B5qTouchMouse p;uint32_t now=1;std::vector<Event> e;uint8_t last=0;auto send=[&](const uint8_t*r){if(last!=r[1])e.push_back({now,r[1]});last=r[1];};
 int ids[]={1,2},x[]={10000,20000},y[]={10000,20000};p.update(2,ids,x,y,now,false,send);now=100;p.update(1,ids,x,y,now,false,send);now=120;p.update(0,nullptr,nullptr,nullptr,now,false,send);assert(last==2);now=152;p.advance(now,send);assert(last==0&&e[1].at-e[0].at==32);
 p.update(1,ids,x,y,200,false,send);now=210;p.update(0,nullptr,nullptr,nullptr,now,false,send);assert(last==1);p.cancel(send);assert(last==0&&!p.timeout(now));
 puts("PASS Flip5 human1.5-2.5mm roll/80-180ms stationary micro-motion:9datasets,32msbuttonhold/timerrelease/two-independent-clicks/staggeredrighttap/recoverycancel ASanUBSan");
}
'''
execute('phone-click',body)
hid=(P/'NativeHidInput.cpp').read_text()
body=base+r'''
#include "B5qTouchMouse.h"
#define XNU_TARGET_OS_OSX 1
#define OSSafeReleaseNULL(p) ((p)=nullptr)
using IOReturn=int;constexpr int kIOReturnSuccess=0;
struct OSObject{};
struct IOTimerEventSource{unsigned ms=0,cancels=0;void setTimeoutMS(unsigned n){ms=n;}void cancelTimeout(){ms=0;cancels++;}};
struct NativeHidInput:OSObject{
 bool inputStopping=false,mouseEnabled=true;B5qTouchMouse pointer;IOTimerEventSource status,click;
 IOTimerEventSource *timer=&status,*clickTimer=&click;void *cachedEventDriver=nullptr;unsigned sends=0;uint8_t button=0;
 static uint32_t now;static uint32_t pointerNow(){return now;}void pointerDiagnostics(){}
 void pointerReport(const uint8_t *r){sends++;button=r[1];}
 SCHEDULE
 TICK
 STOP
};
uint32_t NativeHidInput::now=1;
int main(){NativeHidInput n;int id=1,x=10000,y=10000;
 auto send=[&](const uint8_t*r){n.pointerReport(r);};n.pointer.update(1,&id,&x,&y,1,false,send);
 n.now=100;n.pointer.update(0,nullptr,nullptr,nullptr,100,false,send);n.scheduleClick();assert(n.button==1&&n.click.ms==32);
 assert(!n.stopAction(&n,nullptr,nullptr,nullptr,nullptr));assert(n.inputStopping&&n.button==0&&!n.click.ms&&!n.status.ms&&!n.pointer.timeout(100));
 unsigned sent=n.sends;n.now=200;n.clickTick(&n,&n.click);assert(n.sends==sent&&!n.click.ms);
 puts("PASS real HID clickTick/stopAction:workloop cancellation releases heldbutton,drains pendingtimer,no late rearm/report after stop ASanUBSan");}
'''
execute('hid-stop',body.replace('SCHEDULE',function(hid,'void scheduleClick(')).replace('TICK',function(hid,'static void clickTick(')).replace('STOP',function(hid,'static IOReturn stopAction(')))
stop=function(hid,'void stop(IOService *provider) override')
assert stop.index('runAction(&NativeHidInput::stopAction')<stop.index('removeEventSource(clickTimer)')

# RTSOFF/ERST lie past the capability/operational4KiB page on DWC3.
# The production diagnostic must use the same32KiB register mapping as xHCI.
assert 'mapRegion(gXhciRegs,kCore,kXhciRegisterBytes)'in q.replace(' ','')
assert 'constexpr unsigned kXhciRegisterBytes=0x8000;'in q
assert 'rt+0x40/4<kXhciRegisterBytes/4'in q
