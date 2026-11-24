/* SPDX-License-Identifier: BSD-2-Clause-Patent */
/* b5q MDP0 INTF0 VSync, sharing the actual MDSS level IRQ115. Retain the
 * handler context/map for the platform lifetime, as ArmCpu share requires.
 * No polling/timer synthesizes frames; only real IRQs wake the worker. */
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceMemory.h>
#include <kern/thread.h>
#include <kern/clock.h>
#include <mach/mach_time.h>
#include "B5qDpIrq.h"
#include "B5qDpVsync.h"
extern "C" IOReturn armcpu_spi_share(uint32_t,void (*)(void *),void *);
extern "C" kern_return_t clear_wait(thread_t,wait_result_t);
namespace {
struct Irq {
 IOMemoryMap *map=nullptr;volatile uint32_t *regs=nullptr;
 IOLock *lock=nullptr;B5qDp::Vsync source;
 B5qDpFrameCallback callback=nullptr;void *context=nullptr;
 uint32_t generation=0,seen=0,publication=0,irqInFlight=0,callbackInFlight=0,enabled=0;
 uint32_t latestFrame=0;uint64_t latestTime=0;
 bool attached=false,workerStarted=false;
 uint32_t read(unsigned off){return regs[off/4];}
 void write(unsigned off,uint32_t value){regs[off/4]=value;asm volatile("dsb sy":::"memory");}
 void barrier(){asm volatile("dsb sy":::"memory");}
 void vsync(uint32_t frame){
  __atomic_add_fetch(&publication,1u,__ATOMIC_ACQ_REL);
  __atomic_store_n(&latestTime,mach_absolute_time(),__ATOMIC_RELAXED);
  __atomic_store_n(&latestFrame,frame,__ATOMIC_RELAXED);
  __atomic_add_fetch(&generation,1u,__ATOMIC_RELEASE);
  __atomic_add_fetch(&publication,1u,__ATOMIC_RELEASE);thread_wakeup(event_t(&generation));
 }
 static void primary(void *p){
  auto *self=static_cast<Irq*>(p);
  __atomic_add_fetch(&self->irqInFlight,1u,__ATOMIC_ACQ_REL);
  if(__atomic_load_n(&self->enabled,__ATOMIC_ACQUIRE))self->source.service(*self);
  __atomic_sub_fetch(&self->irqInFlight,1u,__ATOMIC_RELEASE);
 }
 static void worker(void *p,wait_result_t){
  auto *self=static_cast<Irq*>(p);
  for(;;){
   const uint32_t observed=__atomic_load_n(&self->generation,__ATOMIC_ACQUIRE);
   IOLockLock(self->lock);
   bool invoke=__atomic_load_n(&self->enabled,__ATOMIC_ACQUIRE)&&self->callback&&observed!=self->seen;
   B5qDpFrameCallback action=self->callback;void *context=self->context;
   uint32_t frame=0;uint64_t timestamp=0;
   if(invoke){
    const uint32_t before=__atomic_load_n(&self->publication,__ATOMIC_ACQUIRE);
    frame=__atomic_load_n(&self->latestFrame,__ATOMIC_ACQUIRE);timestamp=__atomic_load_n(&self->latestTime,__ATOMIC_ACQUIRE);
    const uint32_t after=__atomic_load_n(&self->publication,__ATOMIC_ACQUIRE);
    invoke=!(before&1)&&before==after&&observed==__atomic_load_n(&self->generation,__ATOMIC_ACQUIRE);
    if(invoke){self->seen=observed;__atomic_add_fetch(&self->callbackInFlight,1u,__ATOMIC_RELEASE);}
   }
   IOLockUnlock(self->lock);
   if(invoke){action(context,frame,timestamp);__atomic_sub_fetch(&self->callbackInFlight,1u,__ATOMIC_RELEASE);}
   assert_wait(event_t(&self->generation),THREAD_UNINT);
   if(observed!=__atomic_load_n(&self->generation,__ATOMIC_ACQUIRE)||
      (__atomic_load_n(&self->enabled,__ATOMIC_ACQUIRE)&&observed!=self->seen))clear_wait(current_thread(),THREAD_AWAKENED);
   else thread_block(THREAD_CONTINUE_NULL);
  }
 }
 bool prepare(){
  if(!lock){lock=IOLockAlloc();if(!lock)return false;}
  if(!map){
   auto *d=IODeviceMemory::withRange(0xae00000,0x84000);
   map=d?d->map(kIOMapAnywhere|kIOMapInhibitCache):nullptr;OSSafeReleaseNULL(d);
   regs=map?reinterpret_cast<volatile uint32_t*>(map->getVirtualAddress()):nullptr;
   if(!regs){OSSafeReleaseNULL(map);return false;}
  }
  if(!workerStarted){
   thread_t thread=nullptr;
   if(kernel_thread_start(worker,this,&thread)!=KERN_SUCCESS)return false;
   thread_deallocate(thread);workerStarted=true;
  }
  if(!attached){
   // This source is still disabled. Existing shared handlers keep their
   // interrupt enables and pending bits; never mask the whole MDSS IRQ.
   if(read(0x1010)&B5qDp::Vsync::mask)return false;
   const IOReturn result=armcpu_spi_share(0x53+32,primary,this);
   IOLog("B5qDP: vsync IRQ115 share=%x\n",result);
   if(result!=kIOReturnSuccess)return false;attached=true;
  }
  return true;
 }
 bool start(void *nextContext,B5qDpFrameCallback action){
  if(!nextContext||!action||!prepare())return false;
  IOLockLock(lock);
  bool ok=false;
  if(!__atomic_load_n(&enabled,__ATOMIC_ACQUIRE)&&!__atomic_load_n(&callbackInFlight,__ATOMIC_ACQUIRE)&&
     !__atomic_load_n(&irqInFlight,__ATOMIC_ACQUIRE)){
   callback=action;context=nextContext;seen=__atomic_load_n(&generation,__ATOMIC_ACQUIRE);
   __atomic_store_n(&enabled,1u,__ATOMIC_RELEASE);
   ok=source.begin(*this);
   if(!ok){__atomic_store_n(&enabled,0u,__ATOMIC_RELEASE);callback=nullptr;context=nullptr;}
  }
  IOLockUnlock(lock);return ok;
 }
 bool stop(){
  if(!lock)return true;
  IOLockLock(lock);__atomic_store_n(&enabled,0u,__ATOMIC_RELEASE);source.end(*this);IOLockUnlock(lock);
  uint64_t ns=0;const uint64_t start=mach_absolute_time();
  while(__atomic_load_n(&irqInFlight,__ATOMIC_ACQUIRE)||__atomic_load_n(&callbackInFlight,__ATOMIC_ACQUIRE)){
   absolutetime_to_nanoseconds(mach_absolute_time()-start,&ns);
   if(ns>=100000000){IOLog("B5qDP: vsync callback retained irq=%u worker=%u\n",irqInFlight,callbackInFlight);return false;}
   IOSleep(1);
  }
  IOLockLock(lock);callback=nullptr;context=nullptr;IOLockUnlock(lock);return true;
 }
};
// start/stop belongs to the serialized DP lifecycle owner. The ArmCpu
// callback and sleeping worker own this allocation for the boot lifetime.
Irq *irq;
}
extern "C" bool b5q_dp_irq_start(void *context,B5qDpFrameCallback action){
 if(!irq)irq=new Irq;
 return irq&&irq->start(context,action);
}
extern "C" bool b5q_dp_irq_stop(void){return !irq||irq->stop();}
