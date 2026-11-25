"""Exercise the original QcomDwc3 nub with its actual one-second fuse."""
from pathlib import Path
import subprocess,tempfile
root=Path(__file__).resolve().parents[2]
source=(root/'UniXNU-b5q/package/QcomDwc3.cpp').read_text()
a=source.index('class QcomDwc3Nub;');b=source.index('OSDefineMetaClassAndStructors(QcomDwc3Nub',a)
body=source[a:b].replace('__asm__ volatile("dmb ish" ::: "memory");','barrier();')
stub=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <mutex>
#include <thread>
#include <atomic>
#include <chrono>
#include "B5qUsbIrq.h"
#define OSDeclareDefaultStructors(x)
constexpr uint32_t NSEC_PER_MSEC=1000000;
uint64_t now=0;
uint64_t mach_absolute_time(){return now;}
void clock_interval_to_absolutetime_interval(uint32_t interval,uint32_t scale,uint64_t *out){assert(interval==1000&&scale==NSEC_PER_MSEC);*out=1000000;}
using IOReturn=int;
constexpr int kIOReturnSuccess=0,kIOReturnNoInterrupt=-1,kIOReturnNoResources=-2,kIOReturnNotReady=-3,kIOInterruptTypeLevel=1;
thread_local bool hardContext=false;
std::atomic<bool> pauseDrain{false},callbackDone{false},irqDrained{false},returnIRQ{false};
std::atomic<unsigned> destroyed{0};
struct OSObject{std::atomic<int> refs{1};virtual ~OSObject(){assert(!hardContext);++destroyed;}
 void retain(){assert(!hardContext);++refs;}void release(){assert(!hardContext);if(--refs==0)delete this;}};
struct IOService;
using IOInterruptAction=void(*)(OSObject*,void*,IOService*,int);
struct IOService:OSObject{
 virtual IOReturn getInterruptType(int,int*){return 0;}
 virtual IOReturn registerInterrupt(int,OSObject*,IOInterruptAction,void*){return 0;}
 virtual IOReturn unregisterInterrupt(int){return 0;}
 virtual IOReturn enableInterrupt(int){return 0;}
 virtual IOReturn disableInterrupt(int){return 0;}
};
struct IOSimpleLock{std::mutex m;};
IOSimpleLock *IOSimpleLockAlloc(){return new IOSimpleLock;}
void IOSimpleLockFree(IOSimpleLock*p){delete p;}
bool IOSimpleLockLockDisableInterrupt(IOSimpleLock*p){p->m.lock();return true;}
void IOSimpleLockUnlockEnableInterrupt(IOSimpleLock*p,bool){p->m.unlock();
 if(hardContext&&pauseDrain&&callbackDone){irqDrained=true;while(!returnIRQ)std::this_thread::yield();}}
void IOSleep(unsigned ms){std::this_thread::sleep_for(std::chrono::milliseconds(ms));}
#define OSSafeReleaseNULL(p) do{if(p)(p)->release();p=nullptr;}while(0)
void barrier(){__atomic_thread_fence(__ATOMIC_SEQ_CST);}
constexpr unsigned kIrq=165;
uint32_t native_usb_stats[54];

void(*irqAction)(void*);void*irqContext;OSObject *expectedOwner;void *expectedContext;
bool lineMasked=true,raceAttach=true,attachFail=false;int maskFail=0,attachCount=0,maskCount=0,calls=0;
int armcpu_spi_mask(unsigned n,bool mask){assert(n==165);++maskCount;lineMasked=mask;return maskFail;}
int armcpu_spi_attach(unsigned n,bool edge,void(*action)(void*),void *context,uint32_t*,uint64_t*){
 assert(n==165&&!edge&&expectedOwner->refs>=2);++attachCount;
 if(attachFail)return -9;
 irqAction=action;irqContext=context;lineMasked=false;
 if(raceAttach){hardContext=true;action(context);hardContext=false;assert(lineMasked);}
 return 0;
}
void fire(){assert(irqAction);hardContext=true;irqAction(irqContext);hardContext=false;}
void rejected(OSObject *owner,void *ctx,IOService*,int source){assert(owner==expectedOwner&&ctx==expectedContext&&!source);++calls;}
void accepted(OSObject *owner,void *ctx,IOService *nub,int source){rejected(owner,ctx,nub,source);assert(!nub->disableInterrupt(0));}
void acceptedAndReenabled(OSObject *owner,void *ctx,IOService *nub,int source){accepted(owner,ctx,nub,source);assert(!nub->enableInterrupt(0));}
'''
test=r"""
std::atomic<bool> entered{false},allowExit{false},drained{false};
void blocked(OSObject*,void*,IOService*,int){entered=true;while(!allowExit)std::this_thread::yield();callbackDone=true;}
int main(){
 OSObject owner;expectedOwner=&owner;int cookie=7;expectedContext=&cookie;QcomDwc3Nub nub;
 assert(!nub.registerInterrupt(0,&owner,rejected,&cookie));assert(lineMasked&&gLineAttached&&attachCount==1&&owner.refs==2);
 QcomDwc3Nub::route(&nub);assert(lineMasked);assert(!nub.enableInterrupt(0)&&!lineMasked);
 for(unsigned i=0;i<B5qUsbIrq::Window::limit;i++)fire();assert(!gIrqStormed);fire();assert(lineMasked&&gIrqStormed);
 assert(nub.enableInterrupt(0)==kIOReturnNotReady);assert(!nub.unregisterInterrupt(0)&&owner.refs==1);
 QcomDwc3Nub::route(nullptr);assert(nub.refs==1);
 now=1000000;QcomDwc3Nub good;OSObject owner2;expectedOwner=&owner2;
 assert(!good.registerInterrupt(0,&owner2,acceptedAndReenabled,&cookie));QcomDwc3Nub::route(&good);assert(!gIrqStormed&&!gIrqWindow.count);
 assert(!good.enableInterrupt(0));for(unsigned sec=1;sec<20;sec++){now=sec*1000000;for(unsigned i=0;i<8193;i++)fire();}assert(!gIrqStormed);
 assert(!good.unregisterInterrupt(0)&&owner2.refs==1);QcomDwc3Nub::route(nullptr);
 // Failure after callback retention must undo its reference; the global line
 // is reset here only to model a first-ever GIC attachment that fails.
 gLineAttached=false;attachFail=true;expectedOwner=&owner;
 QcomDwc3Nub failed;assert(failed.registerInterrupt(0,&owner,rejected,&cookie)==kIOReturnNoResources&&owner.refs==1);
 attachFail=false;QcomDwc3Nub racing;assert(!racing.registerInterrupt(0,&owner,blocked,&cookie));QcomDwc3Nub::route(&racing);racing.enableInterrupt(0);
 std::thread irq([]{fire();});while(!entered)std::this_thread::yield();
 std::thread detach([&]{QcomDwc3Nub::route(nullptr);racing.unregisterInterrupt(0);drained=true;});
 std::this_thread::sleep_for(std::chrono::milliseconds(5));assert(!drained&&owner.refs>=2&&racing.refs>=2);
 allowExit=true;irq.join();detach.join();assert(drained&&owner.refs==1&&racing.refs==1&&lineMasked);
 // Drop all caller references: registration and route now own the objects.
 // Pause IRQ after its final unlock; teardown can destroy both before it returns.
 callbackDone=false;entered=false;allowExit=false;drained=false;
 auto *heapOwner=new OSObject;auto *heapNub=new QcomDwc3Nub;expectedOwner=heapOwner;
 assert(!heapNub->registerInterrupt(0,heapOwner,blocked,&cookie));QcomDwc3Nub::route(heapNub);heapNub->enableInterrupt(0);
 heapOwner->release();heapNub->release();unsigned beforeDestroy=destroyed;
 pauseDrain=true;std::thread heapIRQ([]{fire();});while(!entered)std::this_thread::yield();
 std::thread retire([&]{heapNub->unregisterInterrupt(0);QcomDwc3Nub::route(nullptr);drained=true;});
 allowExit=true;while(!irqDrained)std::this_thread::yield();retire.join();
 assert(drained&&destroyed==beforeDestroy+2);returnIRQ=true;heapIRQ.join();pauseDrain=false;
 puts("PASS production USB IRQ:attach-race mask,65536/s fuse+role reset,19s@8193/s safe,targetref cleanup,blocked IRQ route/unregister drains withoutUAF; nohardIRQretain/release/free; finalthreadrefs destroyedbeforeIRQreturn");
}
"""
with tempfile.TemporaryDirectory(prefix='b5q-usb-irq-')as td:
 p=Path(td)/'test.cpp';p.write_text(stub+body+test);out=p.with_suffix('')
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=address,undefined','-pthread','-I',str(root/'UniXNU-b5q/package'),str(p),'-o',str(out)],check=True)
 subprocess.run([str(out)],check=True)
