// SPDX-License-Identifier: BSD-2-Clause-Patent
// Samsung b5q S3916A: TouchComm V1 over GPIO44/45 open-drain I2C.
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceMemory.h>
#include <kern/thread.h>
#include <pexpert/pexpert.h>
#include "B5qTouchBus.h"
#include "B5qTouchReports.h"
#include "B5qTouchIrq.h"
#include "B5qTouchPower.h"
extern "C" {
wait_result_t clear_wait(thread_t,wait_result_t);
int armcpu_spi_share(uint32_t,void (*)(void *),void *);
volatile uint32_t native_touch_seq,native_touch_count,native_touch_hid_reports;
volatile int native_touch_xs[12],native_touch_ys[12],native_touch_ids[12];
}
extern "C" { __attribute__((visibility("default"))) volatile uint32_t native_touch_recovered; }
namespace {
IOMemoryMap *tlmmMapping;volatile uint32_t *tlmm;B5qTouch::Reports reports;
void (*sink)(void *);void *sinkContext;uint8_t message[4096],config[512];size_t configBytes;unsigned frames,maxObjects;
volatile uint32_t *mapTlmm(){
 auto *memory=IODeviceMemory::withRange(0xf100000,0x100000);
 tlmmMapping=memory?memory->map(kIOMapAnywhere|kIOMapInhibitCache):nullptr;
 OSSafeReleaseNULL(memory);
 return tlmmMapping?reinterpret_cast<volatile uint32_t *>(tlmmMapping->getVirtualAddress()):nullptr;
}
void barrier(){__asm__ volatile("dsb sy":::"memory");}
uint32_t tlmmRead(unsigned off){return tlmm[off/4];}
void tlmmWrite(unsigned off,uint32_t value){tlmm[off/4]=value;barrier();}
struct TlmmPins {
 void configure(unsigned pin){
  const unsigned ctl=pin*0x1000;
  tlmmWrite(ctl,tlmmRead(ctl)&~0x3ffu); // GPIO input, external pullup, 2mA.
 }
 void low(unsigned pin,bool drive){
  const unsigned ctl=pin*0x1000;
  if(drive)tlmmWrite(ctl+4,tlmmRead(ctl+4)&~2u);
  const uint32_t config=tlmmRead(ctl)&~(1u<<9);
  tlmmWrite(ctl,config|(drive?(1u<<9):0));
 }
 bool high(unsigned pin){return tlmmRead(pin*0x1000+4)&1u;}
 void delay(unsigned us){IODelay(us);}
};
using TouchBus=B5qTouchBus::Bus<TlmmPins>;
uint32_t irqEvents=0;
bool irqOnline=false, irqAttached=false;
void touchIrq(void *) {
 if(!__atomic_load_n(&irqOnline,__ATOMIC_ACQUIRE) || !B5qTouchIrq::acknowledge(tlmmRead,tlmmWrite))return;
 __atomic_fetch_add(&irqEvents,1u,__ATOMIC_RELEASE);
 thread_wakeup((event_t)&irqEvents);
}
bool lowAttention(){return !(tlmmRead(B5qTouchIrq::gpio*0x1000+4)&1u);}
void waitAttention(){
 const uint32_t seen=__atomic_load_n(&irqEvents,__ATOMIC_ACQUIRE);
 assert_wait((event_t)&irqEvents,THREAD_UNINT);
 if(lowAttention() || seen!=__atomic_load_n(&irqEvents,__ATOMIC_ACQUIRE))clear_wait(current_thread(),THREAD_AWAKENED);
 else thread_block(THREAD_CONTINUE_NULL);
}
bool powerTouch(){
 TlmmPins pins;
 pins.configure(B5qTouchPower::sda);
 pins.configure(B5qTouchPower::scl);
 B5qTouchPower::Bus<TlmmPins> bus(pins);
 uint8_t before=0,after=0;
 const bool ok=B5qTouchPower::enable(bus,before,after);
 IOLog("B5qTouch: s2dos05 enable=%02x->%02x verified=%u\n",before,after,ok);
 if(ok)IOSleep(100);
 return ok;
}
bool packet(TouchBus &bus,uint8_t &code,unsigned &length){
 uint8_t h[4];if(!bus.read(h,4))return false;code=h[1];length=unsigned(h[2])|(unsigned(h[3])<<8);
 if(h[0]!=0xa5||length>4096){IOLog("B5qTouch: stage=header hdr=%02x/%02x/%02x/%02x\n",h[0],h[1],h[2],h[3]);return false;}
 if(length)IODelay(100);
 return B5qTouch::continuation([&bus](uint8_t *p,unsigned n){return bus.read(p,n);},message,length);
}
void publish(bool fromReport=true){
 __atomic_fetch_add(&native_touch_seq,1u,__ATOMIC_RELEASE);
 __asm__ volatile("dmb ish" ::: "memory");unsigned count=0;
 native_touch_recovered=!fromReport;
 for(unsigned i=0;i<12;++i)if(reports.points[i].kind==1||reports.points[i].kind==2){native_touch_xs[count]=int(B5qTouch::hid(reports.points[i].x));native_touch_ys[count]=int(B5qTouch::hid(reports.points[i].y));native_touch_ids[count]=int(i);++count;}
 native_touch_count=count;__asm__ volatile("dmb ish":::"memory");__atomic_fetch_add(&native_touch_seq,1u,__ATOMIC_RELEASE);
 if(auto callback=__atomic_load_n(&sink,__ATOMIC_ACQUIRE))callback(sinkContext);
 if(fromReport){
  if(++frames<=8||!(frames%256))IOLog("B5qTouch: mode=%02x frames=%u contacts=%u palm=%u c2=%u release_all=%u hid=%u\n",reports.mode,frames,count,reports.palm,reports.c2,reports.releases,native_touch_hid_reports);
 }else if(reports.releases<=8 || !(reports.releases&(reports.releases-1)))
  IOLog("B5qTouch: stage=release-all mode=%02x contacts=0 palm=%u c2=%u identify=%u errors=%u release_all=%u hid=%u\n",reports.mode,reports.palm,reports.c2,reports.identify,reports.errors,reports.releases,native_touch_hid_reports);
}
unsigned layoutFailures;
void report(uint8_t code,unsigned n){
 static unsigned sampled=0;
 if((code==0x11 || code==0xc1) && sampled++<5){
  char hex[97]={};const unsigned count=n<32?n:32;
  for(unsigned i=0;i<count;++i)snprintf(hex+3*i,sizeof(hex)-3*i,"%02x ",message[i]);
  IOLog("B5qTouch: raw code=%02x bytes=%u first=%s\n",code,n,hex);
 }
 const auto result=reports.consume(code,message,n,config,configBytes,maxObjects);
 if(result==B5qTouch::ReportResult::Frame){layoutFailures=0;publish();}
 else if(result==B5qTouch::ReportResult::Released){
  publish(false);
  if(code==0x11 && ++layoutFailures<=3)
   IOLog("B5qTouch: stage=touch-layout code=%02x bytes=%u config=%lu failures=%u\n",code,n,(unsigned long)configBytes,layoutFailures);
 }
}
bool command(TouchBus &bus,uint8_t cmd,const uint8_t *p,unsigned n,bool getConfig=false){
 if(n>16)return false;
 uint8_t bytes[19]={cmd,uint8_t(n),uint8_t(n>>8)};
 if(n)memcpy(bytes+3,p,n);
 if(!bus.write(bytes,n+3)){
  IOLog("B5qTouch: command=%02x failed=write error=%s stop=%s\n",cmd,B5qTouchBus::name(bus.error()),B5qTouchBus::name(bus.stopError()));
  return false;
 }
 for(unsigned i=0;i<200;++i){
  if(!lowAttention()){IOSleep(5);continue;}
  uint8_t code=0;unsigned length=0;
  if(!packet(bus,code,length)){
   IOLog("B5qTouch: command=%02x failed=packet error=%s stop=%s\n",cmd,B5qTouchBus::name(bus.error()),B5qTouchBus::name(bus.stopError()));
   return false;
  }
  if(code==1){if(cmd==2){const bool ok=length>1&&message[1]==1;IOLog("B5qTouch: stage=identify mode=%u bytes=%u response=01 ok=%u\n",length>1?message[1]:255,length,ok);return ok;}if(cmd==0x20&&!B5qTouch::appInfo(message,length,maxObjects)){IOLog("B5qTouch: command=%02x failed=application-info bytes=%u\n",cmd,length);return false;}if(getConfig){if(length>sizeof(config)||!length){IOLog("B5qTouch: command=%02x failed=config-length bytes=%u\n",cmd,length);return false;}memcpy(config,message,length);configBytes=length;}return true;}
  if(code==0x10&&cmd==2){IOLog("B5qTouch: stage=identify mode=%u bytes=%u\n",length>1?message[1]:255,length);continue;}
  report(code,length);
  if(code==0x10 || (code<0x10&&code!=0&&code!=7)){
   IOLog("B5qTouch: command=%02x failed=response code=%02x bytes=%u\n",cmd,code,length);return false;
  }
 }
 IOLog("B5qTouch: command=%02x failed=response-timeout gpio19=%u\n",cmd,!lowAttention());
 return false;
}
bool configureReports(TouchBus &bus,bool preferFull=true){
 reports.mode=0;reports.reconfigure=false;configBytes=0;layoutFailures=0;
 if(!command(bus,0x20,nullptr,0))return false;
 const bool got=command(bus,0x25,nullptr,0,true);
 const uint8_t full=0x11,delta=0xc1;
 bool ok11=false,okC1=false;
 if(preferFull&&got)ok11=command(bus,5,&full,1);
 if(ok11){command(bus,6,&delta,1);reports.mode=full;}
 else {command(bus,6,&full,1);okC1=command(bus,5,&delta,1);if(okC1)reports.mode=delta;}
 IOLog("B5qTouch: stage=enable-report mode=%02x full_config=%lu ok11=%u okC1=%u\n",reports.mode,(unsigned long)configBytes,ok11,okC1);
 return reports.mode!=0;
}
void worker(void *,wait_result_t){
 const char *stage="mapping";
 TlmmPins pins;
 TouchBus bus(pins);
 do {
  tlmm=mapTlmm();if(!tlmm)break;
  stage="touch-power";if(!powerTouch())break;
  stage="gpio-bus";
  const unsigned attentionCtl=B5qTouchIrq::gpio*0x1000;
  tlmmWrite(attentionCtl,tlmmRead(attentionCtl)&~(1u<<9)); // ATTN input, preserve pulls.
  // b5q pinctrl uses 2mA and bias-disable for both touch bus pins.
  pins.configure(B5qTouchBus::sda);
  pins.configure(B5qTouchBus::scl);
  pins.delay(2);
  const unsigned initialSda=pins.high(B5qTouchBus::sda);
  const unsigned initialScl=pins.high(B5qTouchBus::scl);
  IOLog("B5qTouch: stage=%s phase=before gpio_sda=%u gpio_scl=%u sda_level=%u scl_level=%u address=%02x\n",
        stage,B5qTouchBus::sda,B5qTouchBus::scl,initialSda,initialScl,B5qTouchBus::address);
  const bool busReady=bus.prepare();
  IOLog("B5qTouch: stage=%s phase=after ok=%u error=%s\n",stage,busReady,B5qTouchBus::name(bus.error()));
  if(!busReady)break;
  stage="identify";IOLog("B5qTouch: stage=%s phase=before\n",stage);
  const bool identified=command(bus,2,nullptr,0);IOLog("B5qTouch: stage=%s phase=after ok=%u\n",stage,identified);if(!identified)break;
  stage="enable-report";if(!configureReports(bus))break;
  stage="attach-irq";
  IOLog("B5qTouch: stage=%s phase=before gpio=%u intid=%u\n",stage,B5qTouchIrq::gpio,B5qTouchIrq::intid);
  const uint32_t cfg=B5qTouchIrq::disabled(tlmmRead(B5qTouchIrq::cfg));
  tlmmWrite(B5qTouchIrq::cfg,cfg);tlmmWrite(B5qTouchIrq::status,0);
  int irqRc=kIOReturnNotReady;
  for(unsigned tries=0;tries<240;++tries){
   irqRc=armcpu_spi_share(B5qTouchIrq::intid,touchIrq,nullptr);
   if(irqRc!=kIOReturnNotReady)break;IOSleep(250);
  }
  IOLog("B5qTouch: stage=attach-irq phase=after intid=%u rc=%d\n",B5qTouchIrq::intid,irqRc);
  if(irqRc)break;
  irqAttached=true;__atomic_store_n(&irqOnline,true,__ATOMIC_RELEASE);
  tlmmWrite(B5qTouchIrq::cfg,cfg|1u);
  IOLog("B5qTouch: stage=ready address=20 gpio19=%u config=%lu seq=%u hid_reports=%u\n",!lowAttention(),(unsigned long)configBytes,native_touch_seq,native_touch_hid_reports);
  for(unsigned consecutive=0,readErrors=0;;){
   if(!lowAttention()){consecutive=0;waitAttention();continue;}
   uint8_t code=0;unsigned n=0;stage="read-report";
   if(!packet(bus,code,n)){
    reports.error();publish(false);
    consecutive=0;
    if(++readErrors==3){
     stage="bus-recovery";
     IOLog("B5qTouch: stage=%s errors=%u\n",stage,reports.errors);
     if(!bus.prepare()||!command(bus,2,nullptr,0)||!configureReports(bus))break;
     readErrors=0;
    }
    IOSleep(5);
    continue;
   }
   readErrors=0;report(code,n);
   if(reports.reconfigure || layoutFailures>=3){
    stage="report-recovery";
    if(!configureReports(bus,layoutFailures<3))break;
   }
   // Drain a sustained interrupt in batches so another thread can run.
   if(++consecutive==128){consecutive=0;IOSleep(1);}
  }
 }while(false);
 if(irqAttached){
  tlmmWrite(B5qTouchIrq::cfg,tlmmRead(B5qTouchIrq::cfg)&~1u);
  tlmmWrite(B5qTouchIrq::status,0);
  __atomic_store_n(&irqOnline,false,__ATOMIC_RELEASE);
 }
 // Release active contacts on initialization failure.
 reports.release();
 publish(false);
 IOLog("B5qTouch: stage=%s stopped error=%s stop=%s\n",stage,B5qTouchBus::name(bus.error()),B5qTouchBus::name(bus.stopError()));
 // The shared IRQ handler has no detach API; keep its pin mapping valid.
 if(!irqAttached && tlmmMapping)tlmmMapping->release();
 thread_terminate(current_thread());
}
}
extern "C" void native_touch_set_sink(void(*callback)(void*),void *context){sinkContext=context;__atomic_store_n(&sink,callback,__ATOMIC_RELEASE);}
extern "C" void b5q_touch_probe(void){unsigned on=0;if(!PE_parse_boot_argn("touch",&on,4)||on!=1)return;static uint32_t once=0;if(__atomic_exchange_n(&once,1u,__ATOMIC_ACQ_REL))return;thread_t t=nullptr;if(kernel_thread_start(worker,nullptr,&t)==KERN_SUCCESS)thread_deallocate(t);else IOLog("B5qTouch: stage=thread-allocation\n");}
