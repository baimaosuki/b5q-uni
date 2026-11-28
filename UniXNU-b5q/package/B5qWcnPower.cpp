/* SPDX-License-Identifier: BSD-2-Clause-Patent */
/* Board-only b5q.dts WCN supplies; transport/core remain shared components. */
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceMemory.h>
#include <sys/errno.h>
#include "B5qWcnPower.h"
#include "B5qWcnPowerCore.h"
#include "QcomRpmh.h"
#include "AppsSmmuLock.h"
namespace {
IOLock *lock;
B5qWcn::Power power;
struct Window {
    IOMemoryMap *mapping=nullptr;volatile uint32_t *va=nullptr;
    bool open(uint64_t base,size_t bytes) {
        if(va)return true;
        auto *m=IODeviceMemory::withRange(base,bytes);
        mapping=m?m->map(kIOMapAnywhere|kIOMapInhibitCache):nullptr;
        OSSafeReleaseNULL(m);
        va=mapping?reinterpret_cast<volatile uint32_t*>(mapping->getVirtualAddress()):nullptr;
        return va;
    }
    ~Window(){OSSafeReleaseNULL(mapping);}
};
Window rsc,tlmm;
QcomRpmhResource resources[5],xo;
bool prepared;
void barrier(){__asm__ volatile("dsb sy":::"memory");}
bool ensureLock() {
    if(__atomic_load_n(&lock,__ATOMIC_ACQUIRE))return true;
    auto *candidate=IOLockAlloc();if(!candidate)return false;
    IOLock *expected=nullptr;
    if(!__atomic_compare_exchange_n(&lock,&expected,candidate,false,__ATOMIC_RELEASE,__ATOMIC_ACQUIRE))IOLockFree(candidate);
    return true;
}
bool prepare() {
    if(prepared)return true;
    Window cmd;
    if(!cmd.open(0x81c60000,0x20000) || !rsc.open(0x17a20000,0x10000) || !tlmm.open(0xf100000,0x100000))return false;
    auto *copy=static_cast<uint8_t*>(IOMallocData(0x20000));if(!copy)return false;
    for(unsigned i=0;i<0x20000;i+=4){uint32_t v=cmd.va[i/4];memcpy(copy+i,&v,4);}
    bool ok=true;
    for(unsigned i=0;i<5;i++)if(qcom_cmd_db_find(copy,0x20000,B5qWcn::rails[i].name,resources+i))ok=false;
    if(qcom_cmd_db_find(copy,0x20000,"xo.lvl",&xo))ok=false;
    IOFreeData(copy,0x20000);prepared=ok;return ok;
}
bool send(const QcomRscLayout &layout,uint32_t address,uint32_t value) {
    constexpr unsigned tcs=0,base=0xd00;
    QcomRpmhWrite writes[16];
    // Serialize this active TCS with the existing USB RPMh owner. The mutex
    // name is historical: AppsSmmuLock performs no SMMU register access.
    const unsigned n=qcom_rpmh_active_request(&layout,tcs,&address,&value,1,writes,16);
    if(!n)return false;
    rsc.va[base/4]|=1u<<tcs;barrier();
    for(unsigned i=0;i<n;i++){rsc.va[(base+writes[i].offset)/4]=writes[i].value;barrier();}
    unsigned us=0;uint32_t status=0;
    for(;us<20000;us+=10){status=rsc.va[(base+layout.irq_status)/4];if(status&(1u<<tcs))break;IODelay(10);}
    const unsigned finish=qcom_rpmh_finish(&layout,tcs,writes,16);
    for(unsigned i=0;i<finish;i++)rsc.va[(base+writes[i].offset)/4]=writes[i].value;
    barrier();
    if(us==20000)IOLog("B5qWcn: RPMh completion timeout addr=%08x data=%u irq=%08x\n",address,value,status);
    return us<20000;
}
bool vote(unsigned index,const B5qWcn::Rail &rail) {
    const QcomRscLayout layout=qcom_rsc_layout(rsc.va[0]);
    bool ok=send(layout,resources[index].address+8,7) &&
        send(layout,resources[index].address,rail.mv) && send(layout,resources[index].address+4,1);
    IOLog("B5qWcn: rail=%s mv=%u address=%08x completion=%u\n",rail.name,rail.mv,resources[index].address,ok);
    return ok;
}
}
extern "C" int b5q_wcn_power_get(unsigned radio) {
    if(radio>1)return EINVAL;
    if(!ensureLock())return ENOMEM;
    IOLockLock(lock);
    bool ok=prepare();
    if(ok){AppsSmmuLock arb;ok=arb.ready() && send(qcom_rsc_layout(rsc.va[0]),xo.address,3) && power.get(radio,vote);}
    IOLog("B5qWcn: get radio=%u owners=%u refs=%u/%u/%u/%u/%u retained=%x result=%u\n",radio,power.owners,
        power.refs[0],power.refs[1],power.refs[2],power.refs[3],power.refs[4],power.retained,ok);
    IOLockUnlock(lock);return ok?0:EIO;
}
extern "C" int b5q_wcn_power_put(unsigned radio) {
    if(radio>1)return EINVAL;
    if(!ensureLock())return ENOMEM;
    IOLockLock(lock);bool ok=power.put(radio);
    IOLog("B5qWcn: put radio=%u owners=%u retained=%x floor=firmware-and-usb\n",radio,power.owners,power.retained);
    IOLockUnlock(lock);return ok?0:EINVAL;
}
extern "C" unsigned b5q_wcn_power_owners() {
    if(!ensureLock())return 0;
    IOLockLock(lock);unsigned owners=power.owners;IOLockUnlock(lock);return owners;
}
extern "C" int b5q_wcn_pcie_vote() {
    if(!ensureLock())return ENOMEM;
    IOLockLock(lock);bool ok=prepare();
    Window cmd;QcomRpmhResource phy[2],bcm;
    if(ok)ok=cmd.open(0x81c60000,0x20000);
    auto *copy=ok?static_cast<uint8_t*>(IOMallocData(0x20000)):nullptr;
    if(!copy)ok=false;
    if(ok) {
        for(unsigned i=0;i<0x20000;i+=4){uint32_t v=cmd.va[i/4];memcpy(copy+i,&v,4);}
        ok=!qcom_cmd_db_find(copy,0x20000,"ldoe1",phy) &&
           !qcom_cmd_db_find(copy,0x20000,"ldoe3",phy+1) &&
           !qcom_cmd_db_find(copy,0x20000,"SN7",&bcm);
    }
    if(copy)IOFreeData(copy,0x20000);
    if(ok) {
        AppsSmmuLock arb;ok=arb.ready();
        const QcomRscLayout layout=qcom_rsc_layout(rsc.va[0]);
        const unsigned mv[]={880,1200};
        for(unsigned i=0;ok&&i<2;i++)ok=send(layout,phy[i].address+8,7) &&
            send(layout,phy[i].address,mv[i]) && send(layout,phy[i].address+4,1);
        // Samsung PCIe0 icc_path and cmd-db BCM aux data, same calculation
        // as mainline WifiProbe; never guess the BCM command address.
        if(ok && bcm.level_count>=3 && bcm.levels[2]) {
            uint64_t unit=bcm.levels[0]|uint64_t(bcm.levels[1])<<16;
            if(!unit)ok=false;
            else {
                uint64_t value=(((2000000ULL*bcm.levels[2]+15)/16)*1000+unit-1)/unit;
                uint32_t vote=value<1?1:value>0x3fff?0x3fff:uint32_t(value);
                ok=send(layout,bcm.address,(1u<<30)|(1u<<29)|(vote<<14)|vote);
            }
        }else ok=false;
    }
    IOLog("B5qWcn: PCIe PHY880/1200mV+SN7 completion=%u\n",ok);
    IOLockUnlock(lock);return ok?0:EIO;
}
extern "C" int b5q_wcn_radio_enable(unsigned radio,int enabled) {
    if(radio>1)return EINVAL;
    if(!ensureLock())return ENOMEM;
    IOLockLock(lock);
    bool ok=prepared && (!enabled || (power.owners&(1u<<radio)));
    if(ok)ok=B5qWcn::enable(radio,enabled!=0,
        [](unsigned p){return (tlmm.va[(p*0x1000+4)/4]&1u)!=0;},
        [](unsigned p,bool on){
            tlmm.va[(p*0x1000+4)/4]=on?2:0;
            // BT_EN default pinctrl: GPIO output, 2mA, pulldown.
            uint32_t cfg=p==81?0x201u:(tlmm.va[p*0x1000/4]&~0x23cu)|0x200u;
            tlmm.va[p*0x1000/4]=cfg;barrier();
        },[](unsigned us){if(us>=1000)IOSleep(us/1000);else IODelay(us);});
    IOLog("B5qWcn: radio=%u enable=%u verified=%u\n",radio,enabled!=0,ok);
    IOLockUnlock(lock);return ok?0:EIO;
}
