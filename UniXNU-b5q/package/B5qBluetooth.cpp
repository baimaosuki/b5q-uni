/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#include <IOKit/IOLib.h>
#include <IOKit/IOService.h>
#include <IOKit/IOPlatformExpert.h>
#include <IOKit/IODeviceMemory.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <libkern/c++/OSData.h>
#include <kern/thread.h>
#include <kern/clock.h>
#include <pexpert/pexpert.h>
#include <sys/errno.h>
#include <stdarg.h>
#include "qbt.h"
#include "B5qBtFifo.h"
#include "qbt_transport.h"
#include "Sm8550GeniUart.h"
#include "B5qWcnPower.h"
#include "BluetoothFirmware.h"
#include "BluetoothHciTrace.h"
#include "B5qBtH4Tap.h"

extern "C" int armcpu_spi_attach(uint32_t,bool,void(*)(void *),void *,uint32_t *,uint64_t *);
extern "C" int armcpu_spi_share(uint32_t,void(*)(void *),void *);
extern "C" int armcpu_spi_mask(uint32_t,bool);
extern "C" uint64_t qbt_transport_rx_dropped(void);
// Private exports of the pinned XNU sched_prim.h/thread.h, absent from SDK.
extern "C" kern_return_t clear_wait(thread_t,wait_result_t);
extern "C" void thread_yield_to_preemption(void);
extern "C" volatile int native_gpu_addon_stage;
extern "C" volatile uint32_t native_wifi_stats[29];
extern "C" {
volatile uint64_t native_bluetooth_stats[32];
uint8_t native_bluetooth_boot_rx[512];
volatile uint32_t native_bluetooth_boot_rx_length;
uint8_t native_bluetooth_boot_tail[256];
volatile uint32_t native_bluetooth_boot_tail_length;
/* log-bluetooth=2: pins before TX, RX bytes before TX, then pins, engine status and download reports when startup returns. */
volatile uint32_t native_bluetooth_boot_state[12];
/* log-bluetooth=2: live pid and starts seen for bluetoothd, then for BlueTool. */
volatile uint32_t native_bluetooth_processes[4];
/* log-bluetooth=2: printable runs in controller output, which carry its assert text. */
char *volatile native_bluetooth_boot_text;
volatile uint32_t native_bluetooth_boot_text_length;
/* In-band sleep: wake indications sent, wake acknowledgements sent, sleep indications sent, clock stops undone by a wake
 * inside the stop, writes an idle UART refused, interrupts of the shared line that found the wake disarmed, RX stop timeouts, wakes taken. */
volatile uint64_t native_bluetooth_ibs[8];
/* Per HCI discovery command: sent, completed, status; then received report counts. */
volatile uint32_t native_bluetooth_discovery[18];
}
namespace {
struct bt_hci_trace *hci_trace;
void traceHci(void *, bool tx, uint8_t type, const uint8_t *data, size_t length) {
    uint64_t ns;
    absolutetime_to_nanoseconds(mach_absolute_time(), &ns);
    bt_hci_record(__atomic_load_n(&hci_trace, __ATOMIC_ACQUIRE), ns, tx, type, data, length);
}
struct Region {IOMemoryMap *map;volatile uint32_t *va;};
struct Bluetooth {
    Region gcc,uart,wrapper,tlmm;
    IOService *radio;
    struct b5q_bt_fifo geni;
    struct qbt *core;
    uint64_t rx_sequence;
    uint32_t pending,rx_wake,power_request,started;
    unsigned log,baud;
    uint8_t address[6];
    bool resources,powered,gated,clocked,serial_irq,wake_irq,service,initializing,loopback;
    uint8_t loop_rx[16];unsigned loop_length;
} bt;
B5qBtH4Tap h4Tap;
constexpr unsigned kRx=79,kBtEnable=81,kSwCtrl=82;
constexpr uint32_t kUartDefault[]={0u,1u,3u,1u};
constexpr uint32_t kUartActive[]={4u,5u,7u,4u}; // b5q.dts 3162..3298, all 2mA
bool map(Region &r,uint64_t base,size_t bytes) {
    if(r.va)return true;
    IODeviceMemory *memory=IODeviceMemory::withRange(base,bytes);
    r.map=memory?memory->map(kIOMapAnywhere|kIOMapInhibitCache):nullptr;
    if(memory)memory->release();r.va=r.map?reinterpret_cast<volatile uint32_t *>(r.map->getVirtualAddress()):nullptr;
    return r.va!=nullptr;
}
void barrier(){__asm__ volatile("dsb sy" ::: "memory");}
uint64_t nowNs(void *){uint64_t ns;absolutetime_to_nanoseconds(mach_absolute_time(),&ns);return ns;}
uint64_t h4NowMs(void *){return nowNs(nullptr)/1000000ULL;}
void h4Line(void *,const char *text){printf("%s\n",text);}
const B5qBtH4Sink h4Sink={h4Line,h4NowMs};
void wake(void *){__atomic_store_n(&bt.pending,1u,__ATOMIC_RELEASE);thread_wakeup((event_t)&bt.pending);}
void waitUntil(void *,uint64_t deadline) {
    // qbt_boot's command waits must honour FIFO progress just like the main
    // executor. Once H4 bytes enter the FIFO, qbt's command queue is empty
    // even while CTS/watermarks still owe transmission and an RX tail.
    if(bt.uart.va && !bt.gated){
        const uint64_t fifo=b5q_bt_fifo_deadline(&bt.geni);
        if(fifo<deadline)deadline=fifo;
    }
    if(__atomic_exchange_n(&bt.pending,0u,__ATOMIC_ACQ_REL))return;
    if(deadline==UINT64_MAX)assert_wait((event_t)&bt.pending,THREAD_UNINT);
    else {uint64_t absolute;nanoseconds_to_absolutetime(deadline,&absolute);assert_wait_deadline((event_t)&bt.pending,THREAD_UNINT,absolute);}
    if(__atomic_exchange_n(&bt.pending,0u,__ATOMIC_ACQ_REL))clear_wait(current_thread(),THREAD_AWAKENED);
    else thread_block(THREAD_CONTINUE_NULL);
}
uint32_t urd(void *,uint32_t reg){return bt.uart.va[reg/4];}
void uwr(void *,uint32_t reg,uint32_t value){bt.uart.va[reg/4]=value;barrier();}
uint32_t grd(void *,uint32_t reg){return bt.gcc.va[reg/4];}
void gwr(void *,uint32_t reg,uint32_t value){bt.gcc.va[reg/4]=value;barrier();}
void delay(void *,unsigned us){IODelay(us);}
void fifoBarrier(void *){barrier();}
void irqMask(void *,bool masked) {
    if(bt.serial_irq)(void)armcpu_spi_mask(SM8550_UART14_INTID,masked);
}
void serialIrq(void *){b5q_bt_fifo_irq(&bt.geni);}
void pin(unsigned gpio,uint32_t cfg,int output=-1) {
    if(output>=0)bt.tlmm.va[(gpio*4096+4)/4]=output?2:0;
    bt.tlmm.va[gpio*4096/4]=cfg;barrier();
}
void rxIrq(void *) {
    volatile uint32_t *r=bt.tlmm.va+kRx*4096/4;
    if(!(r[3]&1))return;
    /* Raw status stays on after the wake is disarmed, so every UART start bit latches it again, and each pin of the
     * shared TLMM summary line calls this handler. Only the armed interrupt is a wake. */
    if(!(r[2]&1)){native_bluetooth_ibs[5]=native_bluetooth_ibs[5]+1;return;}
    r[2]=0;r[3]=0;barrier();
    native_bluetooth_ibs[7]=native_bluetooth_ibs[7]+1;
    __atomic_store_n(&bt.rx_wake,1u,__ATOMIC_RELEASE);wake(nullptr);
}
void disarmRxWake(){bt.tlmm.va[(kRx*4096+8)/4]=0;bt.tlmm.va[(kRx*4096+12)/4]=0;pin(kRx,kUartActive[3]);}
bool serialClock(bool enabled) {
    if(!sm8550_geni_uart14_vote(bt.gcc.va+0x52010/4,enabled))return false;
    if(!enabled){bt.clocked=false;return true;}
    for(unsigned i=0;i<1000;i++){if(!(grd(nullptr,0x1e754)&(1u<<31))){bt.clocked=true;return true;}IODelay(1);}
    return false;
}
size_t rxBytes(void *,const uint8_t *bytes,size_t n) {
    if(bt.loopback) {
        size_t count=sizeof(bt.loop_rx)-bt.loop_length;if(count>n)count=n;
        memcpy(bt.loop_rx+bt.loop_length,bytes,count);bt.loop_length+=(unsigned)count;
        return n;
    }
    if(bt.log>=2 && bt.initializing) {
        uint32_t at=__atomic_load_n(&native_bluetooth_boot_rx_length,__ATOMIC_RELAXED);
        size_t count=sizeof(native_bluetooth_boot_rx)-at;if(count>n)count=n;
        if(count) {
            memcpy(native_bluetooth_boot_rx+at,bytes,count);
            __atomic_store_n(&native_bluetooth_boot_rx_length,at+(uint32_t)count,__ATOMIC_RELEASE);
        }
        static char run[96];static unsigned runLength;
        for(size_t i=0;i<n;i++) {
            uint8_t c=bytes[i];
            if(c>=32 && c<127 && runLength<sizeof(run)-1){run[runLength++]=(char)c;continue;}
            if(runLength>=12 && memchr(run,' ',runLength)) {
                uint32_t at=native_bluetooth_boot_text_length;
                if(native_bluetooth_boot_text && at+runLength+1<8192) {
                    memcpy(native_bluetooth_boot_text+at,run,runLength);native_bluetooth_boot_text[at+runLength]='|';
                    __atomic_store_n(&native_bluetooth_boot_text_length,at+runLength+1,__ATOMIC_RELEASE);
                }
            }
            runLength=0;
        }
        uint32_t tail=__atomic_load_n(&native_bluetooth_boot_tail_length,__ATOMIC_RELAXED);
        for(size_t i=0;i<n;i++)native_bluetooth_boot_tail[(tail+i)%sizeof(native_bluetooth_boot_tail)]=bytes[i];
        __atomic_store_n(&native_bluetooth_boot_tail_length,tail+(uint32_t)n,__ATOMIC_RELEASE);
    }
    bt.rx_sequence+=n;return qbt_receive(bt.core,bytes,n);
}
size_t nativeRx(void *,const uint8_t *bytes,size_t n) {
    const uint32_t taken=qbt_transport_receive(bytes,(uint32_t)n);
    // Only the accepted prefix belongs to the RX H4 stream. The transport
    // retries the remainder after backpressure; feeding n here would
    // duplicate bytes and lose frame sync.
    if(bt.log>=2)b5q_bt_h4_tap_rx_taken(&h4Tap,bytes,n,taken);
    return taken;
}
size_t writeUart(void *,const uint8_t *p,size_t n){return b5q_bt_fifo_write(&bt.geni,p,n);}
bool drained(void *){return bt.gated || b5q_bt_fifo_drained(&bt.geni);}
int flow(void *,bool enabled){b5q_bt_fifo_set_flow(&bt.geni,enabled);return 0;}
void pump(void *) {
    if(bt.log>=2 && bt.initializing) {
        struct qbt_stats stats;qbt_get_stats(bt.core,&stats);
        native_bluetooth_stats[3]=stats.tx_bytes;native_bluetooth_stats[4]=stats.rx_bytes;
        native_bluetooth_boot_state[10]=(uint32_t)stats.tlv_acks|((uint32_t)stats.tlv_sent<<16);
        native_bluetooth_boot_state[11]=(uint32_t)stats.hardware_errors|((uint32_t)stats.last_hardware_error<<8)|((uint32_t)stats.tlv_final_status<<16);
    }
    if(__atomic_exchange_n(&bt.rx_wake,0u,__ATOMIC_ACQ_REL) && bt.powered) {
        qbt_rx_wake(bt.core);
        /* The GPIO consumed the first IBS wake byte while the UART was gated. It counts as received, so a clock stop
         * in progress (quiesce() pumps too) sees it and backs out. */
        const uint8_t wakeByte=0xfd;bt.rx_sequence++;(void)qbt_receive(bt.core,&wakeByte,1);
    }
    if(!bt.gated) {
        if(b5q_bt_fifo_service(&bt.geni))wake(nullptr);
        if(bt.geni.state==B5Q_BT_FIFO_FAILED)qbt_fail(bt.core,bt.geni.error);
    }
}
int quiesce() {
    uint64_t end=nowNs(nullptr)+40000000ULL;
    for(;;) {
        int e=b5q_bt_fifo_quiesce(&bt.geni);if(!e)return 0;
        if(e!=-EINPROGRESS && e!=-EBUSY)return e;
        pump(nullptr);if(bt.geni.state==B5Q_BT_FIFO_STOPPED)return 0;
        if(nowNs(nullptr)>=end)return -ETIMEDOUT;
        uint64_t next=b5q_bt_fifo_deadline(&bt.geni);if(next>end)next=end;waitUntil(nullptr,next);
    }
}
int clockVote(void *,bool enabled) {
    if(enabled) {
        if(!bt.gated)return 0;
        if(!serialClock(true))return -EIO;
        disarmRxWake();IODelay(10);bt.gated=false;
        return b5q_bt_fifo_resume(&bt.geni);
    }
    if(bt.gated)return 0;
    uint64_t sequence=bt.rx_sequence;
    int e=quiesce();if(e)return e;
    if(sequence!=bt.rx_sequence || qbt_transport_tx_pending()) {b5q_bt_fifo_resume(&bt.geni);return -EBUSY;}
    volatile uint32_t *r=bt.tlmm.va+kRx*4096/4;
    r[2]=0;r[3]=0;pin(kRx,3u);
    r[2]=(3u<<5)|(2u<<2)|(1u<<4)|(1u<<1)|1u;barrier();
    if(!(r[1]&1) || (r[3]&1)) {disarmRxWake();b5q_bt_fifo_resume(&bt.geni);return -EBUSY;}
    /* Leave RTS ready so the controller can send its IBS wake indication. */
    uwr(nullptr,0x2ac,0x80000001u);
    bt.gated=true;
    if(!serialClock(false)){bt.gated=false;disarmRxWake();b5q_bt_fifo_resume(&bt.geni);return -EIO;}
    return 0;
}
int setRate(void *,uint32_t baud) {
    int e=quiesce();if(e)return e;
    uint32_t hz=0;struct sm8550_geni_clock_io io={nullptr,grd,gwr,delay};
    e=sm8550_geni_uart14_source(&io,baud,&hz);
    if(!e)e=b5q_bt_fifo_set_rate(&bt.geni,baud,hz,16);
    if(!e)e=b5q_bt_fifo_resume(&bt.geni);
    if(!e)bt.baud=baud;return e;
}
void *allocate(void *,size_t n){return IOMallocData(n);}
void release(void *,void *p,size_t n){IOFreeData(p,n);}
int firmware(void *,const char *name,const uint8_t **data,size_t *size) {
    uint8_t *bytes=nullptr;int e=sheng_bt_firmware_read(name,&bytes,size);*data=bytes;return -e;
}
void firmwarePut(void *,const uint8_t *data,size_t size){sheng_bt_firmware_release(const_cast<uint8_t *>(data),size);}
void log(void *,int level,const char *line){if(level<=3 || bt.log)printf("[bluetooth] %s\n",line);}
bool address() {
    IORegistryEntry *chosen=IORegistryEntry::fromPath("/chosen",gIODTPlane);
    OSData *id=chosen?OSDynamicCast(OSData,chosen->getProperty("unique-chip-id")):nullptr;
    if(!id || id->getLength()<8){if(chosen)chosen->release();return false;}
    uint64_t hash=0xcbf29ce484222325ULL;
    static const char domain[]="unixnu-bluetooth";
    for(unsigned i=0;i<sizeof(domain)-1;i++)hash=(hash^(uint8_t)domain[i])*0x100000001b3ULL;
    const uint8_t *seed=static_cast<const uint8_t *>(id->getBytesNoCopy());
    bool nonzero=false;
    for(unsigned i=0;i<id->getLength();i++){nonzero|=seed[i]!=0;hash=(hash^seed[i])*0x100000001b3ULL;}
    bool published=false;
    if(nonzero) {
        for(unsigned i=0;i<6;i++)bt.address[i]=(uint8_t)(hash>>(i*8));
        bt.address[0]=(bt.address[0]&0xfe)|2;
        IORegistryEntry *node=IORegistryEntry::fromPath("/arm-io/bluetooth",gIODTPlane);
        OSData *encoding=node?OSDynamicCast(OSData,node->getProperty("transport-encoding")):nullptr;
        OSData *speed=node?OSDynamicCast(OSData,node->getProperty("transport-speed")):nullptr;
        uint32_t wire=0,baud=0;
        if(encoding && encoding->getLength()==4)memcpy(&wire,encoding->getBytesNoCopy(),4);
        if(speed && speed->getLength()==4)memcpy(&baud,speed->getBytesNoCopy(),4);
        if(node && wire==1 && baud==3200000) {
            published=chosen->setProperty("mac-address-bluetooth0",bt.address,6) &&
                node->setProperty("local-mac-address",bt.address,6);
            if(published && !bt.radio) {
                IOService *radio=new IOService;
                if(radio && radio->init()) {
                    radio->setName("bluetooth");
                    published=radio->setProperty("device_type","bluetooth") &&
                        radio->setProperty("transport-encoding",encoding) &&
                        radio->setProperty("transport-speed",speed) &&
                        radio->setProperty("local-mac-address",bt.address,6);
                    IOService *provider=IOService::getPlatform();
                    if(published && provider && radio->attach(provider)) {
                        bt.radio=radio;radio->registerService();
                    } else {published=false;radio->release();}
                } else {published=false;if(radio)radio->release();}
            }
        }
        if(node)node->release();
    }
    chosen->release();return published;

}
int resources() {
    if(bt.resources)return 0;
    if(!map(bt.gcc,0x100000,0x80000) || !map(bt.uart,SM8550_UART14_BASE,0x4000) ||
        !map(bt.wrapper,SM8550_QUP2_BASE,0x2000) || !map(bt.tlmm,0xf100000,0x100000))return -ENOMEM;
    if(!address())return -ENOENT;
    bt.resources=true;return 0;
}
int stopEngine() {
    irqMask(nullptr,true);uwr(nullptr,0xe1c,0);
    if(urd(nullptr,0x40)&0x1001) {
        uwr(nullptr,0x604,4);uwr(nullptr,0x634,4);
        unsigned i=0;for(;i<1000 && (urd(nullptr,0x40)&0x1001);i++)IODelay(1);
        if(i==1000) {
            uwr(nullptr,0x604,2);uwr(nullptr,0x634,2);
            for(i=0;i<1000 && (urd(nullptr,0x40)&0x1001);i++)IODelay(1);
            if(i==1000)return -ETIMEDOUT;
        }
    }
    uwr(nullptr,0x618,UINT32_MAX);uwr(nullptr,0x648,UINT32_MAX);
    bt.geni.state=B5Q_BT_FIFO_OFF;bt.geni.tx_busy=false;
    return 0;
}
uint32_t linePins() {
    static const uint8_t pins[]={76,77,78,79,kBtEnable,kSwCtrl};
    uint32_t bits=0;
    for(unsigned i=0;i<sizeof(pins);i++)bits|=(bt.tlmm.va[(pins[i]*4096u+4)/4]&1u)<<i;
    return bits;
}
int prepareEngine() {
    struct b5q_bt_fifo_ops ops={nullptr,urd,uwr,fifoBarrier,nowNs,irqMask,wake,rxBytes};
    const uint32_t disabled=urd(nullptr,0x64),revision=urd(nullptr,0x68);
    int e=b5q_bt_fifo_prepare(&bt.geni,&ops);
    IOLog("B5qBluetooth: transport=FIFO base=898000 intid=493 if-disable=%08x fw=%08x prepare=%d\n",disabled,revision,e);
    if(e)return e;
    native_bluetooth_stats[14]=5;
    uint32_t hz;struct sm8550_geni_clock_io clocks={nullptr,grd,gwr,delay};
    e=sm8550_geni_uart14_source(&clocks,115200,&hz);if(e)return e;
    e=b5q_bt_fifo_set_rate(&bt.geni,115200,hz,16);if(e)return e;
    bt.baud=115200;return 0;
}
/* log-bluetooth=2, controller still in reset: GENI's internal loopback checks FIFO
 * packing without the controller. Stats[30] holds received
 * length, bit 16 sent, bit 17 match; stats[31] the first received bytes. */
int loopbackCheck() {
    static const uint8_t pattern[16]={0x01,0x55,0xaa,0x00,0xff,0x04,0x0e,0x7e,0x81,0x42,0x24,0x18,0x10,0x20,0x40,0x80};
    uwr(nullptr,0x22c,3);bt.loopback=true;bt.loop_length=0;
    int e=b5q_bt_fifo_start(&bt.geni);
    size_t sent=e?0:b5q_bt_fifo_write(&bt.geni,pattern,sizeof(pattern));
    uint64_t end=nowNs(nullptr)+50000000ULL;
    while(sent && bt.loop_length<sizeof(pattern) && bt.geni.state==B5Q_BT_FIFO_RUN && nowNs(nullptr)<end) {
        if(!b5q_bt_fifo_service(&bt.geni))IOSleep(1);
    }
    uint64_t first=0;memcpy(&first,bt.loop_rx,bt.loop_length<8?bt.loop_length:8);
    native_bluetooth_stats[31]=first;
    native_bluetooth_stats[30]=bt.loop_length|(sent?1u<<16:0)|(bt.loop_length==sizeof(pattern) && !memcmp(bt.loop_rx,pattern,sizeof(pattern))?1u<<17:0);
    /* Stopping exercises the same cancel path as a baud change. */
    e=bt.geni.state==B5Q_BT_FIFO_RUN?quiesce():-EIO;
    bt.loopback=false;uwr(nullptr,0x22c,0);
    if(!e && bt.geni.state==B5Q_BT_FIFO_STOPPED)return 0;
    e=stopEngine();if(e)return e;
    return prepareEngine();
}
int powerOn() {
    if(bt.powered)return 0;
    b5q_bt_h4_tap_reset_session(&h4Tap);
    int wait=b5q_wcn_wait_wifi_probe();if(wait)return -wait;
    native_bluetooth_stats[14]=1;int e=resources();if(e)return e;
    native_bluetooth_stats[14]=2;
    e=b5q_wcn_power_get(B5Q_WCN_BLUETOOTH);if(e)return -e;
    bt.powered=true;bt.gated=true;
    native_bluetooth_stats[14]=3;
    /* The controller leaves reset with RTS low: UART function only after it has settled. */
    for(unsigned gpio=76;gpio<=79;gpio++)pin(gpio,kUartDefault[gpio-76]);
    pin(kSwCtrl,0u);e=b5q_wcn_radio_enable(B5Q_WCN_BLUETOOTH,0);if(e)return -e;
    if(!sm8550_gcc_update32(bt.gcc.va+0x52018/4,0,1u))return -EIO;
    for(unsigned i=0;i<1000 && !(grd(nullptr,0)&(1u<<31));i++)IODelay(1);
    if(!(grd(nullptr,0)&(1u<<31)) || !serialClock(true))return -EIO;
    bt.gated=false;
    native_bluetooth_stats[11]=urd(nullptr,0x68);native_bluetooth_stats[12]=bt.wrapper.va[1];
    native_bluetooth_stats[13]=grd(nullptr,0x52010);native_bluetooth_stats[14]=4;
    if(bt.wrapper.va[1]<0x20050000)return -ENOTSUP;
    if(((urd(nullptr,0x68)>>8)&255)!=2)return -ENXIO;
    e=stopEngine();if(e)return e;
    e=prepareEngine();if(e)return e;
    if(!bt.serial_irq){e=armcpu_spi_attach(SM8550_UART14_INTID,false,serialIrq,nullptr,nullptr,nullptr);if(e)return -EIO;bt.serial_irq=true;irqMask(nullptr,true);}
    if(!bt.wake_irq){e=armcpu_spi_share(240,rxIrq,nullptr);if(e)return -EIO;bt.wake_irq=true;}
    if(bt.log>=2){e=loopbackCheck();if(e)return e;}
    e=b5q_wcn_radio_enable(B5Q_WCN_BLUETOOTH,1);if(e)return -e;
    // radio_enable already includes the stock 50ms post-BT_EN delay.
    // Keep UART detached for a further bounded guard after the shared vote.
    IOLog("B5qBluetooth: stage=reset-settle wait-ms=50 pins=%x\n",linePins());
    IOSleep(50);
    for(unsigned gpio=76;gpio<=79;gpio++)pin(gpio,kUartActive[gpio-76]);
    disarmRxWake();
    e=b5q_bt_fifo_startup(&bt.geni);if(e)return e;
    // Allow one reset/mux transient before any HCI command is transmitted.
    for(unsigned i=0;i<20;i++){pump(nullptr);if(bt.geni.state==B5Q_BT_FIFO_FAILED)return bt.geni.error;IOSleep(1);}
    IOLog("B5qBluetooth: stage=rx-settled pins=%x ios=%x startup-line=%llu discarded=%llu irq=%x/%x\n",
        linePins(),urd(nullptr,0x908),bt.geni.stats.startup_line_errors,
        bt.geni.stats.startup_rx_discarded,bt.geni.fault_irq[0],bt.geni.fault_irq[1]);
    native_bluetooth_stats[14]=6;
    bt.initializing=true;
    if(bt.log>=2) {
        /* Bytes seen here precede the first command: controller output, not a reply. */
        for(unsigned i=0;i<20;i++){pump(nullptr);IOSleep(1);}
        native_bluetooth_boot_state[0]=linePins();
        native_bluetooth_boot_state[1]=__atomic_load_n(&native_bluetooth_boot_rx_length,__ATOMIC_ACQUIRE);
    }
    e=qbt_boot(bt.core,3200000,bt.address);bt.initializing=false;
    if(e){
        struct qbt_stats stats;qbt_get_stats(bt.core,&stats);
        IOLog("B5qBluetooth: stage=boot-failed result=%d baud=%u pins=%x tlv=%llu/%llu status=%llx tx=%llu rx=%llu fifo=%u/%u busy=%u irq=%x/%x hw=%x txfifo=%x rxfifo=%x ios=%x rfr=%x\n",
            e,bt.geni.baud,linePins(),stats.tlv_acks,stats.tlv_sent,stats.tlv_final_status,
            bt.geni.stats.tx_bytes,bt.geni.stats.rx_bytes,bt.geni.tx_offset,bt.geni.tx_length,bt.geni.tx_busy,
            urd(nullptr,0x610),urd(nullptr,0x640),urd(nullptr,0x40),urd(nullptr,0x800),urd(nullptr,0x804),urd(nullptr,0x908),urd(nullptr,0x2ac));
    }
    if(bt.log>=2) {
        static const uint32_t regs[]={0x40,0x610,0x640,0x800,0x804,0x64,0x908};
        native_bluetooth_boot_state[2]=linePins();
        for(unsigned i=0;i<7;i++)native_bluetooth_boot_state[3+i]=bt.clocked?urd(nullptr,regs[i]):0;
        struct qbt_stats stats;qbt_get_stats(bt.core,&stats);
        native_bluetooth_boot_state[10]=(uint32_t)stats.tlv_acks|((uint32_t)stats.tlv_sent<<16);
        native_bluetooth_boot_state[11]=(uint32_t)stats.hardware_errors|((uint32_t)stats.last_hardware_error<<8)|((uint32_t)stats.tlv_final_status<<16);
    }
    return e;
}
int powerOff() {
    if(!bt.powered)return 0;
    b5q_bt_h4_tap_reset_streams(&h4Tap);
    qbt_set_service(bt.core,false);bt.service=false;
    int e=0;
    if(bt.geni.state!=B5Q_BT_FIFO_OFF) {
        if(bt.gated){int resumed=clockVote(nullptr,true);if(!e)e=resumed;}
        if(bt.clocked){int shutdown=qbt_shutdown(bt.core);if(!e)e=shutdown;}
    }
    if(bt.clocked && bt.geni.state!=B5Q_BT_FIFO_OFF){int stopped=quiesce();if(!e)e=stopped;}
    irqMask(nullptr,true);disarmRxWake();
    int reset=b5q_wcn_radio_enable(B5Q_WCN_BLUETOOTH,0);if(!e)e=-reset;
    int retired=bt.clocked?stopEngine():0;if(!e)e=retired;
    if(!retired)bt.gated=serialClock(false);
    for(unsigned i=0;i<4;i++)pin(76+i,kUartDefault[i]);
    bt.powered=false;__atomic_store_n(&bt.rx_wake,0u,__ATOMIC_RELEASE);
    int released=b5q_wcn_power_put(B5Q_WCN_BLUETOOTH);if(!e)e=-released;
    return e;
}
int requestPower(void *,bool enabled) {
    uint32_t expected=0;
    if(!__atomic_compare_exchange_n(&bt.power_request,&expected,enabled?1u:2u,false,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))return EBUSY;
    wake(nullptr);return 0;
}
void powerResult(bool enabled,int error) {
    struct qbt_info info;qbt_get_info(bt.core,&info);
    native_bluetooth_stats[17]=info.product;native_bluetooth_stats[18]=info.soc;
    native_bluetooth_stats[19]=((uint32_t)info.rom<<16)|info.patch;
    if(enabled && !error)native_bluetooth_stats[14]=7;
    qbt_transport_power_result(enabled,error<0?-error:error,info.firmware,info.baud);
    native_bluetooth_stats[20]=(unsigned)bt.powered|((unsigned)bt.gated<<1)|((unsigned)bt.clocked<<2);
    native_bluetooth_stats[21]=b5q_wcn_power_owners();
    native_bluetooth_stats[0]=error?3:enabled?2:0;native_bluetooth_stats[1]=(uint64_t)(int64_t)error;
    printf("B5qBluetooth: power=%u result=%d baud=%u product=%08x rom=%04x transport=FIFO\n",enabled,error,info.baud,info.product,info.rom);
    if(error && bt.geni.error)printf("[bluetooth uart] error=%d irq=%x/%x\n",bt.geni.error,bt.geni.fault_irq[0],bt.geni.fault_irq[1]);
}
void worker(void *,wait_result_t) {
    thread_set_thread_name(current_thread(),"bluetooth");
    struct qbt_platform ops={nullptr,allocate,release,nowNs,writeUart,drained,setRate,flow,clockVote,pump,waitUntil,nativeRx,firmware,firmwarePut,log,nullptr};
    if (bt.log >= 3) {
        struct bt_hci_trace *trace = static_cast<struct bt_hci_trace *>(IOMallocZeroData(sizeof(*trace)));
        __atomic_store_n(&hci_trace, trace, __ATOMIC_RELEASE);
        if (trace) ops.trace_hci = traceHci;
        else printf("[bluetooth hci] allocation failed\n");
    }
    bt.core=qbt_create(&ops);if(!bt.core){native_bluetooth_stats[0]=3;IOLog("B5qBluetooth: stage=core-create result=%d\n",-ENOMEM);thread_terminate(current_thread());return;}
    struct qbt_transport_ops transport={nullptr,wake,requestPower};
    int e=qbt_transport_init(&transport);if(e){native_bluetooth_stats[0]=3;IOLog("B5qBluetooth: stage=transport-init result=%d\n",e);thread_terminate(current_thread());return;}
    while(native_gpu_addon_stage<1)waitUntil(nullptr,nowNs(nullptr)+10000000ULL);
    /* Wi-Fi settles WLAN_EN and the shared supplies first; its failure stage is negative. */
    unsigned wifi=0;PE_parse_boot_argn("wifi",&wifi,sizeof(wifi));
    if(wifi) {
        uint64_t end=nowNs(nullptr)+15000000000ULL;
        while(nowNs(nullptr)<end) {
            int32_t stage=(int32_t)native_wifi_stats[0];
            if(stage<0 || stage>=17)break;
            waitUntil(nullptr,nowNs(nullptr)+10000000ULL);
        }
    }
    e=powerOn();if(e)(void)powerOff();powerResult(true,e);
    uint64_t health=nowNs(nullptr)+1000000000ULL,closeAt=0;
    for(;;) {
        uint32_t command=__atomic_exchange_n(&bt.power_request,0u,__ATOMIC_ACQ_REL);
        if(command){e=command==1?powerOn():powerOff();if(e && command==1)(void)powerOff();powerResult(command==1,e);}
        if(bt.powered) {
            pump(nullptr);bool active=qbt_transport_active();
            if(active!=bt.service){
                if(active&&bt.log>=2)b5q_bt_h4_tap_reset_streams(&h4Tap);
                qbt_set_service(bt.core,active);bt.service=active;closeAt=active?0:nowNs(nullptr)+500000000ULL;
            }
            uint8_t tx[2048];size_t room=qbt_transmit_capacity(bt.core);
            if(room>sizeof(tx))room=sizeof(tx);
            if(room){uint32_t n=qbt_transport_tx_take(tx,(uint32_t)room);if(n){
                int sent=qbt_transmit(bt.core,tx,n);
                if(sent){e=sent<0?sent:-EIO;qbt_fail(bt.core,e);IOLog("B5qBluetooth: stage=transmit result=%d bytes=%u\n",e,n);}
                else if(bt.log>=2)b5q_bt_h4_tap_tx(&h4Tap,tx,n);
            }}
            qbt_step(bt.core);
            struct qbt_info info;qbt_get_info(bt.core,&info);
            if(info.state==3 || bt.geni.state==B5Q_BT_FIFO_FAILED || (closeAt && nowNs(nullptr)>=closeAt)) {
                int error=info.state==3?info.error:bt.geni.error;
                (void)powerOff();powerResult(false,error);closeAt=0;
            }
        }
        uint64_t t=nowNs(nullptr);
        if(t>=health) {
            struct qbt_stats stats;qbt_get_stats(bt.core,&stats);
            native_bluetooth_stats[2]=bt.baud;native_bluetooth_stats[3]=stats.tx_bytes;native_bluetooth_stats[4]=stats.rx_bytes;
            native_bluetooth_stats[5]=bt.geni.stats.interrupts;native_bluetooth_stats[6]=stats.timeouts;native_bluetooth_stats[7]=stats.clock_sleeps;
            native_bluetooth_stats[8]=bt.geni.tx_depth;native_bluetooth_stats[9]=bt.geni.rx_depth;
            native_bluetooth_stats[20]=(unsigned)bt.powered|((unsigned)bt.gated<<1)|((unsigned)bt.clocked<<2);
            native_bluetooth_stats[21]=b5q_wcn_power_owners();
            for(unsigned i=0;i<2;i++)native_bluetooth_stats[22+i]=bt.geni.fault_irq[i];
            native_bluetooth_stats[26]=stats.malformed;native_bluetooth_stats[27]=stats.unmatched_events;
            native_bluetooth_stats[28]=bt.geni.stats.rx_words;native_bluetooth_stats[29]=bt.geni.stats.tx_words;
            native_bluetooth_stats[15]=bt.geni.stats.line_errors;native_bluetooth_stats[16]=0;
            native_bluetooth_ibs[0]=stats.wake_ind;native_bluetooth_ibs[1]=stats.wake_ack;native_bluetooth_ibs[2]=stats.sleep_ind;
            native_bluetooth_ibs[3]=stats.clock_reverts;native_bluetooth_ibs[4]=stats.tx_refused;
            native_bluetooth_ibs[6]=bt.geni.stats.cancel_timeouts;
            static_assert(QBT_DISCOVERY_COMMANDS == 5, "Update the discovery log ABI");
            for (unsigned i=0;i<QBT_DISCOVERY_COMMANDS;i++) {
                native_bluetooth_discovery[i*3]=stats.discovery.sent[i];
                native_bluetooth_discovery[i*3+1]=stats.discovery.replied[i];
                native_bluetooth_discovery[i*3+2]=stats.discovery.status[i];
            }
            native_bluetooth_discovery[15]=stats.discovery.inquiry_results;
            native_bluetooth_discovery[16]=stats.discovery.le_reports;
            native_bluetooth_discovery[17]=stats.discovery.le_extended_reports;
            if(bt.log>=2) {
                static uint64_t nextLog=0;
                if(t>=nextLog) {
                    nextLog=t+5000000000ULL;
                    printf("B5qBluetooth: stage=health powered=%u active=%u gated=%u irq=%llu SE_IRQ_EN=%x tty-power=%u boot-read=%u open=%u speed-requests=%u discovery=%u/%u/%u rx=%llu\n",
                        bt.powered,bt.service,bt.gated,bt.geni.stats.interrupts,
                        bt.clocked?urd(nullptr,0xe1c):0,
                        __atomic_load_n(&qbt_transport_activity[0],__ATOMIC_RELAXED),
                        __atomic_load_n(&qbt_transport_activity[1],__ATOMIC_RELAXED),
                        __atomic_load_n(&qbt_transport_activity[2],__ATOMIC_RELAXED),
                        __atomic_load_n(&qbt_transport_activity[3],__ATOMIC_RELAXED),
                        stats.discovery.inquiry_results,stats.discovery.le_reports,stats.discovery.le_extended_reports,stats.rx_bytes);
                    printf("B5qBluetooth: stage=ibs wake-ind=%llu wake-ack=%llu sleep-ind=%llu clock-reverts=%llu tx-refused=%llu rx-irq=%llu cancel-timeouts=%llu wake-irq=%llu\n",
                        native_bluetooth_ibs[0],native_bluetooth_ibs[1],native_bluetooth_ibs[2],native_bluetooth_ibs[3],
                        native_bluetooth_ibs[4],native_bluetooth_ibs[5],native_bluetooth_ibs[6],native_bluetooth_ibs[7]);
                    printf("B5qBluetooth: stage=discovery inquiry=%u/%u/%u le-param=%u/%u/%u le-enable=%u/%u/%u ext-param=%u/%u/%u ext-enable=%u/%u/%u reports=%u/%u/%u\n",
                        stats.discovery.sent[QBT_INQUIRY],stats.discovery.replied[QBT_INQUIRY],stats.discovery.status[QBT_INQUIRY],
                        stats.discovery.sent[QBT_LE_SCAN_PARAMS],stats.discovery.replied[QBT_LE_SCAN_PARAMS],stats.discovery.status[QBT_LE_SCAN_PARAMS],
                        stats.discovery.sent[QBT_LE_SCAN_ENABLE],stats.discovery.replied[QBT_LE_SCAN_ENABLE],stats.discovery.status[QBT_LE_SCAN_ENABLE],
                        stats.discovery.sent[QBT_LE_EXT_SCAN_PARAMS],stats.discovery.replied[QBT_LE_EXT_SCAN_PARAMS],stats.discovery.status[QBT_LE_EXT_SCAN_PARAMS],
                        stats.discovery.sent[QBT_LE_EXT_SCAN_ENABLE],stats.discovery.replied[QBT_LE_EXT_SCAN_ENABLE],stats.discovery.status[QBT_LE_EXT_SCAN_ENABLE],
                        stats.discovery.inquiry_results,stats.discovery.le_reports,stats.discovery.le_extended_reports);
                    printf("B5qBluetooth: stage=transport tx=%llu rx=%llu delivered=%llu malformed=%llu unmatched=%llu backpressure=%llu fifo-backpressure=%llu hardware-errors=%llu last-hardware=%llu tty-rx-dropped=%llu\n",
                        stats.tx_bytes,stats.rx_bytes,stats.delivered_bytes,stats.malformed,stats.unmatched_events,
                        stats.backpressure,bt.geni.stats.rx_backpressure,stats.hardware_errors,stats.last_hardware_error,
                        qbt_transport_rx_dropped());
                    printf("B5qBluetooth: stage=h4 tx-cmd=%llu tx-acl=%llu rx-evt=%llu rx-acl=%llu errs=%llu smp=%llu l2cap=%llu desync=%llu evt13=%llu logged=%u/%u\n",
                        h4Tap.stats.tx_cmd,h4Tap.stats.tx_acl,h4Tap.stats.rx_evt,h4Tap.stats.rx_acl,
                        h4Tap.stats.errs,h4Tap.stats.smp,h4Tap.stats.l2cap,h4Tap.stats.desync,h4Tap.stats.evt13,
                        h4Tap.stats.logged,B5Q_BT_H4_QUOTA_TOTAL);
                }
            }
            health=t+1000000000ULL;
        }
        uint64_t deadline=bt.powered?qbt_deadline(bt.core):UINT64_MAX;
        uint64_t geni=bt.powered && !bt.gated?b5q_bt_fifo_deadline(&bt.geni):UINT64_MAX;
        if(geni<deadline)deadline=geni;if(health<deadline)deadline=health;if(closeAt && closeAt<deadline)deadline=closeAt;
        if(!deadline){thread_yield_to_preemption();continue;}
        waitUntil(nullptr,deadline);
    }
}
}
extern "C" size_t b5q_bluetooth_hci_dump(char *out, size_t capacity, uint64_t *cursor) {
    return bt_hci_dump(__atomic_load_n(&hci_trace, __ATOMIC_ACQUIRE), out, capacity, cursor);
}
struct proc;
extern "C" {
void proc_iterate(unsigned,int (*)(struct proc *,void *),void *,int (*)(struct proc *,void *),void *);
int proc_pid(struct proc *);
}
int processSeen(struct proc *process,void *found) {
    static const char *const names[]={"bluetoothd","BlueTool","BluetoothUIServer"};
    const char *name=proc_best_name(process);
    for(unsigned i=0;name && i<3;i++) {
        const bool match=i==2?!strncmp(name,"BluetoothUIServe",16):!strcmp(name,names[i]);
        if(match)static_cast<int *>(found)[i]=proc_pid(process);
    }
    return 0;
}
void processWatch(void *,wait_result_t) {
    thread_set_thread_name(current_thread(),"b5q-bluetooth-procs");
    static uint32_t uiPid,uiChanges;
    for(;;) {
        int found[3]={0,0,0};
        proc_iterate(1u|4u,processSeen,found,nullptr,nullptr);
        for(unsigned i=0;i<3;i++) {
            // native_bluetooth_processes[4] keeps its ABI and the first two
            // entries keep their bluetoothd/BlueTool meaning exactly.
            if(i<2) {
                if(found[i] && (uint32_t)found[i]!=native_bluetooth_processes[i*2])native_bluetooth_processes[i*2+1]=native_bluetooth_processes[i*2+1]+1;
                native_bluetooth_processes[i*2]=(uint32_t)found[i];
            } else if((uint32_t)found[i]!=uiPid) {
                uiChanges++;
                IOLog("B5qBluetooth: process name=BluetoothUIServer pid=%u change=%u\n",(uint32_t)found[i],uiChanges);
                uiPid=(uint32_t)found[i];
            }
        }
        IOSleep(2000);
    }
}
extern "C" void b5q_bluetooth_probe(void) {
    unsigned enabled=0;
    if(!PE_parse_boot_argn("bluetooth",&enabled,sizeof(enabled)) || !enabled)return;
    uint32_t expected=0;if(!__atomic_compare_exchange_n(&bt.started,&expected,1u,false,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))return;
    native_bluetooth_stats[0]=1;
    if(!address()){native_bluetooth_stats[0]=3;native_bluetooth_stats[1]=(uint64_t)(int64_t)-ENOENT;IOLog("B5qBluetooth: stage=address failed requires=/arm-io/bluetooth encoding=1 speed=3200000 identity=nonzero\n");return;}
    PE_parse_boot_argn("log-bluetooth",&bt.log,sizeof(bt.log));
    b5q_bt_h4_tap_init(&h4Tap,&h4Sink,nullptr,bt.log>=2);
    if(bt.log>=2)native_bluetooth_boot_text=static_cast<char *>(IOMallocData(8192));
    thread_t thread=nullptr;
    if(kernel_thread_start(worker,nullptr,&thread)==KERN_SUCCESS)thread_deallocate(thread);
    else {native_bluetooth_stats[0]=3;IOLog("B5qBluetooth: stage=worker-start failed\n");}
    if(bt.log>=2){const kern_return_t rc=kernel_thread_start(processWatch,nullptr,&thread);
        if(rc==KERN_SUCCESS)thread_deallocate(thread);else IOLog("B5qBluetooth: stage=process-watch result=%d\n",rc);}
}
