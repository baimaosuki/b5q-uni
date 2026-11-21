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
#include "B5qUsbIrq.h"
#define OSDeclareDefaultStructors(x)
constexpr uint32_t NSEC_PER_MSEC=1000000;
uint64_t now=0;
uint64_t mach_absolute_time(){return now;}
void clock_interval_to_absolutetime_interval(uint32_t interval,uint32_t scale,uint64_t *out){assert(interval==1000&&scale==NSEC_PER_MSEC);*out=1000000;}
using IOReturn=int;
constexpr int kIOReturnSuccess=0,kIOReturnNoInterrupt=-1,kIOReturnNoResources=-2,kIOReturnNotReady=-3,kIOInterruptTypeLevel=1;
struct OSObject{int refs=1;virtual ~OSObject()=default;void retain(){++refs;}void release(){--refs;}};
struct IOService;
using IOInterruptAction=void(*)(OSObject*,void*,IOService*,int);
struct IOService:OSObject{
 virtual IOReturn getInterruptType(int,int*){return 0;}
 virtual IOReturn registerInterrupt(int,OSObject*,IOInterruptAction,void*){return 0;}
 virtual IOReturn unregisterInterrupt(int){return 0;}
 virtual IOReturn enableInterrupt(int){return 0;}
 virtual IOReturn disableInterrupt(int){return 0;}
};
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
 if(raceAttach){action(context);assert(lineMasked);}
 return 0;
}
void fire(){assert(irqAction);irqAction(irqContext);}
void rejected(OSObject *owner,void *ctx,IOService*,int source){assert(owner==expectedOwner&&ctx==expectedContext&&!source);++calls;}
void accepted(OSObject *owner,void *ctx,IOService *nub,int source){rejected(owner,ctx,nub,source);assert(!nub->disableInterrupt(0));}
void acceptedAndReenabled(OSObject *owner,void *ctx,IOService *nub,int source){accepted(owner,ctx,nub,source);assert(!nub->enableInterrupt(0));}
'''
test='\nint main(){\n OSObject owner;expectedOwner=&owner;int cookie=7;expectedContext=&cookie;\n QcomDwc3Nub nub;\n assert(!nub.registerInterrupt(0,&owner,rejected,&cookie));assert(lineMasked&&gLineAttached&&attachCount==1);\n QcomDwc3Nub::route(&nub);assert(lineMasked);assert(!nub.enableInterrupt(0)&&!lineMasked);\n for(unsigned i=0;i<8191;i++)fire();assert(!lineMasked);fire();assert(lineMasked&&gIrqStormed);\n assert(nub.enableInterrupt(0)==kIOReturnNotReady);assert(!nub.disableInterrupt(0));assert(gIrqWindow.count==8193);\n assert(!nub.unregisterInterrupt(0));fire();assert(lineMasked);\n gIrqStormed=false;gIrqWindow={};now=1000000;\n QcomDwc3Nub good;OSObject owner2;expectedOwner=&owner2;\n assert(!good.registerInterrupt(0,&owner2,acceptedAndReenabled,&cookie));QcomDwc3Nub::route(&good);assert(!good.enableInterrupt(0));\n for(unsigned second=1;second<20;second++){now=second*1000000;for(unsigned i=0;i<1000;i++)fire();}assert(!gIrqStormed);\n now+=1000000;for(unsigned i=0;i<8192;i++)fire();assert(!gIrqStormed);fire();assert(gIrqStormed&&lineMasked);\n puts("PASS production QcomDwc3 attach-race/mask/role-routing and8193arrival timewindow evenwithconsumer mask/unmask cycles");\n}\n'
with tempfile.TemporaryDirectory(prefix='b5q-usb-irq-')as td:
 p=Path(td)/'test.cpp';p.write_text(stub+body+test);out=p.with_suffix('')
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=address,undefined','-I',str(root/'UniXNU-b5q/package'),str(p),'-o',str(out)],check=True)
 subprocess.run([str(out)],check=True)
