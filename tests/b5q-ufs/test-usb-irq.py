"""Exercise the production USB nub, including an IRQ racing inside attach."""
from pathlib import Path
import subprocess,tempfile
root=Path(__file__).resolve().parents[2]
source=(root/'UniXNU-b5q/package/B5qUsbHost.cpp').read_text()
body=source[source.index('class B5qUsbNub :'):source.index('OSDefineMetaClassAndStructors(B5qUsbNub')]
stub=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#define OSDeclareDefaultStructors(x)
using IOReturn=int;
constexpr int kIOReturnNoInterrupt=-1,kIOReturnNoResources=-2,kIOReturnNotReady=-3,kIOInterruptTypeLevel=1;
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
namespace B5qHardware{constexpr unsigned usbIrq=165;}
void barrier(){__atomic_thread_fence(__ATOMIC_SEQ_CST);}
void(*irqAction)(void*);void*irqContext;OSObject *expectedOwner;void *expectedContext;
bool lineMasked=true,raceAttach=true,attachFail=false;int maskFail=0,attachCount=0,maskCount=0,calls=0;
int armcpu_spi_mask(unsigned n,bool mask){assert(n==165);++maskCount;lineMasked=mask;return maskFail;}
int armcpu_spi_attach(unsigned n,bool edge,void(*action)(void*),void *context,uint32_t*,uint64_t*){
 assert(n==165&&!edge&&expectedOwner->refs==2);++attachCount;
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
test=r'''
int main(){
 OSObject owner;expectedOwner=&owner;int cookie=7;expectedContext=&cookie;
 B5qUsbNub nub;
 assert(nub.registerInterrupt(1,&owner,rejected,&cookie)==kIOReturnNoResources);
 assert(!nub.registerInterrupt(0,&owner,rejected,&cookie));assert(lineMasked&&attachCount==1&&maskCount==2);
 uint32_t irq,un,storm;nub.interruptStats(irq,un,storm);assert(irq==1&&un==1&&!storm);
 assert(!nub.disableInterrupt(0));nub.interruptStats(irq,un,storm);assert(!un);
 assert(!nub.enableInterrupt(0)&&!lineMasked);
 for(unsigned i=0;i<200;++i)fire();assert(!lineMasked);
 fire();assert(lineMasked);nub.interruptStats(irq,un,storm);assert(storm&&un==201&&calls==201);
 assert(nub.enableInterrupt(0)==kIOReturnNotReady&&lineMasked);
 assert(!nub.disableInterrupt(0));nub.interruptStats(irq,un,storm);assert(un==0&&storm);
 assert(!nub.unregisterInterrupt(0));fire();assert(lineMasked);
 B5qUsbNub good;OSObject owner2;expectedOwner=&owner2;calls=0;
 assert(!good.registerInterrupt(0,&owner2,accepted,&cookie));assert(!good.enableInterrupt(0));fire();
 good.interruptStats(irq,un,storm);assert(lineMasked&&!un&&!storm&&calls==1);
 B5qUsbNub cycle;OSObject owner3;expectedOwner=&owner3;
 assert(!cycle.registerInterrupt(0,&owner3,acceptedAndReenabled,&cookie));assert(!cycle.enableInterrupt(0));
 for(unsigned i=0;i<1000;++i)fire();cycle.interruptStats(irq,un,storm);assert(!storm&&un==1&&!lineMasked);
 // Attach failure unwinds callback ownership before it can ever be enabled.
 B5qUsbNub failure;OSObject owner4;expectedOwner=&owner4;attachFail=true;
 assert(failure.registerInterrupt(0,&owner4,rejected,&cookie)==kIOReturnNoResources&&owner4.refs==1);
 assert(failure.enableInterrupt(0)==kIOReturnNoInterrupt);
 puts("PASS actual USB nub: attach-race mask, callback publication, 201 IRQ fuse, disable resets, accepted filter and lifetime/error paths");
}
'''
with tempfile.TemporaryDirectory(prefix='b5q-usb-irq-')as td:
 p=Path(td)/'test.cpp';p.write_text(stub+body+test);out=p.with_suffix('')
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=address,undefined',str(p),'-o',str(out)],check=True)
 subprocess.run([str(out)],check=True)
