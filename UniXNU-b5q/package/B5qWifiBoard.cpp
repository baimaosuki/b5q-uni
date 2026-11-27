/* SPDX-License-Identifier: BSD-2-Clause-Patent */
// b5q resources around the shared Linux ath11k/mac80211/cfg80211 driver.
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceMemory.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <libkern/c++/OSData.h>
#include <kern/thread.h>
#include <kern/clock.h>
#include <pexpert/pexpert.h>
#include <sys/errno.h>
#ifndef KERN_CTL_REG_OPAQUE
#define KERN_CTL_REG_OPAQUE
#endif
#include <sys/kern_control.h>
#include <sys/kern_control_private.h>
#include <sys/kpi_mbuf.h>
#include <net/kpi_interface.h>
#include <stdarg.h>
extern "C" bool sm8550_gcc_trigger32(volatile uint32_t *,uint32_t,unsigned);
extern "C" ifnet_t sheng_ethernet_ifnet(void);
extern "C" bool sheng_ethernet_wifi_attached(void);
extern "C" void sheng_ethernet_wifi_detach(void);
extern "C" int b5q_wifi_publish_ready(void);
extern "C" bool sm8550_gcc_update32(volatile uint32_t *,uint32_t,uint32_t);
#include "B5qPcieCore.h"
#include "B5qWifiDma.h"
#include "B5qWifiArena.h"
#include "B5qWifiFirmwareName.h"
#include "B5qWcnPower.h"
#include "WifiFirmware.h"
#include "nw_abi.h"
#include "nw_control_endpoint.h"
extern "C" int armcpu_spi_attach(uint32_t,bool,void(*)(void *),void *,uint32_t *,uint64_t *);
extern "C" int armcpu_spi_mask(uint32_t,bool);
extern "C" void _disable_preemption(void),_enable_preemption(void),thread_yield_to_preemption(void);
extern "C" kern_return_t clear_wait(thread_t,wait_result_t);
extern "C" volatile int native_gpu_addon_stage;
extern "C" void sheng_wifi_net_start(const uint8_t[6]);
extern "C" {volatile uint32_t native_wifi_stats[29];}
extern "C" void native_wifi_logf(int level,const char *format,...) {
    char line[192];va_list ap;va_start(ap,format);vsnprintf(line,sizeof(line),format,ap);va_end(ap);
    IOLog("B5qWifi[%d]: %s\n",level,line);
}
namespace {
void barrier(){__asm__ volatile("dsb sy":::"memory");}
struct Window {
    IOMemoryMap *mapping=nullptr;volatile uint32_t *va=nullptr;
    Window()=default;
    Window(const Window&)=delete;
    Window &operator=(const Window&)=delete;
    ~Window(){OSSafeReleaseNULL(mapping);}
    bool open(uint64_t address,size_t bytes,IOOptionBits cache=kIOMapInhibitCache) {
        if(va)return true;
        auto *memory=IODeviceMemory::withRange(address,bytes);
        mapping=memory?memory->map(kIOMapAnywhere|cache):nullptr;OSSafeReleaseNULL(memory);
        va=mapping?reinterpret_cast<volatile uint32_t*>(mapping->getVirtualAddress()):nullptr;
        return va;
    }
};
Window gccWindow,tlmm,parf,dbi,phy,atu,config,bar,dma,gic;
B5qWifiDma::State dmaState{};
using DmaArena=B5qWifi::Arena<16384>;
DmaArena *arena;
IOLock *arenaLock;
uint32_t pcieCap,msiCap;
volatile uint32_t pending,wakeCount;
bool irqAttached,stackStarted;
uint64_t nowNs(){uint64_t ns;absolutetime_to_nanoseconds(mach_absolute_time(),&ns);return ns;}
uint64_t nowMs(){return nowNs()/1000000;}
bool wifiReadyAccepted(int result,uint64_t now,uint64_t &nextTry){
    if(!result||result==EEXIST)return true;
    nextTry=now+1000;return false;
}
uint64_t bootNs(){uint64_t ns;absolutetime_to_nanoseconds(mach_continuous_time(),&ns);return ns;}
void busyDelay(unsigned us){IODelay(us);}
void sleepMs(unsigned ms){IOSleep(ms);}
void wake(){__atomic_fetch_add(&wakeCount,1u,__ATOMIC_RELEASE);thread_wakeup(event_t(&wakeCount));}
void interrupt(void *){__atomic_fetch_or(&pending,1u,__ATOMIC_RELEASE);wake();}
bool readHandoff() {
    auto *chosen=IORegistryEntry::fromPath("/chosen",gIODTPlane);uint32_t flag=0;
    auto *ready=chosen?OSDynamicCast(OSData,chosen->getProperty("b5q-pcie-dma-ready")):nullptr;
    auto *state=chosen?OSDynamicCast(OSData,chosen->getProperty("b5q-pcie-dma-state")):nullptr;
    if(ready && ready->getLength()==4)memcpy(&flag,ready->getBytesNoCopy(),4);
    if(state && state->getLength()==sizeof(dmaState))memcpy(&dmaState,state->getBytesNoCopy(),sizeof(dmaState));
    OSSafeReleaseNULL(chosen);
    native_wifi_logf(6,"DMA v=%u ready=%u HAL=%llx/%x/%x/%x/%x prepare=%llx retain=%llx",
        dmaState.version,flag,dmaState.locate,dmaState.create,dmaState.configure,dmaState.attach,dmaState.map,dmaState.prepareStatus,dmaState.retentionStatus);
    if(!B5qWifiDma::ready(flag,dmaState))return false;
    // Only retained, firmware-owned low memory; never a second mapping of
    // XNU allocator memory. PCIe is dma-coherent in the original b5q DTS.
    if(!dma.open(dmaState.poolBase,dmaState.poolBytes,kIOMapCopybackCache))return false;
    arena=static_cast<DmaArena*>(IOMallocData(sizeof(DmaArena)));arenaLock=IOLockAlloc();
    if(!arena || !arenaLock)return false;
    memset(arena,0,sizeof(*arena));
    return arena->init(const_cast<uint32_t*>(dma.va),dmaState.iova,uint32_t(dmaState.poolBytes));
}
struct Hardware {
    uint64_t radioAt=0,resetAt=0;
    bool power(){return !b5q_wcn_power_get(B5Q_WCN_WLAN) && !b5q_wcn_pcie_vote();}
    bool radio(bool on){bool ok=!b5q_wcn_radio_enable(B5Q_WCN_WLAN,on);radioAt=mach_absolute_time();native_wifi_logf(ok?6:3,"stage=wlan-en on=%u verified=%u",on,ok);return ok;}
    void pin(unsigned n,uint32_t cfg,int level) {
        if(level>=0)tlmm.va[(n*0x1000+4)/4]=level?2:0;
        tlmm.va[n*0x1000/4]=cfg;barrier();
        if(n==94){uint64_t at=mach_absolute_time(),held=0,sinceRadio=0;
            if(!level)resetAt=at;
            if(resetAt)absolutetime_to_nanoseconds(at-resetAt,&held);
            if(radioAt)absolutetime_to_nanoseconds(at-radioAt,&sinceRadio);
            native_wifi_logf(6,"stage=perst level=%d read=%u held-us=%llu wlan-return-us=%llu",level,tlmm.va[(n*0x1000+4)/4]&1,held/1000,sinceRadio/1000);
        }
    }
    bool gcc(uint32_t reg,uint32_t clear,uint32_t set){bool ok=sm8550_gcc_update32(gccWindow.va+reg/4,clear,set);if(!ok)native_wifi_logf(3,"stage=gcc-rmw reg=%x value=%x clear=%x set=%x result=-12",reg,gccWindow.va[reg/4],clear,set);return ok;}
    bool rcg(uint32_t reg){bool ok=sm8550_gcc_trigger32(gccWindow.va+reg/4,1,10000);native_wifi_logf(ok?6:3,"stage=rcg-update reg=%x value=%x result=%d",reg,gccWindow.va[reg/4],ok?0:-12);return ok;}
    uint32_t readGcc(uint32_t reg){return gccWindow.va[reg/4];}
    bool clkref(){Window ref;if(!ref.open(0x1fd5000,0x1000))return false;ref.va[0x100/4]|=1;barrier();return (ref.va[0x100/4]&1)!=0;}
    void delay(unsigned us){if(us>=1000)IOSleep((us+999)/1000);else IODelay(us);}
    bool openController(){return ::parf.open(0x1c00000,0x3000)&&::dbi.open(0x60000000,0x1000);}
    bool openPhy(){return ::phy.open(0x1c06000,0x2000);}
    void parf(uint32_t reg,uint32_t clear,uint32_t set){::parf.va[reg/4]=(::parf.va[reg/4]&~clear)|set;barrier();}
    void dbi(uint32_t reg,uint32_t clear,uint32_t set){::dbi.va[reg/4]=(::dbi.va[reg/4]&~clear)|set;barrier();}
    void phy(uint32_t reg,uint32_t value){::phy.va[reg/4]=value;barrier();}
    uint32_t readPhy(uint32_t reg){return ::phy.va[reg/4];}
    uint32_t readDbi(uint32_t reg){return ::dbi.va[reg/4];}
};
bool mapOutbound(unsigned region,uint64_t cpu,uint64_t pci,uint32_t bytes,uint32_t type) {
    if(!atu.open(0x60001000,0x1000) || region>7 || !bytes || cpu>UINT64_MAX-bytes)return false;
    volatile uint32_t *r=atu.va+region*0x200/4;
    r[8/4]=uint32_t(cpu);r[12/4]=uint32_t(cpu>>32);r[16/4]=uint32_t(cpu+bytes-1);
    r[32/4]=uint32_t((cpu+bytes-1)>>32);r[20/4]=uint32_t(pci);r[24/4]=uint32_t(pci>>32);
    r[0]=type;r[1]=1u<<31;barrier();
    for(unsigned i=0;i<5;i++){if(r[1]&(1u<<31))return true;IODelay(10);}return false;
}
bool endpoint() {
    if(!mapOutbound(0,0x60100000,0x1000000,0x100000,4) || !config.open(0x60100000,0x1000))return false;
    uint32_t id=config.va[0];native_wifi_logf(6,"PCI endpoint=%08x expected=110317cb",id);
    if(id!=0x110317cb)return false;
    if(!mapOutbound(1,0x60300000,0x60300000,0x3d00000,0))return false;
    dbi.va[0x20/4]=0x63f06030;
    // Disable DMA until the original driver has installed real ring contexts.
    config.va[4/4]=(config.va[4/4]&0xffff)&~7u;
    uint32_t original=config.va[0x10/4];config.va[0x10/4]=~0u;barrier();
    uint32_t mask=config.va[0x10/4];config.va[0x10/4]=original;
    uint32_t bytes=~(mask&~15u)+1;
    if((mask&1) || !bytes || (bytes&(bytes-1)) || bytes<0x200000 || bytes>0x3d00000)return false;
    uint64_t address=(0x60300000ULL+bytes-1)&~uint64_t(bytes-1);
    if(address+bytes>0x64000000ULL)return false;
    config.va[0x10/4]=uint32_t(address)|(mask&15);if((mask&6)==4)config.va[0x14/4]=0;
    if(!bar.open(address,0x200000))return false;
    uint8_t cap=uint8_t(config.va[0x34/4]);uint64_t seen=0;
    for(unsigned guard=0;cap>=0x40 && guard<48;guard++) {
        if((cap&3) || (seen&(1ULL<<(cap/4))))return false;seen|=1ULL<<(cap/4);
        uint32_t value=config.va[cap/4];if(uint8_t(value)==0x10)pcieCap=cap;if(uint8_t(value)==5)msiCap=cap;
        cap=uint8_t(value>>8);
    }
    if(!pcieCap || !msiCap || cap)return false;
    config.va[4/4]=6;barrier();return true;
}
bool cfgOffset(int off,int size,uint32_t &reg) {
    reg=uint32_t(off);if(reg&0x80000000u)reg=pcieCap+(reg&0x7fffffffu);
    return (size==1||size==2||size==4) && !(reg&(size-1)) && reg<=4096-unsigned(size);
}
int cfgRead(int off,int size,uint32_t *out) {
    if(!config.va||!dbi.va||!(dbi.va[0x72c/4]&16))return -ENXIO;
    uint32_t reg;if(!out || !cfgOffset(off,size,reg))return -EINVAL;
    uint32_t value=config.va[(reg&~3u)/4];*out=size==4?value:(value>>((reg&3)*8))&((1u<<(size*8))-1);return 0;
}
int cfgWrite(int off,int size,uint32_t value) {
    if(!config.va||!dbi.va||!(dbi.va[0x72c/4]&16))return -ENXIO;
    uint32_t reg;if(!cfgOffset(off,size,reg))return -EINVAL;
    volatile uint8_t *base=reinterpret_cast<volatile uint8_t*>(config.va);
    if(size==1)base[reg]=uint8_t(value);
    else if(size==2)*reinterpret_cast<volatile uint16_t*>(base+reg)=uint16_t(value);
    else *reinterpret_cast<volatile uint32_t*>(base+reg)=value;
    barrier();return 0;
}
int msiTarget(uint32_t *lo,uint32_t *hi,uint32_t *data) {
    if(!irqAttached)return -ENXIO;
    *lo=0xaffff040;*hi=0;*data=800;return 0;
}
void *allocate(size_t n) {
    if(n>SIZE_MAX-16)return nullptr;auto *p=static_cast<uint8_t*>(IOMallocData(n+16));
    if(p){*reinterpret_cast<size_t*>(p)=n+16;return p+16;}return nullptr;
}
void release(void *p){if(p){auto *base=static_cast<uint8_t*>(p)-16;IOFreeData(base,*reinterpret_cast<size_t*>(base));}}
void *dmaAllocate(size_t n,uint64_t *bus){IOLockLock(arenaLock);void *p=arena->allocate(n,bus);IOLockUnlock(arenaLock);return p;}
void dmaRelease(size_t,void *p,uint64_t){IOLockLock(arenaLock);arena->release(p);IOLockUnlock(arenaLock);}
uint64_t dmaMap(void *p,size_t n,int){IOLockLock(arenaLock);uint64_t bus=arena->map(p,n);IOLockUnlock(arenaLock);return bus;}
void dmaSync(uint64_t bus,size_t n,int){if(bus>=dmaState.iova && n<=dmaState.poolBytes && bus-dmaState.iova<=dmaState.poolBytes-n)barrier();}
void logLine(int level,const char *text){native_wifi_logf(level,"%s",text);}
void halt(){native_wifi_logf(3,"driver fatal halt; thread isolated");thread_terminate(current_thread());}
void poll(){uint32_t bits=__atomic_exchange_n(&pending,0u,__ATOMIC_ACQ_REL);if(bits)nw_wifi_irq_pending(bits);nw_wifi_poll();}
struct Firmware {char name[64];uint8_t *data;size_t bytes;} firmware[16];
bool boardMac(uint8_t out[6]) {
    auto *chosen=IORegistryEntry::fromPath("/chosen",gIODTPlane);
    auto *id=chosen?OSDynamicCast(OSData,chosen->getProperty("unique-chip-id")):nullptr;uint64_t seed=0;
    if(id&&id->getLength()==8)memcpy(&seed,id->getBytesNoCopy(),8);OSSafeReleaseNULL(chosen);if(!seed)return false;
    uint64_t hash=0xcbf29ce484222325ULL;for(unsigned i=0;i<8;i++)hash=(hash^uint8_t(seed>>(i*8)))*0x100000001b3ULL;
    for(unsigned i=0;i<6;i++)out[i]=uint8_t(hash>>(i*8));out[0]=(out[0]&0xfe)|2;return true;
}
int fwGet(const char *path,const uint8_t **data,size_t *bytes) {
    if(!path || !data || !bytes)return -EINVAL;
    const char *name=path;for(const char *p=path;*p;p++)if(*p=='/')name=p+1;
    if(!strcmp(name,"wlan_mac.bin")) {
        static char text[40];uint8_t mac[6];if(!boardMac(mac))return -ENOENT;
        *bytes=snprintf(text,sizeof(text),"address=%02x%02x%02x%02x%02x%02x\n",mac[0],mac[1],mac[2],mac[3],mac[4],mac[5]);*data=reinterpret_cast<uint8_t*>(text);return 0;
    }
    if(!b5q_wifi_firmware_name(name))return -ENOENT;
    Firmware *slot=nullptr;
    for(auto &f:firmware){if(!strcmp(name,f.name)){*data=f.data;*bytes=f.bytes;return 0;}if(!*f.name&&!slot)slot=&f;}
    if(!slot)return -ENOMEM;
    int error=sheng_wifi_firmware_read(name,&slot->data,&slot->bytes);
    native_wifi_logf(error?3:6,"firmware=%s bytes=%zu result=%d",name,error?0:slot->bytes,error);
    if(error)return -error;strlcpy(slot->name,name,sizeof(slot->name));*data=slot->data;*bytes=slot->bytes;return 0;
}
// Native privileged control socket callbacks are copied verbatim from the
// pinned mainline WifiProbe; no private wireless station/auth stack is used.
struct ControlClient {uint64_t session; uint32_t unit;};
kern_ctl_ref gControlRef;
IOLock *gControlLock;
ControlClient *gControlClient;
errno_t controlError(int status) {
    switch (status) {
        case NW_CONTROL_OK: return 0;
        case NW_CONTROL_INVALID: return EINVAL;
        case NW_CONTROL_BUSY: return EWOULDBLOCK;
        case NW_CONTROL_NOT_READY: return ENXIO;
        case NW_CONTROL_AUTH_FAILED: return EACCES;
        case NW_CONTROL_TIMED_OUT: return ETIMEDOUT;
        case NW_CONTROL_UNSUPPORTED: return EOPNOTSUPP;
        case NW_CONTROL_NO_MEMORY: return ENOBUFS;
        case NW_CONTROL_NOT_FOUND: return ENOENT;
        case NW_CONTROL_STALE: return ESTALE;
        default: return EIO;
    }
}
errno_t controlConnect(kern_ctl_ref, sockaddr_ctl *address, void **information) {
    auto *owner = static_cast<ControlClient *>(IOMalloc(sizeof(ControlClient)));
    if (!owner) return ENOMEM;
    const int status = nw_wifi_control_attach(&owner->session);
    if (status) {IOFree(owner, sizeof(*owner)); return controlError(status);}
    owner->unit = address->sc_unit;
    IOLockLock(gControlLock); gControlClient = owner; IOLockUnlock(gControlLock);
    *information = owner; return 0;
}
errno_t controlDisconnect(kern_ctl_ref, uint32_t, void *information) {
    // XNU invokes disconnect after a failed connect, with no client context.
    if (!information) return 0;
    auto *owner = static_cast<ControlClient *>(information);
    nw_wifi_control_detach(owner->session);
    IOLockLock(gControlLock); if (gControlClient == owner) gControlClient = nullptr; IOLockUnlock(gControlLock);
    IOFree(owner, sizeof(*owner)); return 0;
}
int controlReadMbuf(void *source, void *destination, size_t length) {
    return mbuf_copydata(static_cast<mbuf_t>(source), 0, length, destination);
}
errno_t controlReceive(kern_ctl_ref, uint32_t, void *information, mbuf_t packet, int) {
    auto *owner = static_cast<ControlClient *>(information);
    const int status = nw_wifi_control_receive(owner->session, mbuf_pkthdr_len(packet), controlReadMbuf, packet);
    mbuf_freem(packet); return controlError(status);
}
void controlReceived(kern_ctl_ref, uint32_t, void *information, int) {
    nw_wifi_control_writable(static_cast<ControlClient *>(information)->session);
}
errno_t controlGetOption(kern_ctl_ref, uint32_t, void *information, int option, void *bytes, size_t *length) {
    if (option != NW_CONTROL_GET_SESSION) return ENOPROTOOPT;
    if (!length) return EINVAL;
    if (!bytes || *length < sizeof(uint64_t)) {*length = sizeof(uint64_t); return EMSGSIZE;}
    const uint64_t session = static_cast<ControlClient *>(information)->session;
    memcpy(bytes, &session, sizeof(session)); *length = sizeof(session); return 0;
}
int controlSend(void *, uint64_t session, const void *bytes, size_t length) {
    IOLockLock(gControlLock);
    const bool active = gControlClient && gControlClient->session == session;
    const uint32_t unit = active ? gControlClient->unit : 0;
    IOLockUnlock(gControlLock);
    if (!active) return NW_CONTROL_SEND_CLOSED;
    // No adapter lock is held while the socket layer takes its own locks.
    const errno_t result = ctl_enqueuedata(gControlRef, unit, const_cast<void *>(bytes), length, CTL_DATA_EOR);
    if (!result) return NW_CONTROL_SEND_OK;
    if (result == ENOBUFS || result == EWOULDBLOCK) return NW_CONTROL_SEND_AGAIN;
    return NW_CONTROL_SEND_CLOSED;
}
void controlWake(void *) {wake();}
int controlStart() {
    if (gControlRef) return 0;
    if (!gControlLock) gControlLock = IOLockAlloc();
    if (!gControlLock) return ENOMEM;
    kern_ctl_reg registration{};
    snprintf(registration.ctl_name, sizeof(registration.ctl_name), "%s", NW_CONTROL_NAME);
    registration.ctl_flags = CTL_FLAG_PRIVILEGED | CTL_FLAG_REG_EXTENDED;
    registration.ctl_sendsize = 256 * 1024; registration.ctl_recvsize = 512 * 1024;
    registration.ctl_connect = controlConnect; registration.ctl_disconnect = controlDisconnect;
    registration.ctl_send = controlReceive; registration.ctl_getopt = controlGetOption; registration.ctl_rcvd = controlReceived;
    const errno_t result = ctl_register(&registration, &gControlRef);
    if (result) return result;
    const nw_control_transport transport{nullptr, controlSend, controlWake};
    const int status = nw_wifi_control_transport_set(&transport);
    if (status) {ctl_deregister(gControlRef); gControlRef = nullptr; return controlError(status);}
    return 0;
}

void worker(void *,wait_result_t) {
    thread_set_thread_name(current_thread(),"B5qWifi");
    int error=0;
    for(unsigned i=0;i<600 && native_gpu_addon_stage<1;i++)IOSleep(100);
    if(native_gpu_addon_stage<1){error=-1;goto failed;}
    if(!readHandoff()){error=-2;goto failed;}
    if(!gccWindow.open(0x100000,0x80000) || !tlmm.open(0xf100000,0x100000)){error=-3;goto failed;}
    {
        uint32_t linkState[4]={};Hardware hardware;error=B5qPcie::train(hardware,linkState);
        native_wifi_stats[0]=error?uint32_t(error):16;
        native_wifi_logf(error?3:6,"PCIe train result=%d phy-entries=%zu",error,sizeof(B5qPcieInputs::phy)/sizeof(B5qPcieInputs::phy[0]));
        native_wifi_logf(error?3:6,"stage=link-state dbi728=%08x dbi72c=%08x ltssm=%u up=%u polls=%u phy214=%08x",linkState[0],linkState[1],linkState[0]&63,!!(linkState[1]&16),linkState[2],linkState[3]);
        if(parf.va&&phy.va)native_wifi_logf(error?3:6,"stage=link-clock parf1b0=%08x cfg=%x/%x pipe=%x gdsc=%x/%x",parf.va[0x1b0/4],gccWindow.va[0x6b078/4],gccWindow.va[0x6b05c/4],gccWindow.va[0x6b070/4],gccWindow.va[0x6b004/4],gccWindow.va[0x6c000/4]);
        if(error&&tlmm.va)native_wifi_logf(3,"stage=link-pins gpio80=%u gpio82=%u gpio94=%u gpio95=%u gpio96=%u gpio204=%u",tlmm.va[(80*0x1000+4)/4]&1u,tlmm.va[(82*0x1000+4)/4]&1u,tlmm.va[(94*0x1000+4)/4]&1u,tlmm.va[(95*0x1000+4)/4]&1u,tlmm.va[(96*0x1000+4)/4]&1u,tlmm.va[(204*0x1000+4)/4]&1u);
        if(error)goto failed;
    }
    if(!endpoint()){error=-17;goto failed;}
    {
        // Samsung's QGIC MSI alternative is described by the b5q DT's
        // pcie0_msi node. It uses GICD_SETSPI_NSR, hwirq as message data.
        // Keep the original ath11k single-vector fallback so the board uses
        // one native SPI slot, with original shared MHI/CE/DP dispatch.
        uint32_t readback=0;uint64_t router=0;
        if(!gic.open(0x17100000,0x10000)){error=-19;goto failed;}
        uint32_t typer=gic.va[4/4];
        native_wifi_logf(6,"QGIC MSI TYPER=%08x MBIS=%u SPIs=%u",typer,(typer>>16)&1,((typer&31)+1)*32);
        // GICD_SETSPI_NSR is optional. Use the DT alternative only when the
        // distributor advertises message-based SPIs and the named IRQ exists.
        if(!(typer&(1u<<16)) || ((typer&31)+1)*32<=800){error=-19;goto failed;}
        error=armcpu_spi_attach(800,true,interrupt,nullptr,&readback,&router);
        native_wifi_logf(error?3:6,"QGIC MSI INTID800 attach=%d readback=%x route=%llx",error,readback,router);
        if(error)goto failed;irqAttached=true;
        static const lx_platform platform={nowMs,sleepMs,poll,logLine,halt,allocate,release,
            dmaAllocate,dmaRelease,dmaMap,dmaSync,fwGet,nowNs,bootNs,busyDelay,_disable_preemption,_enable_preemption};
        nw_wifi_set_platform(&platform);
        error=controlStart();if(error){if(error>0)error=-error;goto failed;}
        static nw_board board;
        board.bar=const_cast<uint32_t*>(bar.va);board.bar_len=0x200000;
        board.device_id=0x1103;board.msi_cap=uint16_t(msiCap);board.irq_base=1000;
        board.cfg_read=cfgRead;board.cfg_write=cfgWrite;board.msi_target=msiTarget;
        error=nw_wifi_start(&platform,&board);if(error)goto failed;stackStarted=true;b5q_wcn_wifi_probe_done();
        nw_wifi_irq_mode(1);native_wifi_stats[0]=21;
    }
    {
        bool netStarted=false,readyPublished=false;unsigned readyFailures=0;
        uint64_t nextReadyTry=0,nextReport=0,slice=nowNs();
        for(;;) {
            error=nw_wifi_step();if(error<0)goto failed;
            if(!netStarted && nw_wifi_stats.stage>=4) {
                uint8_t mac[6];if(!boardMac(mac)){error=-18;goto failed;}
                sheng_wifi_net_start(mac);
                if(!sheng_ethernet_wifi_attached()){error=-ENXIO;native_wifi_logf(3,"stage=network-interface result=%d callbacks=0",error);goto failed;}
                netStarted=true;
                native_wifi_logf(6,"stage=network-interface result=0 callbacks=1 state=%s",sheng_ethernet_ifnet()?"attached":"waiting-for-ifnet");
            }
            const uint64_t readyNow=nowMs();
            if(netStarted && !readyPublished && readyNow>=nextReadyTry && sheng_ethernet_ifnet()) {
                const int ready=b5q_wifi_publish_ready();
                readyPublished=wifiReadyAccepted(ready,readyNow,nextReadyTry);
                if(readyPublished||++readyFailures<=4||!(readyFailures%30))
                    native_wifi_logf(readyPublished?6:3,"stage=supplicant-ready result=%d firmware=%u interface=1 retry-ms=%llu",
                        ready,nw_wifi_stats.stage,(unsigned long long)(readyPublished?0:nextReadyTry-readyNow));
            }
            if(nowMs()>=nextReport) {
                nextReport=nowMs()+30000;native_wifi_stats[1]=nw_wifi_stats.stage;
                native_wifi_logf(6,"stage=%u scans=%u frames=%u err=%d DMA=%u/%u peak=%u failures=%u",
                    nw_wifi_stats.stage,nw_wifi_stats.scans,nw_wifi_stats.frames,nw_wifi_stats.last_err,
                    arena->used,arena->bytes,arena->peak,arena->failures);
            }
            if(!error) {
                uint32_t observed=__atomic_load_n(&wakeCount,__ATOMIC_ACQUIRE);
                unsigned ms=nw_wifi_wait_ms(1000);
                if(ms) {
                    uint64_t deadline;clock_interval_to_deadline(ms,NSEC_PER_MSEC,&deadline);
                    assert_wait_deadline(event_t(&wakeCount),THREAD_UNINT,deadline);
                    if(observed!=__atomic_load_n(&wakeCount,__ATOMIC_ACQUIRE))clear_wait(current_thread(),THREAD_AWAKENED);
                    else thread_block(THREAD_CONTINUE_NULL);
                }
                slice=nowNs();
            }else if(nowNs()-slice>=2000000){thread_yield_to_preemption();slice=nowNs();}
        }
    }
failed:
    if(error>0)error=-error;
    native_wifi_stats[0]=uint32_t(error?error:-1);
    // Stop users of Linux queues while PCIe/MHI and their interrupt are still
    // live. Only then quiesce endpoint DMA and remove power.
    sheng_ethernet_wifi_detach();
    if(stackStarted)nw_wifi_stop();
    if(irqAttached)armcpu_spi_mask(800,true);
    if(config.va&&dbi.va&&(dbi.va[0x72c/4]&16)){
        auto *command=reinterpret_cast<volatile uint16_t*>(reinterpret_cast<volatile uint8_t*>(config.va)+4);
        *command=uint16_t(*command&~4u);barrier();
    }
    if(tlmm.va){Hardware h;h.pin(94,0x201,0);IODelay(1000);}
    b5q_wcn_radio_enable(B5Q_WCN_WLAN,0);b5q_wcn_power_put(B5Q_WCN_WLAN);
    b5q_wcn_wifi_probe_done();
    native_wifi_logf(3,"stopped result=%d; boot continues; DMA pool retained",error);
    thread_terminate(current_thread());
}
}
extern "C" void sheng_wifi_wake(){wake();}
extern "C" int sheng_wifi_file(const char *name,const uint8_t **data,size_t *size){return fwGet(name,data,size);}
extern "C" void b5q_wifi_probe() {
    unsigned enabled=0;if(!PE_parse_boot_argn("wifi",&enabled,sizeof(enabled)) || !enabled)return;
    static uint32_t once=0;if(__atomic_exchange_n(&once,1u,__ATOMIC_ACQ_REL))return;
    b5q_wcn_wifi_probe_begin();
    thread_t thread=nullptr;
    if(kernel_thread_start(worker,nullptr,&thread)==KERN_SUCCESS)thread_deallocate(thread);
    else {b5q_wcn_wifi_probe_done();native_wifi_stats[0]=uint32_t(-7);native_wifi_logf(3,"worker allocation failed");}
}


extern "C" void b5q_wifi_mac_context(const uint8_t *vdev){
 uint8_t board[6]{},ifaddr[6]{};boardMac(board);ifnet_t ifp=sheng_ethernet_ifnet();
 const bool named=ifp&&ifnet_lladdr_copy_bytes(ifp,ifaddr,sizeof ifaddr)==0;
 static uint32_t logs=0;if(__atomic_fetch_add(&logs,1u,__ATOMIC_RELAXED)>=32u)return;
 native_wifi_logf(6,"vdev-mac ifnet=%u lladdr=%02x:%02x:%02x:%02x:%02x:%02x vdev=%02x:%02x:%02x:%02x:%02x:%02x board-match=%u",named,
   ifaddr[0],ifaddr[1],ifaddr[2],ifaddr[3],ifaddr[4],ifaddr[5],vdev[0],vdev[1],vdev[2],vdev[3],vdev[4],vdev[5],!memcmp(board,vdev,6));
}
