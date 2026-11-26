#!/usr/bin/env python3
"""Replay production role/power/orientation functions; no hardware MMIO."""
from pathlib import Path
import subprocess,tempfile,re
R=Path(__file__).resolve().parents[2]
source=(R/'UniXNU-b5q/package/QcomDwc3.cpp').read_text()
def function(signature):
 start=source.index(signature);first=source.index('{',start);end=first+1;depth=1
 while depth:depth+=(source[end]=='{')-(source[end]=='}');end+=1
 return source[start:end]
assert source.count('OSData::withBytes(&busNumber,sizeof(busNumber))')==2
assert not re.search(r'11\s*\*\s*0x1000',source)
assert not re.search(r'0x15000000|SmmuBypass|ArmSmmu4KLive',re.sub(r'//[^\n]*','',source))
assert 'if(!entered)IOSleep(1000)' in source
harness=r'''
#include "B5qMax77705.h"
#include <cassert>
#include <cstdio>
#include <cstdint>
#include <vector>
enum {kRoleNone,kRoleDevice,kRoleHost};
constexpr uint32_t kGctlDisableClockGating=1u;
constexpr uint32_t kUsb2EnableLpm=1u<<8,kUsb2SuspendPhy=1u<<6,kUsb3SuspendPhy=1u<<17;
constexpr uint32_t kGuctlSprsCtrlTransEn=1u<<17,kGuctl1Host=(1u<<21)|(1u<<8),kGuctl2Host=1u<<16;
bool gDmaReady=true,gSuperSpeed=false,gDeviceStackAllowed=false;
unsigned gDpLanes=0;bool gPhyResetPending=false,gDevicePowerAcknowledged=false;uint32_t gDevicePowerOnAtAttach=0;
int gCoreRole=kRoleDevice;unsigned powerCalls=0,hostCalls=0,deviceCalls=0,qmpCalls=0,utmi=0,eusbInit=0;
bool boost=false,powerFailure=false,phyFailure=false,hostFailure=false,qmpReverse=false;
uint32_t native_usb_stats[54]={},registers[1024]={};
struct {uint32_t *va=registers;} gGlobals;
B5qMax77705::Cable current;
B5qMax77705::Cable gAppliedCable;
int gAppliedOrientation=-1;
struct QcomDwc3Nub {static void route(void*){}};
struct Controller {int cable(bool on){assert(on);++deviceCalls;return 0;}} controller;
Controller *gController=&controller;void *gDeviceNub=nullptr,*gHost=nullptr;
struct IOService {
 static IOService *getResourceService(){static IOService x;return &x;}
 void setProperty(const char*,const char*){}
};
bool b5q_usb_cable_state(B5qMax77705::Cable *out){*out=current;return current.valid;}
bool b5q_usb_otg(bool on){++powerCalls;if(on&&powerFailure)return false;boost=on;return true;}
bool repeater(bool,bool){return !phyFailure;}
void barrier(){}void IOSleep(unsigned){}void IODelay(unsigned us){assert(us==100);}void phyInit(){++eusbInit;}
void restoreHostGlobals(){registers[0x110/4]|=1;registers[0x200/4]&=~((1u<<6)|(1u<<8));registers[0x2c0/4]&=~(1u<<17);registers[0x12c/4]|=1u<<17;registers[0x11c/4]=(registers[0x11c/4]&~(7u<<21))|(1u<<21)|(1u<<8);registers[0x60c/4]|=1u<<16;}
template<class... T>void IOLog(const char*,T...){}
bool qmpInit(bool reverse){++qmpCalls;qmpReverse=reverse;return !phyFailure;}
void selectUtmiClock(){++utmi;}
void vbusOverride(bool on){assert(!on);}
void enterHost(){++hostCalls;gHost=hostFailure?nullptr:&controller;}
'''
harness+='\n'.join(function(x)for x in ['bool superSpeedInit()','bool followOrientation()','bool setCoreRole(int role,bool forceReset=false)','bool enterRole(int role)'])
harness+=r'''
void reset(){boost=false;gHost=nullptr;gDmaReady=true;gSuperSpeed=false;gDeviceStackAllowed=false;gCoreRole=kRoleDevice;powerFailure=phyFailure=hostFailure=false;powerCalls=hostCalls=deviceCalls=qmpCalls=utmi=eusbInit=0;}
int main(){
 for(unsigned power:{1u,2u})for(unsigned pd:{0u,128u})for(unsigned pin:{1u,2u}){
  reset();current={uint8_t(power|(pin<<6)),0,uint8_t(pd),0x80,true};
  const int role=current.role();assert(enterRole(role));
  assert(boost==(power==2)&&hostCalls==unsigned(role==kRoleHost)&&deviceCalls==unsigned(role==kRoleDevice));
  assert(gDeviceStackAllowed==(role==kRoleDevice)&&qmpCalls==1&&qmpReverse==(pin==2)&&eusbInit==0);
 }
 reset();current={0x81,0,0x80,0x80,true};powerFailure=true;
 assert(enterRole(kRoleHost)&&!boost&&hostCalls==1); // External powered Sink+DFP never requests a boost.
 reset();current={0x82,0,0x80,0,true};powerFailure=true;
 assert(!enterRole(kRoleHost)&&!hostCalls&&!qmpCalls);
 reset();current={0x81,0,0x80,0x80,true};phyFailure=true;
 assert(!enterRole(kRoleHost)&&!hostCalls&&!boost&&utmi==1);
 reset();current={0x82,0,0x80,0,true};hostFailure=true;
 assert(!enterRole(kRoleHost)&&!boost);
 reset();current={0x81,2,0x80,0x80,true};assert(!enterRole(kRoleHost)&&!powerCalls&&!hostCalls);
 reset();current={};assert(!enterRole(kRoleHost)&&!powerCalls&&!hostCalls);
 reset();current={0x81,0,0x80,0x80,true};gDmaReady=false;
 assert(enterRole(kRoleHost)&&!boost&&!hostCalls);assert(enterRole(kRoleDevice)&&!deviceCalls);
 for(unsigned pin:{0u,3u}){
  reset();current={uint8_t(1|(pin<<6)),0,0x80,0x80,true};
  assert(!superSpeedInit()&&!qmpCalls&&native_usb_stats[34]==~0u);
 }
 // Opposite plug orientation on a reconnect is observed from CC, not GPIO.
 reset();current={0x41,0,0x80,0x80,true};followOrientation();assert(qmpCalls==1&&!qmpReverse);
 current.cc0=0x81;followOrientation();assert(qmpCalls==2&&qmpReverse);
 gDpLanes=4;followOrientation();assert(qmpCalls==2&&utmi==1);
 gDpLanes=0;gSuperSpeed=false;followOrientation();assert(qmpCalls==3&&qmpReverse);
 puts("PASS production P1:CC1/CC2,Sink+DFP externalHub,Source+UFP,roles,boost/read/PHY/XHCI failures,firmwareDMA gate,unknownCC UTMI,bus-number u32");
}
'''
with tempfile.TemporaryDirectory(prefix='b5q-usb-p1-')as td:
 for name,text in [('roles',harness)]:
  cpp=Path(td)/(name+'.cpp');cpp.write_text(text);exe=cpp.with_suffix('')
  subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=address,undefined','-I',str(R/'UniXNU-b5q/package'),str(cpp),'-o',str(exe)],check=True)
  subprocess.run([str(exe)],check=True)
 exe=Path(td)/'status'
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I',str(R/'UniXNU-b5q/package'),str(R/'tests/b5q-ufs/test-max77705-drp.cpp'),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True)
