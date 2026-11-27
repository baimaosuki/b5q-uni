#!/usr/bin/env python3
"""Execute the actual Owner/ScanIo plus real DPU/Presentation end-to-end."""
from pathlib import Path
import subprocess,tempfile
R=Path(__file__).resolve().parents[2]
s=(R/'UniXNU-b5q/package/B5qDpLink.cpp').read_text();start=s.index('struct Owner {');brace=s.index('{',start);depth=0
for at in range(brace,len(s)):
 depth+=(s[at]=='{')-(s[at]=='}')
 if not depth:body=s[start:at+1]+';';break
body=body.replace('asm volatile("dc cvac, %0"::"r"(at):"memory");','cacheCleanLine(at);')
h=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <map>
#include <vector>
#include "B5qDpDma.h"
#include "B5qDpPort.h"
#include "B5qDpPresentation.h"
#include "B5qDpDisplay.h"
#include "B5qDpAux.h"
#include "B5qDpIrq.h"
using B5qDp::Block;
constexpr int kIOReturnSuccess=0,kIODirectionOut=1,kIOServiceSynchronous=1,kIOMapCopybackCache=0x1000;
unsigned cleanLines=0;void cacheCleanLine(uintptr_t at){assert(!(at&63));cleanLines++;}
struct IOLock{bool locked=false;};IOLock *IOLockAlloc(){return new IOLock;}
void IOLockLock(IOLock *l){assert(l&&!l->locked);l->locked=true;}void IOLockUnlock(IOLock *l){assert(l&&l->locked);l->locked=false;}
uint64_t tick=100;uint64_t nowUs(){return tick;}void barrier(){}
template<class...Args>void log(const char *,Args...a){((void)a,...);}
#define IOLog(...) log(__VA_ARGS__)
struct IOService {
 bool attached=false;unsigned refs=1;IOService *parent=nullptr;
 bool init(){return true;}bool attach(IOService *p){parent=p;attached=true;return true;}
 IOService *getProvider(){return parent;}void detach(IOService *){parent=nullptr;attached=false;}
 void setName(const char*){}void retain(){refs++;}void release(){assert(refs);if(!--refs)delete this;}
 void terminate(unsigned){}static IOService *getPlatform(){static IOService p;return &p;}
};
struct OSMetaClass{static void *preModLoad(const char*){return (void*)1;}static int postModLoad(void*){return 0;}};
struct{const char *name="test";}g_kernel_kmod_info;void b5q_dp_display_static_init(){}
struct PE_Video{uint64_t v_baseAddr=0xb8000000;unsigned v_rowBytes=4320,v_height=2640;};
int PE_current_console(PE_Video *p){*p={};return 0;}
struct OSData{void *p;unsigned bytes;unsigned getLength(){return bytes;}const void *getBytesNoCopy(){return p;}};
B5Q_DP_DMA_STATE firmware;uint32_t ready=1;OSData stateData{&firmware,80},flagData{&ready,4};
int gIODTPlane;
struct IORegistryEntry {static IORegistryEntry *fromPath(const char *,int){static IORegistryEntry c;return &c;}
 OSData *getProperty(const char *name){return !strcmp(name,"b5q-dp-dma-ready")?&flagData:&stateData;}void release(){}
};
#define OSDynamicCast(type,value) static_cast<type*>(value)
#define OSSafeReleaseNULL(p) do{if(p){(p)->release();p=nullptr;}}while(0)
struct IOMemoryDescriptor{
 std::vector<uint8_t> bytes;bool fail=false;unsigned prepared=0,completed=0;
 uint64_t getLength(){return bytes.size();}int prepare(int){prepared++;return fail?1:0;}void complete(int){completed++;}
 unsigned readBytes(uint64_t at,void *p,unsigned n){if(at>bytes.size()||n>bytes.size()-at)return 0;memcpy(p,bytes.data()+at,n);return n;}
};
void *IOMallocData(unsigned bytes){return malloc(bytes);}void IOFreeData(void *p,unsigned){free(p);}
struct Window {std::vector<uint32_t> memory;volatile uint32_t *va=nullptr;
 bool open(uint64_t,unsigned bytes,unsigned cache){assert(cache==kIOMapCopybackCache);memory.resize(bytes/4);va=memory.data();return true;}
 void close(){va=nullptr;memory.clear();}
};
bool drainOk=true;unsigned publications=0,completedTags=0;B5qDpDisplayConfig displayConfig;
B5qDpFrameCallback irqCallback=nullptr;void *irqContext=nullptr;
bool b5q_dp_irq_start(void *p,B5qDpFrameCallback cb){assert(!irqContext);irqContext=p;irqCallback=cb;return true;}
bool b5q_dp_irq_stop(){if(!drainOk)return false;irqContext=nullptr;irqCallback=nullptr;return true;}
IOService *b5q_dp_display_create(IOService *provider,const B5qDpDisplayConfig *c){assert(provider&&c);displayConfig=*c;publications++;auto *p=new IOService;p->attach(provider);return p;}
bool b5q_dp_display_disconnect(IOService*){return displayConfig.drain(displayConfig.context);}
void b5q_dp_display_frame(IOService *,uint64_t tag,uint32_t,uint64_t){if(tag)completedTags++;}
struct Hardware{
 bool opened=false,mxOwned=false,fault=false,cablePresent=true;unsigned wantedReverse=0;struct{unsigned failed=0;}clock;
 std::map<unsigned,uint32_t>regs;
 bool open(bool reverse){opened=true;wantedReverse=reverse;return true;}bool close(){opened=false;return true;}
 bool connected(){return opened&&cablePresent;}
 uint32_t read(B5qDp::Block b,unsigned off){assert(b==B5qDp::Block::Dpu);return regs[off];}
 void write(B5qDp::Block b,unsigned off,uint32_t v){assert(b==B5qDp::Block::Dpu);regs[off]=v;}
 void delay(unsigned us){tick+=us;regs[0x3526c]=regs[0x35000]&1;if(regs[0x35000]&1)regs[0x350ac]++;
  for(unsigned c=0;c<6;c++)regs[B5qDp::DpuResources::ctlBase[c]+0x18]=0;
 }
};
namespace B5qDp {
template<class Io>struct Session {
 Io &io;bool streaming=false,trained=false;unsigned rate=20,lanes=2,attempts=1,error=0;
 struct{unsigned failed=0,last=0;}clock,phy;Modes modes;Mode selected{};uint8_t edid[128]{};unsigned edidBytes=128;
 unsigned discoverStep=6,trainError=0;uint8_t dpcd[16]{};
 struct{unsigned revision=0x14,rate=20,lanes=2;bool enhanced=true;}caps;
 struct Controller{Session &s;void stop(){s.streaming=false;}}controller;
 struct Aux{bool dpcd(bool,unsigned,uint8_t *out,unsigned n){memset(out,0x77,n);out[2]=1;return true;}unsigned error=0,lastStatus=0,transactions=0;}aux;
 explicit Session(Io &i):io(i),controller{*this}{}
 bool stop(){streaming=trained=false;selected={};return true;}
 bool discover(unsigned n,bool){lanes=n;modes={};return modes.advertisedVic(16)&&modes.advertisedVic(97);}
 bool train(){assert(modes.count==1&&modes.values[0].width==1920);selected=modes.values[0];trained=true;return true;}
 bool video(){streaming=true;return true;}
};
}
'''
test=r'''
int main(){unsigned cases=0;assert(B5qDpPool(&firmware,0xb8000000,1080*2640*4,0xb8000000+1080*2640*4));firmware.RetentionStatus=0;
 Owner o;B5qDpPortState port{};port.attached=port.configured=port.hpd=true;port.reverse=0;port.lanes=2;port.pin=8;port.generation=1;
 ready=0;o.update(port);assert(!o.accepted&&!publications);ready=1;tick+=1000000;o.update(port);
 assert(o.accepted&&o.presentation.ready&&o.display&&irqCallback&&publications==1);cases++;
 IOMemoryDescriptor memory;memory.bytes.resize(1920*1080*4);for(unsigned i=0;i<memory.bytes.size();i++)memory.bytes[i]=uint8_t(i);
 for(uint64_t tag=1;tag<=8;tag++){
  assert(displayConfig.present(displayConfig.context,&memory,1920*4,false,tag));
  const auto slot=o.presentation.next;const auto off=(o.presentation.buffers[slot].address-firmware.PoolBase)/4;
  assert(o.pool.va[off]==0x03020100&&o.presentation.pendingTag==tag&&cleanLines);
  o.io.delay(17000);assert(irqCallback);irqCallback(irqContext,o.io.regs[0x350ac],tick);
  assert(!o.presentation.pendingTag&&completedTags==tag&&memory.prepared==tag&&memory.completed==tag);cases++;
 }
 // A partial DMA drain must not release the primary-independent pool or
 // PHY. Retrying the exact physical unplug finishes without stale tags.
 drainOk=false;port.hpd=false;o.update(port);assert(!o.accepted&&o.pool.va&&o.display);cases++;
 drainOk=true;o.update(port);assert(!o.pool.va&&!o.display&&!o.io.opened&&!irqContext);cases++;
 port.hpd=true;port.reverse=1;port.generation++;o.update(port);assert(o.accepted&&o.io.wantedReverse==1&&publications==2);
 assert(displayConfig.present(displayConfig.context,nullptr,0,true,99));o.io.delay(17000);irqCallback(irqContext,o.io.regs[0x350ac],tick);assert(completedTags==9);cases++;
 assert(displayConfig.present(displayConfig.context,&memory,1920*4,false,100));tick+=100000;o.update(port);
 assert(o.accepted&&publications==3&&!o.presentation.pendingTag);cases++;
 assert(o.stop()&&!o.pool.va);delete o.scanLock;
 printf("PASS native DP pipeline %u end-to-end cases:firmwaregate/modefilter/training/realDPU/buffer-copy/IRQ-tag/IOMFB/no-lid/unplug-drain/replug/timeout-retrain ASanUBSan\n",cases);
}
'''
with tempfile.TemporaryDirectory(prefix='b5q-dp-pipeline-')as td:
 t=Path(td);(t/'test.cpp').write_text(h+body+test)
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-Wno-missing-field-initializers','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(R/'UniXNU-b5q/package'),str(t/'test.cpp'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test')],check=True)
