/* SPDX-License-Identifier: BSD-2-Clause-Patent */
/* Board-only b5q.dts WCN supplies; transport/core remain shared components. */
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceMemory.h>
#include <sys/errno.h>
#include "B5qWcnPower.h"
#include "B5qWcnPowerCore.h"
#include "QcomRpmh.h"
#include "AppsSmmuLock.h"
#include "BootResetCore.h"
#include "QcomQmp.h"
#include "QcomScm.h"
#include "B5qAossQmpLock.h"
namespace { IOLock *aossQmpLock; }
extern "C" bool b5q_aoss_qmp_lock(void){
    auto *held=__atomic_load_n(&aossQmpLock,__ATOMIC_ACQUIRE);
    if(!held){auto *made=IOLockAlloc();if(!made)return false;IOLock *expected=nullptr;
        if(__atomic_compare_exchange_n(&aossQmpLock,&expected,made,false,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))held=made;
        else{IOLockFree(made);held=expected;}}
    IOLockLock(held);return true;
}
extern "C" void b5q_aoss_qmp_unlock(void){IOLockUnlock(aossQmpLock);}
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
Window rsc,tlmm,aoss,ipcc;
QcomQmp pdcQmp;bool pdcReady,sleepReady;
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
bool sleepClock(){
    if(sleepReady)return true;
    Window core,config,observer,channel;
    if(!core.open(0xc400000,0x3000)||!config.open(0xc42d000,0x4000))return false;
    const unsigned version=core.va[0],count=core.va[BR_FEATURES/4]&BR_FEATURES_APIDS_MASK;
    if(version<BR_VERSION_V7_MIN||version>=BR_VERSION_V8_MIN||!count||count>1024)return false;
    int apid=-1;
    for(unsigned i=0;i<count;i++)if(((core.va[(BR_APID_MAP+4*i)/4]>>8)&0xfff)==0x0ba){if(apid>=0)return false;apid=int(i);}
    if(apid<0||!observer.open(0xc440000+uint64_t(apid)*0x20,0x20)){
        IOLog("B5qWcn: stage=sleep-clock ppid=0ba apid=%d result=no-observer\n",apid);return false;
    }
    const unsigned owner=config.va[apid]&7;
    auto read=[&](uint8_t reg,uint8_t &v){observer.va[BR_CMD/4]=br_cmd(BR_OP_EXT_READL,reg,0);barrier();if(br_wait(observer.va))return false;v=uint8_t(observer.va[BR_RDATA0/4]);return true;};
    auto write=[&](uint8_t reg,uint8_t v){channel.va[BR_WDATA0/4]=v;barrier();channel.va[BR_CMD/4]=br_cmd(BR_OP_EXT_WRITEL,reg,0);barrier();return !br_wait(channel.va);};
    uint8_t type=0,subtype=0;
    const uint8_t regs[]={0x42,0x41,0x44,0x40,0x46},values[]={5,0,2,1,0x80};
    bool ok=read(4,type)&&read(5,subtype);uint8_t actual[5]={};
    for(unsigned i=0;i<5;i++)if(!read(regs[i],actual[i]))ok=false;
    auto enabled=[&](){return (actual[4]&0x80)&&(actual[3]&3)==1&&(actual[2]&0xf)==2;};
    if(ok&&enabled()){
        IOLog("B5qWcn: stage=sleep-clock apid=%d owner=%u type=%02x subtype=%02x mode=%02x src=%02x en=%02x ready=1 retained=1\n",apid,owner,type,subtype,actual[3],actual[2],actual[4]);
        sleepReady=true;return true;
    }
    if(!ok||owner!=0||type!=0x10||subtype<0x10||subtype>0x13||!channel.open(0xc500000+uint64_t(apid)*0x1000,0x1000)){
        IOLog("B5qWcn: stage=sleep-clock apid=%d owner=%u type=%02x subtype=%02x read=%u result=not-writable\n",apid,owner,type,subtype,ok);return false;
    }
    for(unsigned i=0;i<5&&ok;i++)ok=write(regs[i],values[i]);
    for(unsigned i=0;i<5&&ok;i++)ok=read(regs[i],actual[i]);
    ok=ok&&enabled();
    IOLog("B5qWcn: stage=sleep-clock ppid=0ba apid=%d owner=%u subtype=%02x regs42/41/44/40/46=%02x/%02x/%02x/%02x/%02x ready=%u\n",apid,owner,subtype,actual[0],actual[1],actual[2],actual[3],actual[4],ok);
    sleepReady=ok;return ok;
}
void kickPdc(void *){ipcc.va[QCOM_IPCC_SEND/4]=qcom_ipcc_id(QCOM_IPCC_CLIENT_AOP,QCOM_IPCC_SIGNAL_GLINK_QMP);barrier();}
bool waitPdc(){
    for(unsigned ms=0;ms<1000;ms++){
        const int state=qcom_qmp_step(&pdcQmp);if(state==QcomQmpOpen)return true;if(state<0)return false;IOSleep(1);
    }return false;
}
bool pdcInit(){
    B5qAossQmpLock guard;
    if(!guard.ready()){IOLog("B5qWcn: stage=pdc-lock result=no-memory\n");return false;}
    if(pdcReady)return true;
    if(!aoss.open(0xc300000,0x1000)||!ipcc.open(0x408000,0x1000))return false;
    qcom_qmp_init(&pdcQmp,aoss.va,0x400,kickPdc,nullptr);
    if(!waitPdc()){IOLog("B5qWcn: stage=pdc-link result=%d\n",pdcQmp.state);return false;}
    static const char *messages[]={
        "{class: wlan_pdc, ss: rf, res: s4e.v, upval: 966}",
        "{class: wlan_pdc, ss: rf, res: s4e.v, dwnval: 615}",
        "{class: wlan_pdc, ss: rf, res: s4g.v, upval: 1350}",
        "{class: wlan_pdc, ss: rf, res: s4g.v, dwnval: 945}",
        "{class: wlan_pdc, ss: rf, res: s6g.v, upval: 1900}",
        "{class: wlan_pdc, ss: rf, res: s6g.v, dwnval: 1825}",
        "{class: wlan_pdc, ss: rf, res: s2g.m, enable: 1}",
        "{class: wlan_pdc, ss: rf, res: s2g.v, enable: 1}",
        "{class: wlan_pdc, ss: rf, res: s2g.v, upval: 1012}",
        "{class: wlan_pdc, ss: rf, res: s2g.v, dwnval: 800}",
        "{class: wlan_pdc, ss: bb, res: pdc, enable: 0}"};
    for(unsigned i=0;i<sizeof(messages)/sizeof(messages[0]);i++){
        // An earlier firmware/ADSP message must be acknowledged before use.
        unsigned ms=0;while(aoss.va[pdcQmp.box/4]&&ms++<1000)IOSleep(1);
        const int state=ms>=1000?QcomQmpBusy:qcom_qmp_send(&pdcQmp,messages[i]);
        const bool ok=state==QcomQmpSending&&waitPdc();
        IOLog("B5qWcn: stage=pdc-init index=%u state=%d ack=%u\n",i,pdcQmp.state,ok);
        if(!ok)return false; // Never clear an unacknowledged remote mailbox.
    }pdcReady=true;return true;
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
    IOFreeData(copy,0x20000);if(ok)ok=sleepClock()&&pdcInit();prepared=ok;return ok;
}
bool send(const QcomRscLayout &layout,uint32_t address,uint32_t value) {
    constexpr unsigned tcs=0,base=0xd00;
    QcomRpmhWrite writes[16];
    // Serialize this active TCS with the existing USB RPMh owner. The mutex
    // name is historical: AppsSmmuLock performs no SMMU register access.
    const unsigned n=qcom_rpmh_active_request(&layout,tcs,&address,&value,1,writes,16);
    if(!n)return false;
    if(!rsc.va[(base+layout.tcs_stride*tcs+layout.status)/4]){IOLog("B5qWcn: RPMh TCS0 busy addr=%08x\n",address);return false;}
    const uint32_t stale=rsc.va[(base+layout.irq_status)/4]&(1u<<tcs);
    if(stale){rsc.va[(base+layout.irq_clear)/4]=stale;barrier();}
    rsc.va[base/4]|=1u<<tcs;barrier();
    for(unsigned i=0;i<n;i++){rsc.va[(base+writes[i].offset)/4]=writes[i].value;barrier();}
    unsigned us=0;uint32_t status=0;
    for(;us<20000;us+=10){status=rsc.va[(base+layout.irq_status)/4];if(status&(1u<<tcs))break;IODelay(10);}
    if(us==20000){IOLog("B5qWcn: RPMh completion timeout addr=%08x data=%u irq=%08x\n",address,value,status);return false;}
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
            uint32_t cfg=p==80?(on?0x3c3u:0x201u):p==81?0x201u:0x200u;
            tlmm.va[p*0x1000/4]=cfg;barrier();
            tlmm.va[(p*0x1000+4)/4]=on?2:0;barrier();
        },[](unsigned us){if(us>=1000)IOSleep(us/1000);else IODelay(us);});
    IOLog("B5qWcn: radio=%u enable=%u verified=%u\n",radio,enabled!=0,ok);
    IOLockUnlock(lock);return ok?0:EIO;
}
