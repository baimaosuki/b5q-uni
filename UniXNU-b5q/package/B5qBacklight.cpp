/* SPDX-License-Identifier: BSD-2-Clause-Patent */
/* The upstream ShengBacklight IOKit publication/request interface, with the
 * Samsung inner panel's normal candela table and command-FIFO transport.
 * No KTZ8866/I2C backlight hardware, vtable copies or unverified HBM writes. */
#include <IOKit/IOLib.h>
#include "B5qFeatures.h"
#include <IOKit/IODeviceMemory.h>
#include <IOKit/IOPlatformExpert.h>
#include <IOKit/IOWorkLoop.h>
#include <IOKit/IOTimerEventSource.h>
#include <libkern/c++/OSDictionary.h>
#include <libkern/c++/OSNumber.h>
#include <libkern/c++/OSData.h>
#include <libkern/c++/OSSymbol.h>
#include <libkern/OSKextLib.h>
#include <mach/kmod.h>
#include <pexpert/pexpert.h>
#include "B5qPanelCommand.h"
#include "B5qPanelLevels.h"
extern kmod_info_t g_kernel_kmod_info;
extern "C" void b5q_backlight_static_init(void) __asm__("__GLOBAL__sub_I_B5qBacklight.cpp");
namespace {
volatile uint32_t gClosed;
IOTimerEventSource *gRequestTimer;
const OSMetaClass *gBacklightClass;
}
class B5qBacklight:public IOService {
    OSDeclareDefaultStructors(B5qBacklight)
    IOMemoryMap *mapping=nullptr;
    volatile uint32_t *regs=nullptr;
    IOWorkLoop *loop=nullptr;
    IOTimerEventSource *timer=nullptr;
    volatile uint32_t requested=B5qPanelLevels::maximum;
    uint32_t written=~0u,failures=0;
    bool published=false;
    void publish(uint32_t level) {
        OSDictionary *brightness=OSDictionary::withCapacity(3),*parameters=OSDictionary::withCapacity(1);
        OSNumber *min=OSNumber::withNumber(0ULL,32),*max=OSNumber::withNumber(uint64_t(B5qPanelLevels::maximum),32);
        OSNumber *value=OSNumber::withNumber(uint64_t(level),32);
        if(brightness&&parameters&&min&&max&&value) {
            brightness->setObject("min",min);brightness->setObject("max",max);brightness->setObject("value",value);
            parameters->setObject("brightness",brightness);setProperty("IODisplayParameters",parameters);
        }
        OSSafeReleaseNULL(min);OSSafeReleaseNULL(max);OSSafeReleaseNULL(value);
        OSSafeReleaseNULL(brightness);OSSafeReleaseNULL(parameters);
    }
    void calibration() {
        // Values come from the Samsung normal table, not a measured panel
        // calibration. Keep that provenance explicit in the registry.
        const int32_t table[]={1<<16,120<<16,500<<16};
        if(auto *data=OSData::withBytes(table,sizeof(table))) {
            setProperty("backlight-marketing-table",data);data->release();
        }
        if(auto *data=OSData::withBytes(&table[2],sizeof(table[2]))) {
            setProperty("LmaxProduct",data);data->release();
        }
        setProperty("LminProduct",uint64_t(1),32);setProperty("LmidProduct",uint64_t(120),32);
        OSDictionary *cal=OSDictionary::withCapacity(6);
        if(cal) {
            const char *names[]={"lMinProduct","lMidProduct","lMaxProduct","lMinPanel","lMidPanel","lMaxPanel"};
            for(unsigned i=0;i<6;++i) {
                OSNumber *n=OSNumber::withNumber(uint64_t(uint32_t(table[i%3])),32);
                if(n){cal->setObject(names[i],n);n->release();}
            }
            setProperty("backlight-calibration-parameters",cal);cal->release();
        }
        setProperty("B5qBrightnessSource","Samsung normal candela table revA; unmeasured");
    }
    static void tick(OSObject *owner,IOTimerEventSource *) {
        auto *self=static_cast<B5qBacklight*>(owner);
        const uint32_t wanted=__atomic_load_n(&self->requested,__ATOMIC_ACQUIRE);
        const uint32_t target=__atomic_load_n(&gClosed,__ATOMIC_ACQUIRE)?0:wanted;
        if(self->written==target)return;
        const uint32_t raw=target?B5qPanelLevels::normal[target-1].raw:0;
        const auto result=B5qPanelCommand::brightness(
            [&](uint32_t reg){return self->regs[reg/4];},
            [&](uint32_t reg,uint32_t value){self->regs[reg/4]=value;__asm__ volatile("dsb sy":::"memory");},
            [](unsigned us){IODelay(us);},raw);
        IOLog("B5qBacklight: level=%u raw=%u closed=%u completion=%u failures=%u\n",
            target,raw,__atomic_load_n(&gClosed,__ATOMIC_RELAXED),unsigned(result),self->failures);
        if(result!=B5qPanelCommand::Result::Ok) {
            if(++self->failures<=3)self->timer->setTimeoutMS(100);
            return;
        }
        self->written=target;self->failures=0;self->publish(wanted);
        if(!self->published){self->published=true;self->registerService();}
    }
public:
    bool startPanel() {
        auto *memory=IODeviceMemory::withRange(0xae94000,0x1000);
        mapping=memory?memory->map(kIOMapAnywhere|kIOMapInhibitCache):nullptr;
        OSSafeReleaseNULL(memory);
        if(!mapping){IOLog("B5qBacklight: stage=map result=failed base=ae94000\n");return false;}
        regs=reinterpret_cast<volatile uint32_t*>(mapping->getVirtualAddress());
        if(!(regs[B5qPanelCommand::control/4]&1)){IOLog("B5qBacklight: stage=control result=disabled reg=%08x\n",regs[B5qPanelCommand::control/4]);return false;}
        loop=IOWorkLoop::workLoop();timer=IOTimerEventSource::timerEventSource(this,tick);
        if(!loop||!timer||loop->addEventSource(timer)!=kIOReturnSuccess){IOLog("B5qBacklight: stage=workloop-timer result=failed\n");return false;}
        setName("B5qBacklight");setProperty("backlight-control",true);calibration();
        // Successful FIFO completion precedes publication. A controller
        // failure never invents a brightness reading or blocks system boot.
        __atomic_store_n(&gRequestTimer,timer,__ATOMIC_RELEASE);timer->setTimeoutMS(1);return true;
    }
    void free() override {
        if(timer){timer->cancelTimeout();if(loop)loop->removeEventSource(timer);}
        OSSafeReleaseNULL(timer);OSSafeReleaseNULL(loop);OSSafeReleaseNULL(mapping);
        IOService::free();
    }
    IOReturn setProperties(OSObject *object) override {
        auto *dict=OSDynamicCast(OSDictionary,object);if(!dict)return kIOReturnBadArgument;
        uint32_t level;
        if(auto *n=OSDynamicCast(OSNumber,dict->getObject("brightness-nits")))
            level=B5qPanelLevels::forNits(int32_t(n->unsigned32BitValue()));
        else if(auto *n=OSDynamicCast(OSNumber,dict->getObject("brightness"))) {
            const int32_t value=int32_t(n->unsigned32BitValue());
            level=value<0?0:uint32_t(value)>B5qPanelLevels::maximum?B5qPanelLevels::maximum:uint32_t(value);
        }else return kIOReturnSuccess;
        __atomic_store_n(&requested,level,__ATOMIC_RELEASE);timer->setTimeoutUS(1);
        return kIOReturnSuccess;
    }
};
// The upstream arm64e conformance mechanism uses a real override. It never
// reads, copies or patches a vtable or embeds an iPadOS discriminator/length.
B5qBacklight::MetaClass B5qBacklight::gMetaClass;
const OSMetaClass *const B5qBacklight::metaClass=&B5qBacklight::gMetaClass;
const OSMetaClass *const B5qBacklight::superClass=&IOService::gMetaClass;
B5qBacklight::B5qBacklight(const OSMetaClass *meta):IOService(meta){}
B5qBacklight::~B5qBacklight(){}
const OSMetaClass *B5qBacklight::getMetaClass()const{return gBacklightClass?gBacklightClass:&gMetaClass;}
OSMetaClassConstructorInit(B5qBacklight,IOService,)
OSDefineDefaultStructors(B5qBacklight,IOService)

extern "C" void b5q_backlight_lid(bool closed) {
    __atomic_store_n(&gClosed,closed?1u:0u,__ATOMIC_RELEASE);
    if(auto *timer=__atomic_load_n(&gRequestTimer,__ATOMIC_ACQUIRE))timer->setTimeoutUS(1);
}
extern "C" void b5q_backlight_probe() {
    if(B5qFeatures::option("backlight",B5qFeatures::Backlight)!=1)return;
    static uint32_t once;if(__atomic_exchange_n(&once,1u,__ATOMIC_ACQ_REL))return;
    const OSSymbol *name=OSSymbol::withCString("AppleARMBacklight");
    gBacklightClass=name?OSMetaClass::getMetaClassWithName(name):nullptr;OSSafeReleaseNULL(name);
    if(!gBacklightClass){IOLog("B5qBacklight: original AppleARMBacklight metaclass unavailable\n");return;}
    void *handle=OSMetaClass::preModLoad(g_kernel_kmod_info.name);
    if(!handle){IOLog("B5qBacklight: stage=metaclass-pre result=failed\n");return;}
    b5q_backlight_static_init();auto meta=OSMetaClass::postModLoad(handle);if(meta){IOLog("B5qBacklight: stage=metaclass-post result=%x\n",meta);return;}
    auto *service=OSTypeAlloc(B5qBacklight);
    if(!service||!service->init()){IOLog("B5qBacklight: stage=allocate-init result=failed\n");OSSafeReleaseNULL(service);return;}
    if(!service->attach(IOService::getPlatform())){IOLog("B5qBacklight: stage=attach result=failed\n");service->release();return;}
    if(!service->startPanel()){IOLog("B5qBacklight: stage=panel-start result=failed\n");service->detach(IOService::getPlatform());service->release();return;}
    service->release();
}
