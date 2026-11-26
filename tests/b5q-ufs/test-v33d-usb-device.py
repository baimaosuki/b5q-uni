#!/usr/bin/env python3
"""Execute the production cable retry and role/orientation paths, not copies."""
from pathlib import Path
R=Path(__file__).resolve().parents[2];P=R/'UniXNU-b5q/package'
s=(R/'tests/b5q-ufs/test-v33b-causal.py').read_text();ns={'__file__':str(R/'tests/b5q-ufs/test-v33b-causal.py')}
exec(compile(s[:s.index('# Run the actual')],'<ASan-host-runner>','exec'),ns)
q=(P/'QcomDwc3.cpp').read_text();function=ns['function'];execute=ns['execute'];base=ns['base']
body=base+r'''
using IOReturn=int;constexpr int kIOPMAckImplied=0,kIOPMNotYetInitialized=8;
#define IOLog(...) ((void)0)
uint32_t native_usb_stats[54]={},gXdciCableCalls=0,gDevicePowerOnAtAttach=0;
bool gDevicePowerAcknowledged=false,gDeviceStackAllowed=true,gDmaReady=true;
const int kRoleDevice=1,kRoleHost=2,kRoleNone=0;int gRoleApplied=1,gRoleWanted=1;
struct Controller{
 std::vector<int> results{8,8,0};unsigned calls=0;int getPowerState(){return 0;}
 int changePowerStateTo(unsigned target){assert(target==0||target==4);return results.at(calls++);}
 CABLE
}device,*gController=&device;
RETRY
int main(){
 native_usb_stats[20]=device.cable(true);assert(native_usb_stats[20]==8&&!gDevicePowerAcknowledged);
 retryDevicePower();assert(device.calls==2&&native_usb_stats[20]==8);
 retryDevicePower();assert(device.calls==3&&!native_usb_stats[20]&&gDevicePowerAcknowledged);
 for(unsigned i=0;i<15;i++)retryDevicePower();assert(device.calls==3);
 gDevicePowerAcknowledged=false;native_usb_stats[12]=1;native_usb_stats[20]=1;retryDevicePower();assert(device.calls==3);
 native_usb_stats[12]=0;native_usb_stats[20]=8;gRoleWanted=kRoleNone;retryDevicePower();assert(device.calls==3);
 gRoleWanted=kRoleHost;retryDevicePower();assert(device.calls==3);
 gRoleWanted=kRoleDevice;gRoleApplied=kRoleHost;retryDevicePower();assert(device.calls==3);
 gRoleApplied=kRoleDevice;gDeviceStackAllowed=false;retryDevicePower();assert(device.calls==3);
 gDeviceStackAllowed=true;gDmaReady=false;retryDevicePower();assert(device.calls==3);
 gDmaReady=true;gController=nullptr;retryDevicePower();assert(device.calls==3);
 puts("PASS actual cable/retry:PM8->8->0 stops after ACK0; powerOn observed stop; unplug/Host/transition/DMA guards; no uninitialized power retry lost");
}
'''
execute('v33d-device-power',body.replace('CABLE',function(q,'IOReturn cable(')).replace('RETRY',function(q,'void retryDevicePower(')))
body=base+r'''
#include "B5qMax77705.h"
#include "B5qDpPort.h"
#include "B5qUsbHostRole.h"
using wait_result_t=int;
template<class... T>void IOLog(const char*,T...){ }
void *gHost=nullptr;void *gHostNub=nullptr;B5qMax77705::Cable gAppliedCable;int gAppliedOrientation=-1;
const int kRoleHost=2,kRoleNone=0,kRoleDevice=1,THREAD_UNINT=0,kSecondScale=1,kMillisecondScale=1000;
int gRoleWanted=1,gRoleApplied=0,gCoreRole=0;uint32_t gCableWanted=1,gCableApplied=0,gDpLanes=0;
void *gRoleLock=nullptr;bool gDeviceStackAllowed=true,gSuperSpeed=false,gPhyResetPending=false;uint32_t native_usb_stats[54]={};
unsigned polls=0,qmps=0,enters=0,retries=0;int orientation=0;
namespace B5qFeatures{enum{DisplayPort=64};unsigned option(const char*,unsigned){return 1;}}
void IOLockLock(void*){}void IOLockUnlock(void*){}void IOSleep(unsigned){}
bool b5q_dp_port_poll(B5qDpPortState*p){p->configured=1;p->lanes=2;return true;}
bool b5q_usb_cable_state(B5qMax77705::Cable *c){c->cc0=orientation?0x8a:0x4a;return true;}
bool b5q_usb_otg(bool){return true;}bool b5q_dp_link_stop(){return true;}void b5q_dp_link_update(const B5qDpPortState*){}
void leaveRole(int){}bool qmpInit(bool reverse){assert(reverse==bool(orientation));qmps++;return true;}
void selectUtmiClock(){}bool superSpeedInit(){qmps++;native_usb_stats[34]=orientation;return true;}
FOLLOW
bool enterRole(int){enters++;followOrientation();return true;}
void cableChanged(){}void retryDevicePower(){retries++;}void hostStats(){}void deviceStats(){}
void clock_interval_to_deadline(unsigned,unsigned,uint64_t*p){*p=0;}
void IOLockSleepDeadline(void*,void*,uint64_t,int){if(++polls>3)throw 1;}
ROLE
int main(){for(orientation=0;orientation<2;orientation++){
 gRoleApplied=0;gCableApplied=0;gDpLanes=0;gSuperSpeed=false;native_usb_stats[34]=~0u;polls=qmps=enters=retries=0;
 try{roleThread(nullptr,0);}catch(int){}
 assert(qmps==1&&enters==1&&retries==3&&native_usb_stats[34]==unsigned(orientation));
 }puts("PASS actual roleThread + followOrientation:normal/reverse QMP exactlyonce; periodic retry invoked; no immediately repeated PHY reset");}
'''
execute('v33d-qmp-role',body.replace('FOLLOW',function(q,'bool followOrientation(')).replace('ROLE',function(q,'void roleThread(')))
assert 'static volatile bool gDeviceStackAllowed = false;'in q
assert '"configuration-string",config'in q
assert q.index('controller->registerService();')>q.index('gController=controller;')
publish=function(q,'extern "C" void qcom_dwc3_publish(')
assert 'QcomDwc3Nub::route(nub);'not in publish
enter=function(q,'bool enterRole(');device=enter[enter.index('} else {'):]
assert device.index('QcomDwc3Nub::route(gDeviceNub)')<device.index('__atomic_store_n(&gDeviceStackAllowed,true')<device.index('setProperty("AppleUSBCableType"')<device.index('gController->cable(true)')
for field in ['PORTSC1=','PORTSC2=','PORTPMSC1=','PORTPMSC2=','ERDP=','GUSB2PHYCFG=','GUSB3PIPECTL=','GUCTL1=']:assert field in q
assert 'hostCheckpoint("read64");'in q and 'hostCheckpoint("write64");'in q
assert 'hostCheckpoint("before-power-state",true,false);'in q and 'hostCheckpoint("poll",false,true);'in q
assert '(port&3u)==3u&&(port&0x1e0u)==0x60u' in q
print('PASS publication/configuration and host diagnostic source contracts; actual ABI compilation and original binary evidence checked separately')
