#!/usr/bin/env python3
"""Actual native IRQ/worker/start/stop bodies with deterministic scheduler races."""
from pathlib import Path
import subprocess,tempfile
R=Path(__file__).resolve().parents[2]
s=(R/'UniXNU-b5q/package/B5qDpIrq.cpp').read_text()
start=s.index('struct Irq {');brace=s.index('{',start);depth=0
for at in range(brace,len(s)):
 depth+=(s[at]=='{')-(s[at]=='}')
 if not depth:body=s[start:at+1]+';';break
# MMIO mapping and thread creation are target-compiled. Host tests replace
# only prepare(), which needs actual IOKit/GIC, not the IRQ/worker/lifetime.
start=body.index(' bool prepare(){');brace=body.index('{',start);depth=0
for at in range(brace,len(body)):
 depth+=(body[at]=='{')-(body[at]=='}')
 if not depth:body=body[:start]+' bool prepare(){return true;}'+body[at+1:];break
h=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include "B5qDpVsync.h"
#include "B5qDpIrq.h"
using wait_result_t=int;using event_t=void*;
struct IOMemoryMap{};struct IOLock{};IOLock theLock;
uint64_t ticks=0;bool waiting=false;unsigned locks=0,wakes=0,blocks=0,clears=0;
void (*inject)()=nullptr;
constexpr int THREAD_UNINT=0,THREAD_AWAKENED=1,THREAD_CONTINUE_NULL=0;
struct End{};
uint64_t mach_absolute_time(){return ++ticks;}
void absolutetime_to_nanoseconds(uint64_t value,uint64_t *out){*out=value*1000;}
void IOSleep(unsigned ms){ticks+=ms*1000;}
void IOLockLock(IOLock*){assert(!locks);locks++;}
void IOLockUnlock(IOLock*){assert(locks==1);locks--;}
void*current_thread(){return nullptr;}
void assert_wait(event_t,int){waiting=true;if(inject){auto action=inject;inject=nullptr;action();}}
void clear_wait(void*,int){assert(waiting);waiting=false;clears++;}
void thread_block(int){assert(waiting);waiting=false;blocks++;throw End{};}
void thread_wakeup(event_t){wakes++;}
#define IOLog(...) ((void)0)
'''
# ARM-only store barriers become host compiler barriers. W1C reads and
# writes still execute the actual owner source; emulate the HW W1C effect.
body=body.replace('asm volatile("dsb sy":::"memory");','asm volatile("":::"memory");')
body=body.replace('regs[off/4]=value;', 'if(off==0x1018)regs[0x1014/4]&=~value;regs[off/4]=value;')
test=r'''
Irq *current=nullptr;unsigned callbacks=0;uint32_t expectedFrame=0;uint64_t timestamp=0;bool stopInside=false;
void callback(void *ctx,uint32_t frame,uint64_t at){
 assert(ctx==current&&!locks&&frame==expectedFrame&&at);callbacks++;timestamp=at;
 if(stopInside)assert(!current->stop()&&current->context==current&&current->callback==callback);
}
void interrupt(){current->regs[0x1014/4]|=B5qDp::Vsync::frameBit;current->regs[0x350ac/4]=expectedFrame;Irq::primary(current);}
void run(Irq &irq){try{Irq::worker(&irq,0);}catch(End&){}assert(!waiting&&!locks);}
int main(){unsigned cases=0;
 for(unsigned scenario=0;scenario<5;scenario++){
  uint32_t regs[0x84000/4]{};Irq irq;irq.regs=regs;irq.lock=&theLock;current=&irq;
  callbacks=0;wakes=blocks=clears=0;stopInside=false;expectedFrame=100+scenario;
  regs[0x1010/4]=1u<<27;regs[0x1014/4]=1u<<27;
  assert(irq.start(&irq,callback)&&irq.enabled);
  assert(!irq.start(&irq,callback));Irq::primary(&irq);run(irq);assert(!callbacks&&regs[0x1014/4]==(1u<<27));
  if(scenario==0){interrupt();run(irq);assert(callbacks==1&&irq.seen==irq.generation);run(irq);assert(callbacks==1);}
  if(scenario==1){inject=interrupt;run(irq);assert(callbacks==1&&clears==1);}
  if(scenario==2){interrupt();irq.publication|=1;inject=[](){current->publication++;thread_wakeup(event_t(&current->generation));};run(irq);assert(callbacks==1&&clears==1);}
  if(scenario==3){interrupt();expectedFrame++;interrupt();run(irq);assert(callbacks==1&&irq.seen==irq.generation);}
  if(scenario==4){interrupt();stopInside=true;run(irq);assert(callbacks==1&&!irq.enabled&&irq.context==&irq);stopInside=false;}
  assert(irq.stop()&&!irq.context&&!irq.callback&&!irq.enabled);
  assert(regs[0x1010/4]==(1u<<27)&&regs[0x1014/4]==(1u<<27));
  auto count=callbacks;interrupt();run(irq);assert(callbacks==count);
  assert(irq.start(&irq,callback));assert(irq.stop());cases++;
 }
 {uint32_t regs[0x84000/4]{};Irq irq;irq.lock=&theLock;irq.regs=regs;current=&irq;
  regs[0x1010/4]=B5qDp::Vsync::mask;assert(!irq.start(&irq,callback)&&!irq.enabled&&!irq.context&&!irq.callback);cases++;}
 {uint32_t regs[0x84000/4]{};Irq irq;irq.lock=&theLock;irq.regs=regs;current=&irq;
  assert(irq.start(&irq,callback));irq.irqInFlight=1;assert(!irq.stop()&&irq.callback==callback&&irq.context==&irq);
  irq.irqInFlight=0;assert(irq.stop()&&!irq.callback&&!irq.context);cases++;}
 printf("PASS actual native MDSS IRQ worker %u scheduler/IRQ races/foreignsource isolation/callback drain/timeout/restart cases ASanUBSan\n",cases);
}
'''
with tempfile.TemporaryDirectory(prefix='b5q-dp-irq-')as td:
 t=Path(td);(t/'test.cpp').write_text(h+body+test)
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(R/'UniXNU-b5q/package'),str(t/'test.cpp'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test')],check=True,timeout=20)
