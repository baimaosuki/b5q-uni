// SPDX-License-Identifier: BSD-2-Clause-Patent
// SM8550 USB device controller behind Apple's own stack. The DWC3 programming model, endpoints, control transfers and everything
// above them (IOUSBDeviceFamily, AppleUSBDeviceMux, configd's USBDeviceConfiguration, lockdownd) stay the unchanged system parts:
// this class only supplies what an Apple SoC subclass of AppleUSBXDCI supplies, namely the register window, the interrupt, power
// and the PHY. Hardware facts come from mainline Linux: sm8550.dtsi, gcc-sm8550.c, dwc3-qcom.c, phy-snps-eusb2.c.
#include "OriginalUsbXdciABI.h"
#include "OriginalUsbXhciABI.h"
#include "QcomEusb2Phy.h"
#include "QcomQmpUsb3.h"
#include "GeniI2c.h"
#include "B5qUsbInputs.h"
#include "B5qUsbIrq.h"
#include "B5qUsbDmaHandoff.h"
#include "B5qUsbHostEvent.h"
#include "B5qMax77705.h"
#include "B5qDpPort.h"
#include <mach/mach_time.h>
extern "C" unsigned long long ml_phys_read_double_64(uint64_t);
extern "C" bool b5q_usb_repeater(bool,bool);
extern "C" bool b5q_usb_typec_init(void);
extern "C" int b5q_usb_cable_role(void);
extern "C" bool b5q_usb_cable_state(B5qMax77705::Cable *);
extern "C" bool b5q_usb_otg(bool);
#include "QcomRpmh.h"
#include "AppsSmmuLock.h"
#include <IOKit/IOLib.h>
#include <kern/thread.h>
#include <kern/clock.h>
#include <pexpert/pexpert.h>
#include <IOKit/IODeviceMemory.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IOPlatformExpert.h>
#include <libkern/c++/OSData.h>
#include <libkern/c++/OSDictionary.h>
#include <libkern/c++/OSNumber.h>
#include "B5qFeatures.h"
extern "C" bool b5q_dp_link_stop(void);
extern "C" void b5q_dp_link_update(const B5qDpPortState *);
extern "C" {
int armcpu_spi_attach(uint32_t, bool, void (*)(void *), void *, uint32_t *, uint64_t *);
int armcpu_spi_mask(uint32_t, bool);
bool sm8550_gcc_update32(volatile uint32_t *, uint32_t, uint32_t);
// [0] stage (negative: the step that failed), [1] GSNPSID, [2] GUID-free hardware parameter 0, [3] parameter 3, [4] parameter 7,
// [5] GDSC USB30, [6] GDSC PHY, [7] firmware DMA stream ID or ~0u, [8] repeater status, [9] RPMh rails found, [10] VBUS override state,
// [11] interrupts, [12] powerOn calls, [13] powerOff calls, [14] controllerReset result, [15] DSTS at power on, [16] DCFG after
// reset, [17] GCTL after reset, [18] GUSB2PHYCFG after reset, [19] start result, [20] power state request result, [21] kext load result,
// with usb=2, every 2 s: [22] GSBUSCFG0, [23] GSBUSCFG1, [24] GUCTL1, [25] SMMU global fault, [26] DSTS, [27] DALEPENA,
// [28] GEVNTCOUNT, [29] DEPCMD of EP0 OUT, [30] bypass bank fault status, [31] GEVNTSIZ.
// [32] retimer: chip id | stage << 16, [33] QMP PCS status, [34] orientation GPIO, [35] VBUS changes | last value << 16,
// [44] role applied | wanted << 8 | core << 16, [45] role changes, [46] xHCI load << 16 | start, [47] USBCMD, [48] USBSTS, [49] [50] PORTSC 1 and 2,
// [51] HCSPARAMS1,
// [40] UCSI state | version << 16, [41] UCSI connector status, [42] CCI, [43] changes | errors << 16,
// [36] bit mask of the SuperSpeed link states seen (GDBGLTSSM bits 25:22), [37] GDBGLTSSM, [38] GUSB3PIPECTL, [39] cable test steps.
volatile uint32_t native_usb_stats[54];
}
void dmaDiagnostics(const char *reason);
void hostCheckpoint(const char *reason,bool force=false,bool allowU3=false);
void restoreHostGlobals(void);
void configureHostPorts(IOService *host);
extern "C" unsigned b5q_log_sync(unsigned);
namespace {
// The DWC3 global, device and OTG registers in the window Apple's class addresses: base + 0xc000.
constexpr uint64_t kCore = 0x0a600000, kAppleWindow = kCore + 0xc000, kQscratch = kCore + 0xf8800, kGcc = 0x100000, kTcsr = 0x1fd5000,
    kPhy = 0x088e3000, kRsc = 0x17a20000, kCmdDb = 0x81c60000;
constexpr uint32_t kCmdDbSize = 0x20000, kIrq = 133 + 32;
constexpr unsigned kOwnedTcs = 2;   // shared with the microphone rail under the same lock
struct Region {IOMemoryMap *map; volatile uint32_t *va;};
Region gGcc, gScratch, gPhy, gTcsrMap;
bool gSuperSpeed;
unsigned gDpLanes;
bool gPhyResetPending;
void stage(int value) {native_usb_stats[0] = (uint32_t)value;IOLog("qcom-dwc3: stage=%d\n",value);}
bool mapRegion(Region &r, uint64_t pa, uint64_t bytes) {
    IODeviceMemory *d = IODeviceMemory::withRange(pa, bytes);
    r.map = d ? d->map(kIOMapAnywhere | kIOMapInhibitCache) : nullptr;
    OSSafeReleaseNULL(d);
    r.va = r.map ? reinterpret_cast<volatile uint32_t *>(r.map->getVirtualAddress()) : nullptr;
    return r.va != nullptr;
}
void barrier() {__asm__ volatile("dsb sy" ::: "memory");}
bool waitBits(volatile uint32_t *reg, uint32_t mask, uint32_t value, unsigned ms) {
    for (unsigned i = 0; i < ms * 10; ++i) {
        if ((*reg & mask) == value) return true;
        IODelay(100);
    }
    return (*reg & mask) == value;
}
// Rails of the eUSB2 PHY, its repeater and the QMP PHY, the reference clock and the path to memory (dwc3-qcom usb-ddr).
bool powerRails() {
    uint8_t *db = static_cast<uint8_t *>(IOMallocData(kCmdDbSize));
    if (!db) return false;
    Region dbw = {}, rsc = {};
    bool ok = mapRegion(dbw, kCmdDb, kCmdDbSize) && mapRegion(rsc, kRsc, 0x10000);
    if (ok) {
        for (uint32_t i = 0; i < kCmdDbSize; i += 4) {const uint32_t w = dbw.va[i / 4]; memcpy(db + i, &w, 4);}
        const QcomRscLayout layout = qcom_rsc_layout(rsc.va[0]);
        AppsSmmuLock guard;
        auto send = [&](uint32_t address, uint32_t value) {
            QcomRpmhWrite writes[16];
            const unsigned n = qcom_rpmh_active_request(&layout, kOwnedTcs, &address, &value, 1, writes, 16);
            for (unsigned i = 0; i < n; ++i) rsc.va[(0xd00 + writes[i].offset) / 4] = writes[i].value;
            IOSleep(2);
            const unsigned m = qcom_rpmh_finish(&layout, kOwnedTcs, writes, 16);
            for (unsigned i = 0; i < m; ++i) rsc.va[(0xd00 + writes[i].offset) / 4] = writes[i].value;
        };
        static const struct {const char *name; uint32_t mv;} rails[] = {
            {"ldoe1", 880}, {"ldoe3", 1200}, {"ldob15", 1800}, {"ldob5", 3104}, {"ldof3", 912}};
        for (unsigned i = 0; i < sizeof rails / sizeof rails[0] && ok; ++i) {
            QcomRpmhResource res;
            if (qcom_cmd_db_find(db, kCmdDbSize, rails[i].name, &res)) {ok = false; break;}
            send(res.address + 8, 7);
            send(res.address, rails[i].mv);
            send(res.address + 4, 1);
            native_usb_stats[9] = native_usb_stats[9] | (1u << i);
        }
        QcomRpmhResource res;
        if (ok && !qcom_cmd_db_find(db, kCmdDbSize, "xo.lvl", &res)) send(res.address, 3); else ok = false;
        // SN2 carries qnm_aggre1_noc: vote = ceil(ceil(kBps * width / buswidth) * 1000 / unit), buswidth 16, 2500 MB/s peak.
        if (ok && !qcom_cmd_db_find(db, kCmdDbSize, "SN2", &res)) {
            uint32_t vote = 0x400;
            if (res.level_count >= 3 && (res.levels[0] | (uint32_t)res.levels[1] << 16) && res.levels[2]) {
                const uint64_t unit = res.levels[0] | (uint32_t)res.levels[1] << 16;
                const uint64_t x = (((2500000ull * res.levels[2] + 15) / 16) * 1000 + unit - 1) / unit;
                vote = x < 1 ? 1 : x > 0x3fff ? 0x3fff : (uint32_t)x;
            }
            send(res.address, 1u << 30 | 1u << 29 | vote << 14 | vote);
            native_usb_stats[9] = native_usb_stats[9] | 0x80000000u;
        } else ok = false;
    }
    if (dbw.map) dbw.map->release();
    if (rsc.map) rsc.map->release();
    IOFreeData(db, kCmdDbSize);
    return ok;
}
bool gdsc(uint32_t offset, unsigned statIndex) {
    volatile uint32_t *reg = gGcc.va + offset / 4;
    if (!sm8550_gcc_update32(reg, 1u, 1u << 11)) return false;   // SW_COLLAPSE off, RETAIN_FF_ENABLE on
    const bool ok = waitBits(reg, 0x80000000u, 0x80000000u, 100);
    native_usb_stats[statIndex] = *reg;
    return ok;
}
bool branch(uint32_t offset) {
    volatile uint32_t *reg = gGcc.va + offset / 4;
    if (!sm8550_gcc_update32(reg, 0, 1u)) return false;
    return waitBits(reg, 0x80000000u, 0, 100);
}
bool rcg(uint32_t cmd, uint32_t cfg) {
    volatile uint32_t *c = gGcc.va + cmd / 4;
    if ((c[1] & 0x71fu) == cfg) return true;
    c[1] = (c[1] & ~0x71fu) | cfg;
    barrier();
    c[0] = c[0] | 1u;
    barrier();
    return waitBits(c, 1u, 0, 10);
}
bool clocksAndResets() {
    // gcc-sm8550.c: USB30_PRIM_BCR 0x39000, QUSB2PHY_PRIM_BCR 0x12000; the core reset of dwc3_qcom_probe, the PHY reset of its init.
    volatile uint32_t *core = gGcc.va + 0x39000 / 4, *phy = gGcc.va + 0x12000 / 4;
    *core = *core | 1u; barrier(); IODelay(20);
    *core = *core & ~1u; barrier();
    // Master 200 MHz from GPLL0 (source 1, half divider 5), mock UTMI 19.2 MHz from XO, as the dtsi assigns them.
    if (!rcg(0x3902c, 1u << 8 | 5u) || !rcg(0x39044, 0)) return false;
    if (!branch(0x39088) || !branch(0x39018) || !branch(0x3908c) || !branch(0x39024) || !branch(0x39028)) return false;
    gTcsrMap.va[0x118 / 4] = gTcsrMap.va[0x118 / 4] | 1u;
    gTcsrMap.va[0x108 / 4] = gTcsrMap.va[0x108 / 4] | 1u;
    barrier();
    *phy = *phy | 1u; barrier(); IODelay(150);
    *phy = *phy & ~1u; barrier();
    return true;
}
bool repeater(bool init,bool host){return b5q_usb_repeater(init,host);}
void phyInit() {
    for (const auto &w : kQcomEusb2Init) {
        volatile uint32_t *reg = gPhy.va + w.offset / 4;
        *reg = (*reg & ~(uint32_t)w.mask) | w.value;
        barrier();
    }
}
// dwc3_qcom_select_utmi_clk: no PIPE clock until the QMP PHY runs.
void selectUtmiClock() {
    volatile uint32_t *cfg = gScratch.va + 0x8 / 4;
    *cfg = *cfg | 1u << 8; barrier(); IOSleep(1);
    *cfg = *cfg | 1u | 1u << 3; barrier(); IOSleep(1);
    *cfg = *cfg & ~(1u << 8); barrier();
    IOLog("qcom-dwc3: clock-mux QSCRATCH=%x\n",*cfg);
}
// Reverse the QSCRATCH UTMI-only mux after a successful hot-plug QMP start.
// PIPE_UTMI_CLK_DIS gates the mux while PIPE_UTMI_CLK_SEL/PIPE3_PHYSTATUS_SW
// change. Preserve every unrelated GENERAL_CFG bit.
void selectPipeClock() {
    volatile uint32_t *cfg = gScratch.va + 0x8 / 4;
    *cfg = *cfg | 1u << 8; barrier(); IOSleep(1);
    *cfg = *cfg & ~(1u | 1u << 3); barrier(); IOSleep(1);
    *cfg = *cfg & ~(1u << 8); barrier();
    IOLog("qcom-dwc3: clock-mux QSCRATCH=%x\n",*cfg);
}
void vbusOverride(bool on) {
    volatile uint32_t *ss = gScratch.va + 0x30 / 4, *hs = gScratch.va + 0x10 / 4;
    const uint32_t ssBits = 1u << 24, hsBits = 1u << 20 | 1u << 28;
    if (on) {*ss = *ss | ssBits; *hs = *hs | hsBits;} else {*ss = *ss & ~ssBits; *hs = *hs & ~hsBits;}
    barrier();
    native_usb_stats[10] = *hs;
}
// QMP USB3/DP combo PHY at 0x88e8000 in USB 3 only mode: qmp_combo_com_init and qmp_combo_usb_power_on.
bool qmpInit(bool reverse) {
    unsigned forceUtmi=0;
    if(PE_parse_boot_argn("usb-utmi",&forceUtmi,sizeof(forceUtmi))&&forceUtmi==1){
        selectUtmiClock();IOLog("qcom-dwc3: QMP forced-UTMI reverse=%u QSCRATCH=%x\n",reverse,gScratch.va[8/4]);return false;
    }
    Region phy = {};
    if (!mapRegion(phy, 0x088e8000, 0x3000)) return false;
    volatile uint8_t *base = reinterpret_cast<volatile uint8_t *>(phy.va);
    auto rd = [&](uint32_t o) {return *reinterpret_cast<volatile uint32_t *>(base + o);};
    auto wr = [&](uint32_t o, uint32_t v) {*reinterpret_cast<volatile uint32_t *>(base + o) = v; barrier();};
    if(gDpLanes==4){
        // Samsung dp_catalog_ctrl_usb_reset: USB is already stopped by
        // roleThread. Four DP lanes retain USB2 through the UTMI mux.
        wr(kQmpComResetOvrd,0x0a);wr(kQmpComMode,2);wr(kQmpComReset,1);
        wr(kQmpComTypec,reverse?3:2);wr(kQmpComSwi,0);wr(kQmpComReset,0);
        wr(kQmpComPower,1);wr(kQmpComResetOvrd,0);
        phy.map->release();return false;
    }
    selectUtmiClock(); // The core must not consume PIPE while QMP is reset.
    volatile uint32_t *reset = gGcc.va + 0x50000 / 4, *common = gGcc.va + 0x50008 / 4;
    *reset = *reset | 1u; *common = *common | 1u; barrier(); IODelay(20);
    *reset = *reset & ~1u; *common = *common & ~1u; barrier();
    if (!rcg(0x39070, 0) || !branch(0x39060) || !branch(0x39064) ||
        !sm8550_gcc_update32(gGcc.va + 0x3906c / 4, 3u, 0) ||
        !sm8550_gcc_update32(gGcc.va + 0x39068 / 4, 0, 1u)) {
        phy.map->release();return false;
    }
    wr(kQmpComPower, rd(kQmpComPower) | 1u);
    wr(kQmpComResetOvrd, rd(kQmpComResetOvrd) | 0xfu);
    wr(kQmpComTypec, 1u << 1 | (reverse ? 1u : 0));                             // software port select
    wr(kQmpComMode, gDpLanes==2?3u:1u);                                        // Samsung USB3+DP / USB3 only
    wr(kQmpComResetOvrd, rd(kQmpComResetOvrd) & ~0xcu);
    wr(kQmpComSwi, rd(kQmpComSwi) & ~3u);
    wr(kQmpComReset, rd(kQmpComReset) & ~1u);
    wr(kQmpPowerDown, rd(kQmpPowerDown) | 1u);
    for (const auto &w : B5qUsbInputs::qmp) wr(w.offset, w.value);
    wr(kQmpReset, rd(kQmpReset) & ~1u);
    wr(kQmpStart, rd(kQmpStart) | 3u);
    if(gDpLanes==2)wr(kQmpComResetOvrd,rd(kQmpComResetOvrd)&~0xfu);
    bool ok = false;
    for (unsigned i = 0; i < 1000 && !ok; ++i) {ok = !(rd(kQmpStatus) & 1u << 6); if (!ok) IODelay(200);}
    native_usb_stats[33] = rd(kQmpStatus);
    if(ok)selectPipeClock();
    IOLog("qcom-dwc3: QMP result=%u reverse=%u status=%x QSCRATCH=%x\n",ok,reverse,native_usb_stats[33],gScratch.va[8/4]);
    phy.map->release();
    return ok;
}
// The USB 3 path, or false for USB 2 only with the UTMI clock in place of the PIPE clock (a USB 2 cable still works on the former).
bool superSpeedInit() {
    B5qMax77705::Cable cable;b5q_usb_cable_state(&cable);
    const int reverse=cable.orientation();
    native_usb_stats[34]=uint32_t(reverse);
    if(reverse<0){IOLog("qcom-dwc3: QMP orientation=unknown CC0=%x valid=%u UTMI-only\n",cable.cc0,cable.valid);return false;}
    return qmpInit(reverse!=0);
}
// The b5q EL2 XPU rejects even SMR reads at EL1. No mapping, ID register,
// allocator scan or diagnostic may touch apps_smmu here. A future loader-owned
// EFI_HAL_IOMMU_PROTOCOL handoff must prove the coherent USB domain first.
bool gDmaReady, gTypecReady;
template<typename T>
bool readChosen(IORegistryEntry *chosen, const char *name, T &value) {
    OSData *data = chosen ? OSDynamicCast(OSData, chosen->getProperty(name)) : nullptr;
    if (!data || data->getLength() != sizeof(value)) return false;
    memcpy(&value, data->getBytesNoCopy(), sizeof(value));
    return true;
}

struct DmaRange {uint64_t base,bytes;};
DmaRange gDmaRam[17],gDmaExcluded[128];unsigned gDmaRamCount,gDmaExcludedCount;
bool smmuIdentity() {
    IORegistryEntry *chosen = IORegistryEntry::fromPath("/chosen", gIODTPlane);
    uint32_t flag = 0;
    B5qUsbDmaHandoff::State state = {};
    const bool hasFlag = readChosen(chosen, "b5q-usb-dma-ready", flag);
    const bool hasState = readChosen(chosen, "b5q-usb-dma-state", state);
    B5qUsbDmaHandoff::Diagnostics diag={};
    const bool hasDiag=readChosen(chosen,"b5q-usb-dma-diagnostics",diag);
    gDmaRamCount=gDmaExcludedCount=0;
    if(hasState)gDmaRam[gDmaRamCount++]={state.ownedBase,state.ownedBytes};
    for(unsigned kind=0;chosen&&kind<2;kind++){
        const char *key=kind?"darwinboot-memory-excluded":"darwinboot-memory-outside";
        auto *data=OSDynamicCast(OSData,chosen->getProperty(key));
        if(!data||data->getLength()%16)continue;
        for(unsigned i=0;i<data->getLength()/16;i++){
            DmaRange range={};memcpy(&range,static_cast<const uint8_t*>(data->getBytesNoCopy())+16*i,16);
            if(!range.bytes||range.bytes>UINT64_MAX-range.base)continue;
            if(kind){if(gDmaExcludedCount<128)gDmaExcluded[gDmaExcludedCount++]=range;}
            else if(gDmaRamCount<17)gDmaRam[gDmaRamCount++]=range;
        }
    }
    if(hasDiag)IOLog("qcom-dwc3: firmware-dma-ext table=%llx+%llx mapped=%llx used-pages=%u flush=%x coverage=%llx retention=%llx prepare=%llx\n",diag.tableBase,diag.tableBytes,diag.mappedBytes,diag.usedPages,diag.flush,diag.coverageStatus,diag.retentionStatus,diag.prepareStatus);
    OSSafeReleaseNULL(chosen);
    if (hasState) {
        IOLog("qcom-dwc3: firmware-dma v=%u sid=%x locate=%llx create=%x configure=%x attach=%x map=%x owned=%llx+%llx\n",
              state.version, state.sid, state.locate, state.create, state.configure,
              state.attach, state.map, state.ownedBase, state.ownedBytes);
    }
    const bool ready = hasFlag && hasState && hasDiag && !diag.prepareStatus && !diag.flush && !diag.coverageStatus && !diag.retentionStatus && diag.usedPages && B5qUsbDmaHandoff::ready(flag, state);
    native_usb_stats[7] = ready ? state.sid : ~0u;
    IOLog("qcom-dwc3: stage=5 smmu=skipped-el2-xpu firmware-dma-ready=%u flag=%u state-present=%u\n",
          ready, flag, hasState);
    return ready;
}
}  // namespace

// A controller's provider: a register window and the core interrupt, in the IOService terms IOFilterInterruptEventSource uses. Device and
// host have a nub each and share the one line: it goes to the nub of the role the core is in.
class QcomDwc3Nub;
static QcomDwc3Nub *gActiveNub;
static IOSimpleLock *gInterruptLock;
static bool gLineAttached,gLineAttaching;
static B5qUsbIrq::Window gIrqWindow;
static uint64_t gIrqSecond;
static bool gIrqStormed;
class QcomDwc3Nub : public IOService {
    OSDeclareDefaultStructors(QcomDwc3Nub)
    IOInterruptAction action = nullptr;
    OSObject *target = nullptr;
    void *refcon = nullptr;
    bool enabled = false;
    uint32_t inFlight=0;
    static bool ensureLock(){
        if(__atomic_load_n(&gInterruptLock,__ATOMIC_ACQUIRE))return true;
        auto *made=IOSimpleLockAlloc();if(!made)return false;
        IOSimpleLock *expected=nullptr;
        if(!__atomic_compare_exchange_n(&gInterruptLock,&expected,made,false,__ATOMIC_RELEASE,__ATOMIC_ACQUIRE))IOSimpleLockFree(made);
        return true;
    }
    static void primary(void *) {
        __atomic_fetch_add(&native_usb_stats[11],1u,__ATOMIC_RELAXED);
        if(!__atomic_load_n(&gInterruptLock,__ATOMIC_ACQUIRE)){armcpu_spi_mask(kIrq,true);return;}
        const auto state=IOSimpleLockLockDisableInterrupt(gInterruptLock);
        QcomDwc3Nub *self=gActiveNub;
        IOInterruptAction callback=nullptr;OSObject *owner=nullptr;void *context=nullptr;
        if(gIrqWindow.observe(mach_absolute_time(),gIrqSecond))gIrqStormed=true;
        if(!gIrqStormed&&self&&self->enabled&&self->action){
            owner=self->target;
            callback=self->action;context=self->refcon;++self->inFlight;
        }else armcpu_spi_mask(kIrq,true);
        IOSimpleLockUnlockEnableInterrupt(gInterruptLock,state);
        if(!callback)return;
        callback(owner,context,self,0);
        const auto done=IOSimpleLockLockDisableInterrupt(gInterruptLock);
        --self->inFlight;
        IOSimpleLockUnlockEnableInterrupt(gInterruptLock,done);
    }
    void unmaskLocked(){
        if(gActiveNub==this)armcpu_spi_mask(kIrq,gIrqStormed||!enabled);
    }
    void drain(){
        for(;;){
            const auto state=IOSimpleLockLockDisableInterrupt(gInterruptLock);
            const bool idle=inFlight==0;
            IOSimpleLockUnlockEnableInterrupt(gInterruptLock,state);
            if(idle)return;IOSleep(1);
        }
    }
public:
    static void route(QcomDwc3Nub *nub) {
        armcpu_spi_mask(kIrq,true);
        if(!ensureLock())return;
        if(nub)nub->retain();
        const auto state=IOSimpleLockLockDisableInterrupt(gInterruptLock);
        auto *old=gActiveNub;gActiveNub=nub;gIrqStormed=false;gIrqWindow={};
        if(nub)nub->unmaskLocked();
        IOSimpleLockUnlockEnableInterrupt(gInterruptLock,state);
        if(old){if(old!=nub)old->drain();old->release();}
    }
    IOReturn getInterruptType(int source,int *type) override {
        if(source!=0||!type)return kIOReturnNoInterrupt;
        *type=kIOInterruptTypeLevel;return kIOReturnSuccess;
    }
    IOReturn registerInterrupt(int source,OSObject *owner,IOInterruptAction handler,void *context) override {
        if(source!=0||!owner||!handler)return kIOReturnNoInterrupt;
        if(!ensureLock())return kIOReturnNoResources;
        uint64_t second=0;clock_interval_to_absolutetime_interval(1000,NSEC_PER_MSEC,&second);
        const auto state=IOSimpleLockLockDisableInterrupt(gInterruptLock);
        if(action||gLineAttaching){IOSimpleLockUnlockEnableInterrupt(gInterruptLock,state);return kIOReturnNoResources;}
        owner->retain();target=owner;refcon=context;action=handler;enabled=false;gIrqSecond=second;
        const bool attach=!gLineAttached;if(attach)gLineAttaching=true;
        IOSimpleLockUnlockEnableInterrupt(gInterruptLock,state);
        int result=kIOReturnSuccess;
        if(attach){result=armcpu_spi_attach(kIrq,false,primary,nullptr,nullptr,nullptr);armcpu_spi_mask(kIrq,true);}
        const auto ready=IOSimpleLockLockDisableInterrupt(gInterruptLock);
        if(attach){gLineAttaching=false;gLineAttached=result==kIOReturnSuccess;}
        if(result==kIOReturnSuccess)unmaskLocked();
        IOSimpleLockUnlockEnableInterrupt(gInterruptLock,ready);
        if(result!=kIOReturnSuccess){unregisterInterrupt(0);return kIOReturnNoResources;}
        return kIOReturnSuccess;
    }
    IOReturn unregisterInterrupt(int source) override {
        if(source!=0)return kIOReturnNoInterrupt;
        if(!ensureLock())return kIOReturnNoResources;
        const auto state=IOSimpleLockLockDisableInterrupt(gInterruptLock);
        enabled=false;unmaskLocked();auto *old=target;
        action=nullptr;target=nullptr;refcon=nullptr;
        IOSimpleLockUnlockEnableInterrupt(gInterruptLock,state);
        drain();OSSafeReleaseNULL(old);return kIOReturnSuccess;
    }
    IOReturn enableInterrupt(int source) override {
        if(source!=0)return kIOReturnNoInterrupt;
        if(!ensureLock())return kIOReturnNoResources;
        const auto state=IOSimpleLockLockDisableInterrupt(gInterruptLock);
        const bool allowed=!gIrqStormed&&action;enabled=allowed;unmaskLocked();
        IOSimpleLockUnlockEnableInterrupt(gInterruptLock,state);
        return allowed?kIOReturnSuccess:kIOReturnNotReady;
    }
    IOReturn disableInterrupt(int source) override {
        if(source!=0)return kIOReturnNoInterrupt;
        if(!ensureLock())return kIOReturnNoResources;
        const auto state=IOSimpleLockLockDisableInterrupt(gInterruptLock);
        enabled=false;unmaskLocked();IOSimpleLockUnlockEnableInterrupt(gInterruptLock,state);
        return kIOReturnSuccess;
    }
};
OSDefineMetaClassAndStructors(QcomDwc3Nub, IOService)

// Whether the device stack may have the core: false while the core is in the host role or going there.
static volatile bool gDeviceStackAllowed = false;
static bool gDevicePowerAcknowledged;
static uint32_t gDevicePowerOnAtAttach;
static uint32_t gXdciDesiredCalls,gXdciDesired,gXdciCableCalls;
class QcomDwc3Xdci : public AppleUSBXDCI {
    OSDeclareDefaultStructors(QcomDwc3Xdci)
    uint32_t read(uint32_t offset) {return (*reinterpret_cast<volatile uint32_t **>(reinterpret_cast<uint8_t *>(this) + 0x450))[offset / 4];}
    void write(uint32_t offset, uint32_t value) {(*reinterpret_cast<volatile uint32_t **>(reinterpret_cast<uint8_t *>(this) + 0x450))[offset / 4] = value; barrier();}
public:
    bool start(IOService *provider) override {
        uint8_t *self = reinterpret_cast<uint8_t *>(this);
        IOMemoryMap *map = provider->mapDeviceMemoryWithIndex(0, kIOMapInhibitCache);
        if (!map) return false;
        *reinterpret_cast<IOMemoryMap **>(self + 0x448) = map;
        *reinterpret_cast<uint64_t *>(self + 0x450) = map->getVirtualAddress();
        const bool started=AppleUSBXDCI::start(provider);
        IOLog("qcom-dwc3: device stage=family-start result=%u pwr=%u\n",started,getPowerState());
        return started;
    }
    // True keeps the family's already selected configuration list (IOUSBDeviceController builds it when this is false): Apple's SoC
    // classes answer from their IOPort transport object, and this class has none. The USB 3 descriptors follow the speed instead.
    bool XDCI_KEEP_CONFIGURATIONS() override {return false;}
    bool XDCI_TRANSPORT_ACTIVE() override {return true;}
    // The power the family asks for at each change, including when configd's description starts the stack: off while the host role has the core.
    uint32_t XDCI_DESIRED_POWER() override {
        const uint32_t wanted=__atomic_load_n(&gDeviceStackAllowed,__ATOMIC_ACQUIRE) ? AppleUSBXDCI::XDCI_DESIRED_POWER() : 0;
        __atomic_store_n(&gXdciDesired,wanted,__ATOMIC_RELEASE);
        if(__atomic_fetch_add(&gXdciDesiredCalls,1u,__ATOMIC_RELAXED)<4)
            IOLog("qcom-dwc3: device stage=desired-power allowed=%u wanted=%u pwr=%u\n",__atomic_load_n(&gDeviceStackAllowed,__ATOMIC_ACQUIRE),wanted,getPowerState());
        return wanted;
    }
    IOReturn XDCI_POWER_ON() override {
        native_usb_stats[12] = native_usb_stats[12] + 1;
        IOLog("qcom-dwc3: device stage=power-on callback=%u\n",native_usb_stats[12]);
        vbusOverride(true);
        native_usb_stats[15] = read(0x70c);
        return kIOReturnSuccess;
    }
    IOReturn XDCI_POWER_OFF() override {
        native_usb_stats[13] = native_usb_stats[13] + 1;
        vbusOverride(false);
        return kIOReturnSuccess;
    }
    // One event buffer and interrupter; the Linux driver has one as well. The scale and the periodic count are read in the reset.
    void XDCI_PARAMETERS() override {
        uint32_t *fields = reinterpret_cast<uint32_t *>(reinterpret_cast<uint8_t *>(this) + 0x2628);
        fields[0] = 1; fields[1] = 0; fields[2] = 4; fields[3] = 4;
    }
    IOReturn XDCI_CONTROLLER_RESET() override {
        const IOReturn result = AppleUSBXDCI::XDCI_CONTROLLER_RESET();
        native_usb_stats[14] = (uint32_t)result;
        if (result != kIOReturnSuccess) return result;
        uint32_t *fields = reinterpret_cast<uint32_t *>(reinterpret_cast<uint8_t *>(this) + 0x2628);
        // dwc3_core_setup_global_control keeps the power down scale the hardware resets to when there is no suspend clock.
        const uint32_t gctl = read(0x110);
        fields[1] = gctl >> 19;
        write(0x110, (gctl & ~(3u << 12)) | 2u << 12);
        // dwc3_gadget_setup_nump: RAM2 bytes less 24 for the event overhead and 16 per setup, in 1 KiB packets, at most 16.
        const uint32_t hw0 = read(0x140), hw6 = read(0x158), hw7 = read(0x15c);
        const uint32_t mdwidth = ((hw0 >> 8) & 0xffu) | ((hw6 >> 8) & 3u) << 8;
        const uint32_t ram2 = hw7 >> 16;
        uint32_t nump = ram2 * mdwidth / 8 > 40 ? (ram2 * mdwidth / 8 - 40) / 1024 : 1;
        fields[2] = nump > 16 ? 16 : nump ? nump : 1;
        native_usb_stats[2] = hw0; native_usb_stats[3] = read(0x14c); native_usb_stats[4] = hw7;
        // snps,dis_u2_susphy_quirk, snps,dis_enblslpm_quirk: this board never suspends the eUSB2 PHY clock from the core.
        write(0x200, read(0x200) & ~(1u << 6 | 1u << 8));
        write(0x2c0, read(0x2c0) & ~(1u << 17));
        if (!gSuperSpeed) write(0x700, read(0x700) & ~7u);   // High speed
        native_usb_stats[16] = read(0x700); native_usb_stats[17] = read(0x110); native_usb_stats[18] = read(0x200);
        return result;
    }
    // Bandwidth accounting of Apple's fabric: nothing to vote for on this SoC, the SN2 vote covers the peak.
    // The family's power states: 4 starts the bus (the cable-connected path of Apple's SoC classes), 0 takes it off.
    IOReturn cable(bool connected) {
        __atomic_fetch_add(&gXdciCableCalls,1u,__ATOMIC_RELAXED);
        const IOReturn result=changePowerStateTo(connected ? 4 : 0);
        gDevicePowerAcknowledged=connected && result==kIOPMAckImplied;
        IOLog("qcom-dwc3: device stage=cable-request connected=%u target=%u result=%x pwr=%u\n",connected,connected?4:0,result,getPowerState());
        return result;
    }
    uint32_t XDCI_PERIODIC_USAGE() override {return *reinterpret_cast<uint32_t *>(reinterpret_cast<uint8_t *>(this) + 0x58c) != 0;}
    void XDCI_PERIODIC_SET(uint32_t) override {}
};
OSDefineMetaClassAndStructors(QcomDwc3Xdci, AppleUSBXDCI)

// Host mode: Apple's xHCI driver as it is on a PCI controller, with what Linux's dwc3 host glue requires of the core.
class QcomDwc3Xhci : public AppleUSBXHCI {
    OSDeclareDefaultStructors(QcomDwc3Xhci)
public:
    bool start(IOService *provider) override {
        const bool started=AppleUSBXHCI::start(provider);
        if(started){
            restoreHostGlobals();
            configureHostPorts(this);
            hostCheckpoint("after-family-start",true);
        }
        return started;
    }
    // Once the ports exist the family leaves the controller's power to them, and an idle port lets it fall to off: a halted controller reports
    // no attach, and what wakes it on Apple's hardware is the Type-C transport's cable report, which this class does not have. The role follows
    // the port manager, so this controller exists only with a peripheral on the cable: kPowerStateOn for as long as it exists.
    uint32_t XHCI_DESIRED_POWER() override {return 3;}
    IOReturn setPowerState(unsigned long state,IOService *device) override {
        // Capture before Apple's saveState can touch a faulted controller.
        restoreHostGlobals();
        hostCheckpoint("before-power-state",true,false);
        IOReturn result=AppleUSBXHCI::setPowerState(state,device);
        restoreHostGlobals();
        if(result!=kIOReturnSuccess)hostCheckpoint("power-state-result",true);
        return result;
    }
    // write-64-hi-lo-quirk: a 64-bit register is two 32-bit accesses, the high half written first.
    uint64_t XHCI_READ64(void *base, uint32_t offset) override {
        hostCheckpoint("read64");
        volatile uint32_t *at = reinterpret_cast<volatile uint32_t *>(static_cast<uint8_t *>(base) + offset);
        const uint64_t low = at[0];
        return low | (uint64_t)at[1] << 32;
    }
    void XHCI_WRITE64(void *base, uint32_t offset, uint64_t value) override {
        volatile uint32_t *at = reinterpret_cast<volatile uint32_t *>(static_cast<uint8_t *>(base) + offset);
        at[1] = (uint32_t)(value >> 32);
        barrier();
        at[0] = (uint32_t)value;
        barrier();
        hostCheckpoint("write64");
        static uint32_t writes=0;
        const unsigned count=__atomic_fetch_add(&writes,1u,__ATOMIC_RELAXED)+1;
        if(count==1)hostCheckpoint("first-write64",true);
        if(count<=16&&(value||offset==0x30||offset==0x38)){
            uint32_t lo=at[0],hi=at[1];
            IOLog("qcom-dwc3: xhci-w64 #%u off=%x val=%llx rb=%08x:%08x\n",count,offset,value,hi,lo);
            if(value&&offset!=0x18&&!lo&&!hi){
                at[0]=(uint32_t)value;barrier();at[1]=(uint32_t)(value>>32);barrier();
                lo=at[0];hi=at[1];
                IOLog("qcom-dwc3: xhci-w64 #%u off=%x val=%llx rb2=%08x:%08x\n",count,offset,value,hi,lo);
            }
        }
    }
};
OSDefineMetaClassAndStructors(QcomDwc3Xhci, AppleUSBXHCI)

namespace {
bool bringUp() {
    stage(1);
    if (!mapRegion(gGcc, kGcc, 0x1f0000) || !mapRegion(gTcsrMap, kTcsr, 0x1000) || !mapRegion(gPhy, kPhy, 0x1000) ||
        !mapRegion(gScratch, kQscratch & ~0xfffull, 0x1000)) {stage(-1); return false;}
    gScratch.va += (kQscratch & 0xfff) / 4;
    stage(2);
    if (!powerRails()) {stage(-2); return false;}
    stage(3);
    if (!gdsc(0x50018, 6) || !gdsc(0x39004, 5)) {stage(-3); return false;}
    stage(4);
    if (!clocksAndResets()) {stage(-4); return false;}
    stage(5);
    gDmaReady = smmuIdentity();
    stage(6);
    gTypecReady = b5q_usb_typec_init();
    IOLog("qcom-dwc3: stage=6 typec-ready=%u\n",gTypecReady);
    IOLog("qcom-dwc3: stage=6 repeater=before address=3e\n");
    const bool repeaterReady = repeater(true, false);
    IOLog("qcom-dwc3: stage=6 repeater=after ready=%u\n",repeaterReady);
    if (!repeaterReady) {stage(-6); return false;}
    stage(7);
    phyInit();
    IOSleep(2);
    IOLog("qcom-dwc3: stage=7 eusb2=initialized qmp=before pairs=168\n");
    gSuperSpeed = superSpeedInit();
    if (!gSuperSpeed) selectUtmiClock();
    IOLog("qcom-dwc3: stage=7 qmp=%u pairs=168 status=%x utmi-fallback=%u\n",gSuperSpeed,native_usb_stats[33],!gSuperSpeed);
    stage(8);
    Region window = {};
    if (!mapRegion(window, kAppleWindow, 0x1000)) {stage(-8); return false;}
    const uint32_t id = window.va[0x120 / 4];
    native_usb_stats[1] = id;
    window.map->release();
    if ((id & 0xffff0000u) != 0x55330000u && (id & 0xffff0000u) != 0x33310000u && (id & 0xffff0000u) != 0x33320000u) {stage(-9); return false;}
    stage(9);
    IOLog("qcom-dwc3: GSNPSID=%08x hardware-ready dma-ready=%u\n",id,gDmaReady);
    return true;
}
}  // namespace
QcomDwc3Xdci *gController;
int gVbusOn = -1, gVbusApplied = -1;
// One role at a time, changed on one thread: the system's start and stop paths block, and the battery work loop reports the cable.
enum Role {kRoleNone, kRoleDevice, kRoleHost};
IOLock *gRoleLock;
int gRoleWanted,gRoleApplied,gCoreRole=kRoleDevice;
uint32_t gCableWanted, gCableApplied;
bool gForceHost;
constexpr unsigned kXhciRegisterBytes=0x8000; // same bounded host window as makeHost()
constexpr uint32_t kGctlDisableClockGating=1u;
constexpr uint32_t kUsb2EnableLpm=1u<<8,kUsb2SuspendPhy=1u<<6,kUsb3SuspendPhy=1u<<17;
constexpr uint32_t kGuctlSprsCtrlTransEn=1u<<17,kGuctl1Host=(1u<<21)|(1u<<8),kGuctl2Host=1u<<16;
constexpr uint32_t kUsbPortDebugOptions=0x40000119u;
constexpr unsigned kHostEventDumpCount=16;
Region gGlobals, gXhciRegs;
QcomDwc3Nub *gDeviceNub, *gHostNub;
QcomDwc3Xhci *gHost;
void restoreHostGlobals() {
    if(!gGlobals.va)return;
    auto *gctl=gGlobals.va+0x110/4,*guctl=gGlobals.va+0x12c/4,*guctl1=gGlobals.va+0x11c/4,*guctl2=gGlobals.va+0x60c/4;
    auto *usb2=gGlobals.va+0x200/4,*usb3=gGlobals.va+0x2c0/4;
    *gctl|=kGctlDisableClockGating;
    *usb2&=~(kUsb2SuspendPhy|kUsb2EnableLpm);*usb3&=~kUsb3SuspendPhy;
    *guctl|=kGuctlSprsCtrlTransEn;
    *guctl1=(*guctl1&~(7u<<21))|kGuctl1Host;
    *guctl2|=kGuctl2Host;
    barrier();
}
void wantRole(int role) {
    if (!gRoleLock) return;
    IOLockLock(gRoleLock);
    __atomic_store_n(&gRoleWanted,role,__ATOMIC_RELEASE);
    IOLockWakeup(gRoleLock, &gRoleWanted, false);
    IOLockUnlock(gRoleLock);
}
// A data-role, power-role or CC orientation change restarts the existing
// serialized role lifecycle, including when the data role itself stayed Host.
void cableChanged() {
    B5qMax77705::Cable cable;b5q_usb_cable_state(&cable);
    if(!gRoleLock)return;
    IOLockLock(gRoleLock);
    gCableWanted=cable.signature();
    __atomic_store_n(&gRoleWanted,__atomic_load_n(&gForceHost,__ATOMIC_ACQUIRE)?kRoleHost:cable.role(),__ATOMIC_RELEASE);
    IOLockWakeup(gRoleLock,&gRoleWanted,false);
    IOLockUnlock(gRoleLock);
}
void forceHostThread(void *seconds, wait_result_t) {
    IOSleep((uint32_t)reinterpret_cast<uintptr_t>(seconds) * 1000);
    __atomic_store_n(&gForceHost,true,__ATOMIC_RELEASE);
    cableChanged();
    // usb-back=<seconds in the host role>: then what the cable says, for an unattended run of the way back.
    unsigned back = 0;
    if (PE_parse_boot_argn("usb-back", &back, sizeof back) && back) {
        IOSleep(back * 1000);
        __atomic_store_n(&gForceHost,false,__ATOMIC_RELEASE);
        cableChanged();
    }
}
void leaveRole(int role) {
    if (!gDmaReady) {if (role == kRoleHost) b5q_usb_otg(false); return;}
    if (role == kRoleDevice) {
        __atomic_store_n(&gDeviceStackAllowed,false,__ATOMIC_RELEASE);
        IOService::getResourceService()->removeProperty("AppleUSBCableType");
        // The family stops the bus through XDCI_POWER_OFF; with no description from configd yet the bus was never on and it does not come.
        const uint32_t before = native_usb_stats[13];
        native_usb_stats[20] = (uint32_t)gController->cable(false);
        for (unsigned i = 0; i < 200 && native_usb_stats[13] == before; ++i) IOSleep(10);
    } else if (role == kRoleHost) {
        b5q_usb_otg(false);
        if(!gHostNub)return;
        // A removed PCI controller's path: the family stops its devices and the controller.
        QcomDwc3Nub::route(nullptr);
        gHostNub->terminate(kIOServiceSynchronous);
        gHostNub->release();
        gHostNub = nullptr; gHost = nullptr;
    }
}
// __dwc3_set_mode: a core soft reset between the roles, then the port capability.
bool setCoreRole(int role,bool forceReset=false) {
    (void)forceReset;
    __atomic_store_n(&gDeviceStackAllowed,false,__ATOMIC_RELEASE);
    QcomDwc3Nub::route(nullptr);
    auto *gctl=gGlobals.va+0x110/4;
    auto *usb2=gGlobals.va+0x200/4,*usb3=gGlobals.va+0x2c0/4;
    *gctl|=1u<<11;
    barrier();IOSleep(100);
    *gctl&=~(1u<<11);barrier();IOSleep(1);
    // Stock b5q snps,disable-clk-gating: reset must not leave the host bus
    // clock auto-gated while Apple probes or saves its registers.
    *gctl=(*gctl&~(3u<<12))|((role==kRoleHost?1u:2u)<<12)|kGctlDisableClockGating;
    *usb2&=~(kUsb2SuspendPhy|kUsb2EnableLpm);*usb3&=~kUsb3SuspendPhy;barrier();
    if(role==kRoleHost)restoreHostGlobals();
    const bool repeaterReady=repeater(false,role==kRoleHost);
    if(!repeaterReady)return false;
    gCoreRole=role;
    return true;
}
// Lanes follow Samsung PDIC CCPinStat. The role thread has already stopped
// the previous controller before resetting a PHY on a changed connector.
bool followOrientation() {
    B5qMax77705::Cable cable;b5q_usb_cable_state(&cable);
    const int reverse=cable.orientation();
    if (gDpLanes==4) {selectUtmiClock();return false;}
    if (!gSuperSpeed || uint32_t(reverse) != native_usb_stats[34]) {
        gSuperSpeed = superSpeedInit();
        if (!gSuperSpeed) selectUtmiClock();
        return true;
    }
    return false;
}
void enterHost() {
    QcomDwc3Nub *nub = OSTypeAlloc(QcomDwc3Nub);
    // DWC3_XHCI_REGS_END: the host registers below the global ones.
    IODeviceMemory *range = IODeviceMemory::withRange(kCore, 0x8000);
    OSArray *ranges = range ? OSArray::withObjects((const OSObject **)&range, 1) : nullptr;
    const uint32_t busNumber=0;
    OSData *zero = OSData::withBytes(&busNumber,sizeof(busNumber));
    bool done = false;
    if (nub && nub->init() && ranges && zero) {
        nub->setDeviceMemory(ranges);
        nub->setName("usb-host0");
        nub->setProperty("bus-number", zero);
        if (nub->attach(IOService::getPlatform())) {
            nub->registerService();
            QcomDwc3Nub::route(nub);
            QcomDwc3Xhci *host = OSTypeAlloc(QcomDwc3Xhci);
            if (host && host->init() && host->attach(nub)) {
                done = host->start(nub);
                if (!done) host->detach(nub);
                else gHost = host;
            }
            OSSafeReleaseNULL(host);
        }
    }
    native_usb_stats[46] = (native_usb_stats[46] & 0xffff0000u) | (done ? 1u : 2u);
    OSSafeReleaseNULL(ranges); OSSafeReleaseNULL(range); OSSafeReleaseNULL(zero);
    if (done) gHostNub = nub;
    else if (nub) {QcomDwc3Nub::route(nullptr); nub->terminate(kIOServiceSynchronous); nub->release();}
}
bool enterRole(int role) {
    if (!gDmaReady) {
        // PHY and Type-C diagnostics can run without sourcing VBUS or starting DMA.
        if (role == kRoleNone) return b5q_usb_otg(false);
        if (!b5q_usb_otg(false) || !repeater(false,role == kRoleHost)) return false;
        followOrientation();
        IOLog("qcom-dwc3: hardware-only role=%u dma=deferred-no-firmware-handoff\n",role);
        return true;
    }
    if (role == kRoleNone) return b5q_usb_otg(false);
    B5qMax77705::Cable cable;
    if(!b5q_usb_cable_state(&cable)||cable.water())return false;
    // Power role is independent of DFP/UFP. In particular a powered PD Hub
    // can be Sink+DFP: disable our boost and let its VBUS supply the bus.
    const bool source=cable.sourceVbus(role);
    if(!b5q_usb_otg(source)){IOLog("qcom-dwc3: power transition rejected source=%u power=%u data=%d\n",source,cable.power(),role);return false;}
    IOLog("qcom-dwc3: role=%d power=%u vbus-source=%u external-hub=%u\n",role,cable.power(),source,role==kRoleHost&&cable.power()==1);
    const bool phyReset=followOrientation() || gPhyResetPending;gPhyResetPending=false;
    if(!setCoreRole(role,phyReset)){b5q_usb_otg(false);return false;}
    IOLog("qcom-dwc3: host-core role=%d orientation=%d phy-reset=%u qmp=%u GCTL=%x GSBUSCFG0=%x GUCTL=%x GUCTL1=%x GUCTL2=%x\n",role,cable.orientation(),phyReset,gSuperSpeed,gGlobals.va[0x110/4],gGlobals.va[0x100/4],gGlobals.va[0x12c/4],gGlobals.va[0x11c/4],gGlobals.va[0x60c/4]);
    if (role == kRoleHost) {
        vbusOverride(false);
        enterHost();
        if(!gHost){b5q_usb_otg(false);return false;}
    } else {
        QcomDwc3Nub::route(gDeviceNub);
        __atomic_store_n(&gDeviceStackAllowed,true,__ATOMIC_RELEASE);
        // A USB host on the cable: lockdownd's launch event, then the family goes on the bus when configd's description arrives.
        IOService::getResourceService()->setProperty("AppleUSBCableType", "USBHost");
        gDevicePowerOnAtAttach=native_usb_stats[12];gDevicePowerAcknowledged=false;
        native_usb_stats[20] = (uint32_t)gController->cable(true);
    }
    return true;
}
// A RAM read is authorized only by the loader's usable owned/outside ranges.
// No allocations, mapping changes, SMMU MMIO or reads of an arbitrary bus PA.
bool dmaRead64(uint64_t pa,uint64_t &value){
    if((pa&7)||pa>UINT64_MAX-8)return false;
    for(unsigned i=0;i<gDmaExcludedCount;i++)if(pa<gDmaExcluded[i].base+gDmaExcluded[i].bytes&&gDmaExcluded[i].base<pa+8)return false;
    for(unsigned i=0;i<gDmaRamCount;i++)if(pa>=gDmaRam[i].base&&pa+8<=gDmaRam[i].base+gDmaRam[i].bytes){value=ml_phys_read_double_64(pa);return true;}
    return false;
}
void dmaDiagnostics(const char *reason){
    if(!gXhciRegs.va||!gGlobals.va)return;
    const unsigned cap=gXhciRegs.va[0]&255,rt=gXhciRegs.va[0x18/4]&~31u;
    if(cap+0x418>kXhciRegisterBytes||rt+0x40>kXhciRegisterBytes)return;
    auto *op=gXhciRegs.va+cap/4;auto *ir=gXhciRegs.va+rt/4;
    const uint64_t dcbaa=uint64_t(op[0x30/4])|(uint64_t(op[0x34/4])<<32);
    const uint64_t erst=uint64_t(ir[0x30/4])|(uint64_t(ir[0x34/4])<<32);
    const uint64_t crcr=uint64_t(op[0x18/4])|(uint64_t(op[0x1c/4])<<32);
    const uint64_t erdp=uint64_t(ir[0x38/4])|(uint64_t(ir[0x3c/4])<<32);
    const uint32_t hcs2=gXhciRegs.va[8/4];
    IOLog("qcom-dwc3: host-dma-global reason=%s HCSPARAMS2=%x scratchpads=%u GCTL=%x GUCTL=%x GUCTL1=%x GUCTL2=%x GSBUSCFG0=%x GSBUSCFG1=%x GUSB2PHYCFG=%x GUSB3PIPECTL=%x\n",
        reason,hcs2,((hcs2>>27)&31)|(((hcs2>>21)&31)<<5),gGlobals.va[0x110/4],gGlobals.va[0x12c/4],
        gGlobals.va[0x11c/4],gGlobals.va[0x60c/4],gGlobals.va[0x100/4],gGlobals.va[0x104/4],gGlobals.va[0x200/4],gGlobals.va[0x2c0/4]);
    IOLog("qcom-dwc3: host-dma-port reason=%s PORTSC1=%x PORTPMSC1=%x PORTSC2=%x PORTPMSC2=%x QSCRATCH=%x QMP=%x DCBAAP=%llx ERSTBA=%llx ERDP=%llx CRCR=%llx\n",
        reason,op[0x400/4],op[0x404/4],op[0x410/4],op[0x414/4],gScratch.va?gScratch.va[8/4]:0,
        native_usb_stats[33],dcbaa,erst,erdp,crcr);
    uint64_t first=0;bool read=dmaRead64(dcbaa&~63ULL,first);
    IOLog("qcom-dwc3: host-dma-diag DCBAA[0]=%llx read=%u\n",first,read);
    const unsigned entries=ir[0x28/4]&65535;
    for(unsigned i=0;i<3&&i<entries;i++){
        uint64_t base=0,details=0;const uint64_t pa=(erst&~63ULL)+16*i;
        bool ok=dmaRead64(pa,base)&&dmaRead64(pa+8,details);
        IOLog("qcom-dwc3: host-dma-diag ERST%u base=%llx words=%llx read=%u\n",i,base,details,ok);
    }
    const bool eventRead=B5qUsbHostEvent::latest(erst&~63ULL,entries,erdp,kHostEventDumpCount,
        [](uint64_t pa,uint64_t &value){return dmaRead64(pa,value);},
        [reason](unsigned segment,unsigned index,const B5qUsbHostEvent::Event &event){
            IOLog("qcom-dwc3: host-event reason=%s segment=%u index=%u cc=%u type=%u slot=%u ep=%u cycle=%u parameter=%llx status=%08x control=%08x\n",
                reason,segment,index,event.completion,event.type,event.slot,event.endpoint,event.cycle,event.parameter,event.status,event.control);
        });
    if(!eventRead)IOLog("qcom-dwc3: host-event reason=%s unavailable entries=%u erdp=%llx\n",reason,entries,erdp);
}
void hostCheckpoint(const char *reason,bool force,bool allowU3){
    if(!gXhciRegs.va)return;
    const unsigned cap=gXhciRegs.va[0]&255;
    if(cap+0x404>kXhciRegisterBytes)return;
    const uint32_t status=gXhciRegs.va[(cap+4)/4];
    const uint32_t port=gXhciRegs.va[(cap+0x400)/4];
    static uint32_t seenHse=0,seenHce=0,seenU3=0;
    const bool firstHse=allowU3&&(status&4)&&!__atomic_exchange_n(&seenHse,1u,__ATOMIC_RELAXED);
    const bool firstHce=allowU3&&!firstHse&&(status&(1u<<12))&&
        !__atomic_exchange_n(&seenHce,1u,__ATOMIC_RELAXED);
    const bool firstU3=allowU3&&!firstHse&&!firstHce&&(port&3u)==3u&&(port&0x1e0u)==0x60u&&
        !__atomic_exchange_n(&seenU3,1u,__ATOMIC_RELAXED);
    if(!force&&!firstHse&&!firstHce&&!firstU3)return;
    dmaDiagnostics(firstHse?"first-HSE":firstHce?"first-HCE":firstU3?"first-U3":reason);
    const unsigned saved=(allowU3&&(firstHse||firstHce||firstU3))?b5q_log_sync(750):0;
    IOLog("qcom-dwc3: host-dma-diag checkpoint=%s sts=%x portsc1=%x sync=%u\n",reason,status,port,saved);
}
void configureHostPorts(IOService *host) {
    if(!host)return;
    OSNumber *mask=OSNumber::withNumber(kUsbPortDebugOptions,32);
    OSDictionary *settings=mask?OSDictionary::withCapacity(1):nullptr;
    if(settings)settings->setObject("kUSBDebugOptions",mask);
    if(settings&&!host->getProperty("B5qHostDebugApplied")&&host->setProperties(settings)==kIOReturnSuccess)
        host->setProperty("B5qHostDebugApplied",mask);
    OSIterator *children=settings?host->getChildIterator(gIOServicePlane):nullptr;
    while(OSObject *object=children?children->getNextObject():nullptr){
        IOService *port=OSDynamicCast(IOService,object);
        if(!port||!port->metaCast("AppleUSBHostPort"))continue;
        if(!port->getProperty("B5qPortDebugApplied")){
            const IOReturn result=port->setProperties(settings);
            if(result==kIOReturnSuccess){
                port->setProperty("B5qPortDebugApplied",mask);
                IOLog("qcom-dwc3: port-debug name=%s mask=%x rc=%08x\n",port->getName(),kUsbPortDebugOptions,result);
            }
        }
        const bool first=!port->getProperty("B5qPortPowerPinned");
        if(first||port->getPowerState()<3){
            const IOReturn pwrRc=port->changePowerStateTo(3);
            OSNumber *logs=OSDynamicCast(OSNumber,port->getProperty("B5qPortPowerLogs"));
            const unsigned logged=logs?logs->unsigned32BitValue():0;
            if((first||pwrRc!=kIOReturnSuccess)&&logged<4){
                IOLog("qcom-dwc3: port-power name=%s cur=%lu req=3 rc=%08x\n",port->getName(),(unsigned long)port->getPowerState(),pwrRc);
                port->setProperty("B5qPortPowerLogs",logged+1,32);
            }
            if(pwrRc==kIOReturnSuccess)port->setProperty("B5qPortPowerPinned",kOSBooleanTrue);
        }
    }
    OSSafeReleaseNULL(children);OSSafeReleaseNULL(settings);OSSafeReleaseNULL(mask);
}
void hostStats() {
    if (!gDmaReady || gCoreRole != kRoleHost) return;
    const uint32_t cap = gXhciRegs.va[0];
    const volatile uint32_t *op = gXhciRegs.va + (cap & 0xffu) / 4;
    native_usb_stats[47] = op[0]; native_usb_stats[48] = op[1];
    hostCheckpoint("poll",false,true);
    configureHostPorts(gHost);
    native_usb_stats[49] = op[0x400 / 4]; native_usb_stats[50] = op[0x410 / 4];
    native_usb_stats[51] = gXhciRegs.va[1];
    const uint64_t crcr=uint64_t(op[0x18/4])|(uint64_t(op[0x1c/4])<<32);
    const uint64_t dcbaa=uint64_t(op[0x30/4])|(uint64_t(op[0x34/4])<<32);
    const unsigned rt=(gXhciRegs.va[0x18/4]&~31u)/4;
    if(rt+0x40/4<kXhciRegisterBytes/4){
        const uint64_t erst=uint64_t(gXhciRegs.va[rt+0x30/4])|(uint64_t(gXhciRegs.va[rt+0x34/4])<<32);
        const uint64_t erdp=uint64_t(gXhciRegs.va[rt+0x38/4])|(uint64_t(gXhciRegs.va[rt+0x3c/4])<<32);
        IOLog("qcom-dwc3: host DMA64=%u crcr=%llx dcbaa=%llx erst=%llx iman=%x routed=%u enabled=%u\n",
          gXhciRegs.va[0x10/4]&1,crcr,dcbaa,erst,gXhciRegs.va[rt+0x20/4],gActiveNub==gHostNub,gLineAttached);
        IOLog("qcom-dwc3: host PORTSC1=%x PORTPMSC1=%x PORTSC2=%x PORTPMSC2=%x ERDP=%llx GSBUSCFG0=%x GUSB2PHYCFG=%x GUSB3PIPECTL=%x GUCTL=%x GUCTL1=%x GUCTL2=%x\n",
              native_usb_stats[49],op[0x404/4],native_usb_stats[50],op[0x414/4],erdp,
              gGlobals.va?gGlobals.va[0x100/4]:0,gGlobals.va?gGlobals.va[0x200/4]:0,
              gGlobals.va?gGlobals.va[0x2c0/4]:0,gGlobals.va?gGlobals.va[0x12c/4]:0,
              gGlobals.va?gGlobals.va[0x11c/4]:0,gGlobals.va?gGlobals.va[0x60c/4]:0);
    }
    if (gHost) native_usb_stats[46] = (native_usb_stats[46] & 0xffff00ffu) | (uint32_t)gHost->getPowerState() << 8;
    // What the system's stack enumerated: how many devices now, the last one's vendor and product (kept after it leaves).
    OSDictionary *match = IOService::serviceMatching("IOUSBHostDevice");
    OSIterator *devices = match ? IOService::getMatchingServices(match) : nullptr;
    uint32_t count = 0;
    OSNumber *debugMask=OSNumber::withNumber(kUsbPortDebugOptions,32);
    OSDictionary *settings=debugMask?OSDictionary::withCapacity(1):nullptr;
    if(settings)settings->setObject("kUSBDebugOptions",debugMask);
    while (OSObject *object = devices ? devices->getNextObject() : nullptr) {
        ++count;
        IOService *dev=OSDynamicCast(IOService,object);
        if(settings&&dev&&!dev->getProperty("B5qDevDebugApplied")&&dev->setProperties(settings)==kIOReturnSuccess)
            dev->setProperty("B5qDevDebugApplied",debugMask);
        IORegistryEntry *entry = OSDynamicCast(IORegistryEntry, object);
        OSNumber *vendor = entry ? OSDynamicCast(OSNumber, entry->getProperty("idVendor")) : nullptr;
        OSNumber *product = entry ? OSDynamicCast(OSNumber, entry->getProperty("idProduct")) : nullptr;
        if (vendor && product) native_usb_stats[53] = vendor->unsigned32BitValue() << 16 | (product->unsigned32BitValue() & 0xffffu);
    }
    native_usb_stats[52] = count;
    IOLog("qcom-dwc3: host cmd=%x sts=%x EINT=%u HSE=%u devs=%u irq=%u storm=%u pwr=%u\n",native_usb_stats[47],native_usb_stats[48],!!(native_usb_stats[48]&8),!!(native_usb_stats[48]&4),count,native_usb_stats[11],gIrqStormed,gHost?unsigned(gHost->getPowerState()):0);
    OSSafeReleaseNULL(settings);OSSafeReleaseNULL(debugMask);
    OSSafeReleaseNULL(devices); OSSafeReleaseNULL(match);
}
void deviceStats() {
    if(!gDmaReady || __atomic_load_n(&gRoleApplied,__ATOMIC_ACQUIRE)!=kRoleDevice || !gGlobals.va)return;
    // Reuse the upstream device-register samples; SMMU diagnostic slots stay
    // zero on b5q. The role worker owns this mapping for its entire lifetime.
    native_usb_stats[26]=gGlobals.va[0x70c/4];
    native_usb_stats[28]=gGlobals.va[0x40c/4];
    native_usb_stats[31]=gGlobals.va[0x408/4];
    IOLog("qcom-dwc3: device dctl=%x dsts=%x events=%x evsz=%x on=%u off=%u irq=%u storm=%u\n",
          gGlobals.va[0x704/4],native_usb_stats[26],native_usb_stats[28],native_usb_stats[31],
          native_usb_stats[12],native_usb_stats[13],native_usb_stats[11],gIrqStormed);
    IOLog("qcom-dwc3: device stage=power-path started=%u allowed=%u requests=%u wanted=%u cable-calls=%u cable-result=%x pwr=%u\n",
          native_usb_stats[19],__atomic_load_n(&gDeviceStackAllowed,__ATOMIC_ACQUIRE),__atomic_load_n(&gXdciDesiredCalls,__ATOMIC_RELAXED),
          __atomic_load_n(&gXdciDesired,__ATOMIC_ACQUIRE),__atomic_load_n(&gXdciCableCalls,__ATOMIC_RELAXED),
          native_usb_stats[20],gController?gController->getPowerState():0);
}
void retryDevicePower() {
    // The role worker owns the controller lifecycle. Re-read connector intent
    // after the timed wait: never retry an old device request after unplug/Host.
    if(!gDmaReady || !gController || __atomic_load_n(&gRoleApplied,__ATOMIC_ACQUIRE)!=kRoleDevice ||
       __atomic_load_n(&gRoleWanted,__ATOMIC_ACQUIRE)!=kRoleDevice || !__atomic_load_n(&gDeviceStackAllowed,__ATOMIC_ACQUIRE))return;
    if(native_usb_stats[12]!=gDevicePowerOnAtAttach)return;
    if(gDevicePowerAcknowledged && native_usb_stats[20]!=kIOPMNotYetInitialized)return;
    native_usb_stats[20]=uint32_t(gController->cable(true));
    IOLog("qcom-dwc3: device stage=power-retry result=%x on=%u acknowledged=%u\n",
          native_usb_stats[20],native_usb_stats[12],gDevicePowerAcknowledged);
}
void roleThread(void *, wait_result_t) {
    const bool dpEnabled=B5qFeatures::option("b5q-dp",B5qFeatures::DisplayPort)!=0;
    for (;;) {
        B5qDpPortState port{};
        if(dpEnabled)b5q_dp_port_poll(&port);
        const unsigned requestedDp=dpEnabled&&port.configured?port.lanes:0;
        B5qMax77705::Cable timing;b5q_usb_cable_state(&timing);
        const unsigned typecPollMs=timing.pollIntervalMs();
        IOLockLock(gRoleLock);
        if(__atomic_load_n(&gRoleWanted,__ATOMIC_ACQUIRE)==__atomic_load_n(&gRoleApplied,__ATOMIC_ACQUIRE)&&gCableWanted==gCableApplied&&requestedDp==gDpLanes){
            uint64_t deadline;clock_interval_to_deadline(typecPollMs,kMillisecondScale,&deadline);
            IOLockSleepDeadline(gRoleLock,&gRoleWanted,deadline,THREAD_UNINT);
            IOLockUnlock(gRoleLock);
            cableChanged();retryDevicePower();hostStats();deviceStats();
            if(dpEnabled){
                b5q_dp_port_poll(&port);
                if((port.configured?port.lanes:0)==gDpLanes)b5q_dp_link_update(&port);
            }
            IOLockLock(gRoleLock);
            if(__atomic_load_n(&gRoleWanted,__ATOMIC_ACQUIRE)==__atomic_load_n(&gRoleApplied,__ATOMIC_ACQUIRE)&&gCableWanted==gCableApplied&&
               (!dpEnabled||(port.configured?port.lanes:0)==gDpLanes)){IOLockUnlock(gRoleLock);continue;}
        }
        const int role = __atomic_load_n(&gRoleWanted,__ATOMIC_ACQUIRE);
        const uint32_t cableVersion = gCableWanted;
        IOLockUnlock(gRoleLock);
        if(dpEnabled&&!b5q_dp_link_stop()){
            // Keep the combo lanes and existing controller intact until
            // DP has actually stopped clocks/scanout. A detached cable
            // still drops our VBUS source immediately.
            B5qMax77705::Cable current;
            if(!b5q_usb_cable_state(&current)||!current.attached())b5q_usb_otg(false);
            IOLog("B5qDP: combo transition deferred: previous link still owned\n");
            IOSleep(100);continue;
        }
        __atomic_store_n(&gDeviceStackAllowed,false,__ATOMIC_RELEASE);
        leaveRole(__atomic_load_n(&gRoleApplied,__ATOMIC_ACQUIRE));
        __atomic_store_n(&gRoleApplied,kRoleNone,__ATOMIC_RELEASE);
        if(dpEnabled){
            gDpLanes=port.configured?port.lanes:0;
            B5qMax77705::Cable cable;b5q_usb_cable_state(&cable);
            if(cable.orientation()>=0){gPhyResetPending=true;gSuperSpeed=qmpInit(cable.orientation()!=0);
                if(gSuperSpeed)native_usb_stats[34]=uint32_t(cable.orientation());
                else selectUtmiClock();}
            IOLog("B5qDP: combo lanes=%u reverse=%d usb3=%u generation=%u\n",gDpLanes,cable.orientation(),gSuperSpeed,port.generation);
        }
        const bool entered=enterRole(role);
        if(dpEnabled)b5q_dp_link_update(&port);
        IOLockLock(gRoleLock);
        gCableApplied=cableVersion;
        if(entered)__atomic_store_n(&gRoleApplied,role,__ATOMIC_RELEASE);
        else {
            __atomic_store_n(&gRoleApplied,kRoleNone,__ATOMIC_RELEASE);
            if(__atomic_load_n(&gRoleWanted,__ATOMIC_ACQUIRE)==role && gCableWanted==cableVersion)__atomic_store_n(&gRoleWanted,kRoleNone,__ATOMIC_RELEASE);
        }
        IOLockUnlock(gRoleLock);
        native_usb_stats[44] = (uint32_t)role | (uint32_t)__atomic_load_n(&gRoleWanted,__ATOMIC_ACQUIRE) << 8 | (uint32_t)gCoreRole << 16;
        native_usb_stats[45] = native_usb_stats[45] + 1;
        native_usb_stats[35] = ((native_usb_stats[35] & 0xffffu) + 1) | (uint32_t)(role == kRoleDevice) << 16;
        if(!entered)IOSleep(1000); // Bounded retries must not spin on a failed I2C/PHY transition.
    }
}
extern "C" void qcom_dwc3_vbus(int online) {
    gVbusOn = online != 0;
    cableChanged();
}
extern "C" void qcom_dwc3_host_load(int result) {native_usb_stats[46] = (uint32_t)result << 16;}
// The hardware, before the classes exist: a failure leaves the system running with USB off.
extern "C" bool qcom_dwc3_bring_up(void) {return bringUp();}
// After the module's metaclasses are registered: publish the provider and start the controller.
// For bring-up (usb=2): controller-only link diagnostics; never read apps_smmu.
// cycle (usb=3) also takes the controller off the bus and back once, the path a cable removal runs, for an unattended host check.
extern "C" void qcom_dwc3_diag(bool cycle) {
    Region window = {};
    if (!gDmaReady || !mapRegion(window, kAppleWindow, 0x1000)) return;
    for (uint32_t tick = 0;; ++tick) {
        const uint32_t ltssm = window.va[0x164 / 4];
        native_usb_stats[36] = native_usb_stats[36] | 1u << ((ltssm >> 22) & 15u);
        native_usb_stats[37] = ltssm;
        if (!(tick % 400)) {
            native_usb_stats[22] = window.va[0x100 / 4]; native_usb_stats[23] = window.va[0x104 / 4]; native_usb_stats[24] = window.va[0x11c / 4];
            native_usb_stats[25] = 0; // SMMU diagnostics forbidden at EL1.
            native_usb_stats[26] = window.va[0x70c / 4]; native_usb_stats[27] = window.va[0x720 / 4]; native_usb_stats[28] = window.va[0x40c / 4];
            native_usb_stats[29] = window.va[0x80c / 4]; native_usb_stats[30] = 0; native_usb_stats[31] = window.va[0x408 / 4];
            native_usb_stats[38] = window.va[0x2c0 / 4];
        }
        if (cycle && tick == 16000) {wantRole(kRoleNone); native_usb_stats[39] = 1;}
        if (cycle && tick == 18000) {wantRole(kRoleDevice); native_usb_stats[39] = 2;}
        IOSleep(5);
    }
}
extern "C" void qcom_dwc3_publish(void) {
    if (!gDmaReady) {
        IOLog("qcom-dwc3: stage=9 controller-DMA=deferred requires=EFI_HAL_IOMMU_PROTOCOL-handoff\n");
        if (!gTypecReady || !b5q_usb_otg(false)) return;
        gRoleLock = IOLockAlloc();
        thread_t thread = nullptr;
        if (!gRoleLock || kernel_thread_start(roleThread,nullptr,&thread) != KERN_SUCCESS) {
            IOLog("qcom-dwc3: hardware-role-thread allocation-failed\n"); return;
        }
        thread_deallocate(thread);
        unsigned forced = 0;
        PE_parse_boot_argn("usb-host",&forced,sizeof forced);
        if (forced && kernel_thread_start(forceHostThread,reinterpret_cast<void *>((uintptr_t)forced),&thread) == KERN_SUCCESS) thread_deallocate(thread);
        cableChanged();
        return;
    }
    const uint32_t busNumber=0;
    static constexpr char kConfigString[]="standardBringup";
    OSData *zero=OSData::withBytes(&busNumber,sizeof(busNumber));
    OSData *config=OSData::withBytes(kConfigString,sizeof(kConfigString));
    QcomDwc3Nub *nub=OSTypeAlloc(QcomDwc3Nub);
    QcomDwc3Xdci *controller=nullptr;
    IOService *platform=IOService::getPlatform();
    IODeviceMemory *range=IODeviceMemory::withRange(kAppleWindow,0x1000);
    OSArray *ranges=range?OSArray::withObjects((const OSObject **)&range,1):nullptr;
    bool nubAttached=false,controllerAttached=false,started=false,published=false;
    do {
        if(!nub||!nub->init()||!ranges||!zero||!config){stage(-12);break;}
        nub->setDeviceMemory(ranges);nub->setName("usb-drd0");
        nub->setProperty("bus-number",zero);nub->setProperty("configuration-string",config);
        nub->setProperty("u1-init-disable",true);nub->setProperty("u2-init-disable",true);
        if(!(nubAttached=nub->attach(platform))){stage(-13);break;}
        stage(10);controller=OSTypeAlloc(QcomDwc3Xdci);
        if(!controller||!controller->init()){stage(-14);break;}
        if(!(controllerAttached=controller->attach(nub))){stage(-15);break;}
        gRoleLock=IOLockAlloc();
        if(!gRoleLock||!mapRegion(gGlobals,kAppleWindow,0x1000)||!mapRegion(gXhciRegs,kCore,kXhciRegisterBytes)){stage(-17);break;}
        started=controller->start(nub);native_usb_stats[19]=started;
        if(!started){stage(-16);break;}
        gController=controller;gDeviceNub=nub;
        stage(11);thread_t thread=nullptr;
        if(kernel_thread_start(roleThread,nullptr,&thread)!=KERN_SUCCESS){stage(-17);break;}
        thread_deallocate(thread);published=true;
        nub->registerService();controller->registerService();
        unsigned forced=0;PE_parse_boot_argn("usb-host",&forced,sizeof(forced));
        if(forced&&kernel_thread_start(forceHostThread,reinterpret_cast<void *>(uintptr_t(forced)),&thread)==KERN_SUCCESS)thread_deallocate(thread);
        cableChanged();stage(12);
    }while(false);
    OSSafeReleaseNULL(config);OSSafeReleaseNULL(zero);OSSafeReleaseNULL(ranges);OSSafeReleaseNULL(range);
    if(!published){
        QcomDwc3Nub::route(nullptr);
        gController=nullptr;gDeviceNub=nullptr;
        if(started)controller->stop(nub);
        if(controllerAttached)controller->detach(nub);
        OSSafeReleaseNULL(controller);
        if(nubAttached)nub->detach(platform);
        OSSafeReleaseNULL(nub);
        OSSafeReleaseNULL(gGlobals.map);gGlobals.va=nullptr;
        OSSafeReleaseNULL(gXhciRegs.map);gXhciRegs.va=nullptr;
        if(gRoleLock){IOLockFree(gRoleLock);gRoleLock=nullptr;}
    }

}
