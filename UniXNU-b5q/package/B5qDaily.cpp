/* SPDX-License-Identifier: BSD-2-Clause-Patent */
/* Samsung P4A transport with the upstream IOPMPowerSource publication API.
 * This worker does not initialize a second SE8 engine or modify charging. */
#include <IOKit/IOLib.h>
#include <IOKit/IOPlatformExpert.h>
#include <libkern/OSKextLib.h>
#include <mach/kmod.h>
#include <IOKit/pwr_mgt/IOPMPowerSource.h>
#include <libkern/c++/OSSymbol.h>
#include <libkern/c++/OSNumber.h>
#include <libkern/c++/OSBoolean.h>
#include <kern/thread.h>
#include <pexpert/pexpert.h>
#include "B5qFuelGauge.h"
#include "B5qFeatures.h"
#include "B5qMax77705.h"
extern "C" bool b5q_battery_snapshot(B5qFuelGauge::Raw *,B5qMax77705::Cable *,uint8_t *);
extern kmod_info_t g_kernel_kmod_info;
extern "C" void b5q_daily_static_init(void) __asm__("__GLOBAL__sub_I_B5qDaily.cpp");
class B5qBattery:public IOPMPowerSource {
    OSDeclareDefaultStructors(B5qBattery)
    bool published=false;
    void number(const char *name,int32_t value) {
        const OSSymbol *key=OSSymbol::withCString(name);
        OSNumber *object=OSNumber::withNumber(uint32_t(value),32);
        if(key&&object)setPSProperty(key,object);
        OSSafeReleaseNULL(key);OSSafeReleaseNULL(object);
    }
    void flag(const char *name,bool value) {
        const OSSymbol *key=OSSymbol::withCString(name);
        if(key)setPSProperty(key,value?kOSBooleanTrue:kOSBooleanFalse);
        OSSafeReleaseNULL(key);
    }
public:
    void publishSample(const B5qFuelGauge::Sample &s,bool external,unsigned state) {
        setBatteryInstalled(s.present);
        setExternalConnected(external);setExternalChargeCapable(external);
        setIsCharging(s.present&&external&&state<=2);
        setCurrentCapacity(s.permille/10);setMaxCapacity(100);
        setVoltage(s.millivolts);setAmperage(s.milliamps);
        setCycleCount(s.cycles);setTimeRemaining(0xffff);
        setAtWarnLevel(s.present&&s.permille<=100);
        setAtCriticalLevel(s.present&&s.permille<=50);
        flag("FullyCharged",s.present&&external&&(state==3||state==4));
        const int32_t centiKelvin=int32_t(s.temperatureDeciC)*10+27315;
        if(centiKelvin>=0)number("Temperature",uint32_t(centiKelvin));
        number("AppleRawCurrentCapacity",s.remainingMah);
        number("AppleRawMaxCapacity",s.fullMah);number("DesignCapacity",s.designMah);
        if(!published){published=true;registerService();}
        updateStatus();
    }
};
OSDefineMetaClassAndStructors(B5qBattery,IOPMPowerSource)
namespace {
void batteryWorker(void *,wait_result_t) {
    thread_set_thread_name(current_thread(),"B5qBattery");
    B5qBattery *source=nullptr;bool published=false;uint32_t samples=0,failures=0;
    for(;;) {
        B5qFuelGauge::Raw raw{};B5qMax77705::Cable cable{};uint8_t detail=0;
        if(b5q_battery_snapshot(&raw,&cable,&detail)) {
            const auto s=B5qFuelGauge::decode(raw);
            if(!source) {
                source=OSTypeAlloc(B5qBattery);
                if(source&&!source->init()){source->release();source=nullptr;}
                if(source&&!source->attach(IOService::getPlatform())){source->release();source=nullptr;}
            }
            if(source) {
                source->publishSample(s,cable.power()==1,detail&15);published=true;
            }
            if(++samples%6==1)IOLog("B5qBattery: samples=%u present=%u soc=%u mv=%u ma=%d temp_dC=%d external=%u charging=%u detail=%02x published=%u\n",
                samples,s.present,s.permille,s.millivolts,s.milliamps,s.temperatureDeciC,
                cable.power()==1,s.present&&cable.power()==1&&(detail&15)<=2,detail,published);
        }else if(++failures%6==1)IOLog("B5qBattery: sample-failed=%u; retained last valid reading\n",failures);
        IOSleep(5000);
    }
}
void launch(void (*entry)(void *,wait_result_t),const char *name) {
    thread_t thread=nullptr;
    if(kernel_thread_start(entry,nullptr,&thread)==KERN_SUCCESS)thread_deallocate(thread);
    else IOLog("B5qDaily: %s thread allocation failed\n",name);
}
}
extern "C" void b5q_daily_probe() {
    static uint32_t once;
    if(__atomic_exchange_n(&once,1u,__ATOMIC_ACQ_REL))return;
    if(B5qFeatures::option("battery",B5qFeatures::Battery)==1) {
        void *handle=OSMetaClass::preModLoad(g_kernel_kmod_info.name);
        if(handle){b5q_daily_static_init();auto status=OSMetaClass::postModLoad(handle);if(!status)launch(batteryWorker,"battery");else IOLog("B5qDaily: stage=battery-metaclass-post result=%x\n",status);}
        else IOLog("B5qDaily: stage=battery-metaclass-pre result=failed\n");
    }
    IOLog("B5qDaily: lid=removed cover-display=disabled inner-panel-only=1\n");
}
