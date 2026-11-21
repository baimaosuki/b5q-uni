// SPDX-License-Identifier: BSD-2-Clause-Patent
// Samsung b5q S3916A: GENI1 SE4 FIFO, TouchComm V1; no DMA/SMMU.
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceMemory.h>
#include <kern/thread.h>
#include <pexpert/pexpert.h>
#include "GeniI2c.h"
#include "B5qTouchProtocol.h"
#include "B5qTouchClock.h"
#include "B5qTouchIrq.h"
#include "B5qTouchPower.h"
extern "C" {
wait_result_t clear_wait(thread_t,wait_result_t);
int armcpu_spi_share(uint32_t,void (*)(void *),void *);
volatile uint32_t native_touch_seq,native_touch_count,native_touch_hid_reports;
volatile int native_touch_xs[12],native_touch_ys[12],native_touch_ids[12];
}
namespace {
IOMemoryMap *maps[3];volatile uint32_t *tlmm,*gcc,*se;GeniI2c bus={};B5qTouch::Point points[12];
void (*sink)(void *);void *sinkContext;uint8_t message[4096],config[512];size_t configBytes;unsigned frames,maxObjects;
volatile uint32_t *map(unsigned n,uint64_t base,uint64_t bytes){auto *m=IODeviceMemory::withRange(base,bytes);maps[n]=m?m->map(kIOMapAnywhere|kIOMapInhibitCache):nullptr;OSSafeReleaseNULL(m);return maps[n]?reinterpret_cast<volatile uint32_t *>(maps[n]->getVirtualAddress()):nullptr;}
void barrier(){__asm__ volatile("dsb sy":::"memory");}
uint32_t tlmmRead(unsigned off){return tlmm[off/4];}
void tlmmWrite(unsigned off,uint32_t value){tlmm[off/4]=value;barrier();}
struct PmicPins {
 void low(unsigned pin,bool drive){
  const unsigned ctl=pin*0x1000;
  if(drive)tlmmWrite(ctl+4,tlmmRead(ctl+4)&~2u);
  const uint32_t config=tlmmRead(ctl)&~(1u<<9);
  tlmmWrite(ctl,config|(drive?(1u<<9):0));
 }
 bool high(unsigned pin){return tlmmRead(pin*0x1000+4)&1u;}
 void delay(unsigned us){IODelay(us);}
};
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
 PmicPins pins;
 const unsigned pinsToConfigure[]={B5qTouchPower::sda,B5qTouchPower::scl};
 for(unsigned pin:pinsToConfigure){
  const unsigned ctl=pin*0x1000;
  tlmmWrite(ctl,tlmmRead(ctl)&~0x3ffu); // GPIO input, external pullup, 2mA.
 }
 B5qTouchPower::Bus<PmicPins> bus(pins);
 uint8_t before=0,after=0;
 const bool ok=B5qTouchPower::enable(bus,before,after);
 IOLog("B5qTouch: s2dos05 enable=%02x->%02x verified=%u\n",before,after,ok);
 if(ok)IOSleep(100);
 return ok;
}
uint32_t rd(void *,uint32_t off){return se[off/4];}void wr(void *,uint32_t off,uint32_t v){se[off/4]=v;barrier();}
bool finish(){
 for(unsigned phase=0;phase<3;++phase){for(unsigned i=0;i<2000;++i){int rc=geni_i2c_poll(&bus);if(rc==GeniDone)return true;if(rc==GeniFailed)return false;IODelay(10);}if(geni_i2c_timeout(&bus)!=GeniPending)return false;}return false;
}
bool read(uint8_t *p,unsigned n){return !geni_i2c_start_read_only(&bus,p,n)&&finish();}
bool write(const uint8_t *p,unsigned n){return !geni_i2c_start_write_buffer(&bus,p,n)&&finish();}
bool packet(uint8_t &code,unsigned &length){
 uint8_t h[4];if(!read(h,4))return false;code=h[1];length=unsigned(h[2])|(unsigned(h[3])<<8);
 if(h[0]!=0xa5||length>4096){IOLog("B5qTouch: stage=header hdr=%02x/%02x/%02x/%02x\n",h[0],h[1],h[2],h[3]);return false;}
 return B5qTouch::continuation([](uint8_t *p,unsigned n){return read(p,n);},message,length);
}
void publish(){
 __atomic_fetch_add(&native_touch_seq,1u,__ATOMIC_RELEASE);unsigned count=0;
 for(unsigned i=0;i<12;++i)if(points[i].kind==1||points[i].kind==2){native_touch_xs[count]=int(B5qTouch::hid(points[i].x));native_touch_ys[count]=int(B5qTouch::hid(points[i].y));native_touch_ids[count]=int(i);++count;}
 native_touch_count=count;__asm__ volatile("dmb ish":::"memory");__atomic_fetch_add(&native_touch_seq,1u,__ATOMIC_RELEASE);
 if(auto callback=__atomic_load_n(&sink,__ATOMIC_ACQUIRE))callback(sinkContext);
 if(++frames<=8||!(frames%256))IOLog("B5qTouch: stage=report frames=%u contacts=%u seq=%u irq=%u\n",frames,count,native_touch_seq,__atomic_load_n(&irqEvents,__ATOMIC_RELAXED));
}
void report(uint8_t code,unsigned n){
 static unsigned sampled=0;
 if((code==0x11 || code==0xc1) && sampled++<5){
  char hex[97]={};const unsigned count=n<32?n:32;
  for(unsigned i=0;i<count;++i)snprintf(hex+3*i,sizeof(hex)-3*i,"%02x ",message[i]);
  IOLog("B5qTouch: raw code=%02x bytes=%u first=%s\n",code,n,hex);
 }
 bool ready=code==0x11&&configBytes?B5qTouch::parse(config,configBytes,message,n,points,maxObjects):code==0xc1?B5qTouch::sec(message,n,points):false;
 if(ready)publish();else if(code==0x11)IOLog("B5qTouch: stage=touch-layout code=%02x bytes=%u config=%lu\n",code,n,(unsigned long)configBytes);
}
bool command(uint8_t cmd,const uint8_t *p,unsigned n,bool getConfig=false){
 if(n>16)return false;uint8_t bytes[19]={cmd,uint8_t(n),uint8_t(n>>8)};if(n)memcpy(bytes+3,p,n);if(!write(bytes,n+3))return false;
 for(unsigned i=0;i<200;++i){if(tlmm[0x13004/4]&1){IOSleep(5);continue;}uint8_t code=0;unsigned length=0;if(!packet(code,length))return false;
  if(code==1){if(cmd==0x20&&!B5qTouch::appInfo(message,length,maxObjects))return false;if(getConfig){if(length>sizeof(config)||!length)return false;memcpy(config,message,length);configBytes=length;}return true;}
  if(code==0x10&&cmd==2){IOLog("B5qTouch: stage=identify mode=%u bytes=%u\n",length>1?message[1]:255,length);return length>1&&message[1]==1;}
  if(code>=0x10)report(code,length);else if(code!=0&&code!=7)return false;
 }
 return false;
}
void worker(void *,wait_result_t){
 const char *stage="mapping";uint32_t proto=0;
 do {
  IOLog("B5qTouch: stage=clock-check\n");
  tlmm=map(0,0xf100000,0x100000);gcc=map(1,0x100000,0x1f0000);if(!tlmm||!gcc)break;
  stage="touch-power";if(!powerTouch())break;
  unsigned failed=0;uint32_t last=0;
  auto clockRead=[](unsigned off){return gcc[off/4];};
  auto clockWrite=[](unsigned off,uint32_t value){gcc[off/4]=value;barrier();};
  if(!B5qTouchClock::enable(clockRead,clockWrite,[](unsigned us){IODelay(us);},failed,last)) {
   stage="s4-clk-off";IOLog("B5qTouch: stage=s4-clk-off offset=%08x cbcr=%08x\n",failed,last);break;
  }
  stage="s4-xo";if(!B5qTouchClock::xo(clockRead,clockWrite,[](unsigned us){IODelay(us);}))break;
  se=map(2,0xa90000,0x4000);if(!se)break;
  // GPIO mux1 is qup1_se4_l0/l1 in Samsung pinctrl-kalama; preserve drive/pull.
  tlmm[19*0x1000/4]&=~(1u<<9); // ATTN GPIO input, preserve pulls.
  for(unsigned pin=44;pin<=45;++pin)tlmm[pin*0x1000/4]=(tlmm[pin*0x1000/4]&~0x3cu)|(1u<<2);barrier();
  const GeniIo io={rd,wr,nullptr};
  // Firmware protocol and FIFO capability must already permit I2C. An idle
  // engine with a disabled clock receives the Samsung 19.2 MHz XO timing.
  stage="geni-prepare";int prepared=geni_i2c_prepare_xo(&bus,&io,0x20,&proto);
  IOLog("B5qTouch: stage=%s se_proto=%08x gpio19=%u clk=%08x scl=%08x rc=%d\n",stage,proto,tlmm[0x13004/4]&1,se[GENI_CLK_CFG/4],se[GENI_SCL_COUNTERS/4],prepared);if(prepared)break;
  stage="identify";if(!command(2,nullptr,0))break;
  stage="application-info";if(!command(0x20,nullptr,0))break;
  IOLog("B5qTouch: stage=application-info max_objects=%u\n",maxObjects);
  stage="report-config";bool got=command(0x25,nullptr,0,true);IOLog("B5qTouch: stage=report-config available=%u bytes=%lu\n",got,(unsigned long)configBytes);
  stage="enable-report";const uint8_t touch=0x11,samsung=0xc1;
  const bool ok11=command(5,&touch,1),okC1=command(5,&samsung,1);
  IOLog("B5qTouch: enable-report ok11=%u okC1=%u\n",ok11,okC1);
  if(!(ok11||okC1))break;
  stage="attach-irq";
  const uint32_t cfg=B5qTouchIrq::disabled(tlmmRead(B5qTouchIrq::cfg));
  tlmmWrite(B5qTouchIrq::cfg,cfg);tlmmWrite(B5qTouchIrq::status,0);
  const int irqRc=armcpu_spi_share(B5qTouchIrq::intid,touchIrq,nullptr);
  IOLog("B5qTouch: stage=attach-irq intid=%u rc=%d\n",B5qTouchIrq::intid,irqRc);
  if(irqRc)break;
  irqAttached=true;__atomic_store_n(&irqOnline,true,__ATOMIC_RELEASE);
  tlmmWrite(B5qTouchIrq::cfg,cfg|1u);
  IOLog("B5qTouch: stage=ready address=20 gpio19=%u config=%lu\n",!lowAttention(),(unsigned long)configBytes);
  for(unsigned consecutive=0;;){
   if(!lowAttention()){consecutive=0;waitAttention();continue;}
   uint8_t code=0;unsigned n=0;stage="read-report";
   if(++consecutive>128 || !packet(code,n))break;
   report(code,n);
  }
 }while(false);
 if(irqAttached){
  tlmmWrite(B5qTouchIrq::cfg,tlmmRead(B5qTouchIrq::cfg)&~1u);
  tlmmWrite(B5qTouchIrq::status,0);
  __atomic_store_n(&irqOnline,false,__ATOMIC_RELEASE);
 }
 // Always release active contacts on a terminal bus error.
 for(auto &p:points)p={};publish();IOLog("B5qTouch: stage=%s stopped se_proto=%08x error=%u status=%08x\n",stage,proto,bus.error,bus.error_status);
 // The shared IRQ handler has no detach API; keep its pin mapping valid.
 for(unsigned i=irqAttached?1u:0u;i<3;++i)if(maps[i])maps[i]->release();thread_terminate(current_thread());
}
}
extern "C" void native_touch_set_sink(void(*callback)(void*),void *context){sinkContext=context;__atomic_store_n(&sink,callback,__ATOMIC_RELEASE);}
extern "C" void b5q_touch_probe(void){unsigned on=0;if(!PE_parse_boot_argn("touch",&on,4)||on!=1)return;static uint32_t once=0;if(__atomic_exchange_n(&once,1u,__ATOMIC_ACQ_REL))return;thread_t t=nullptr;if(kernel_thread_start(worker,nullptr,&t)==KERN_SUCCESS)thread_deallocate(t);else IOLog("B5qTouch: stage=thread-allocation\n");}
