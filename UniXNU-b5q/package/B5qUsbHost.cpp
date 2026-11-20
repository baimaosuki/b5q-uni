// SPDX-License-Identifier: BSD-2-Clause-Patent
// b5q warm host path. The original AppleUSBXHCI owns rings and USB/HID.
// No Xiaomi rails/retimer/UCSI/GPIO and no apps_smmu register access.
#include "OriginalUsbXhciABI.h"
#include "B5qUsbPolicy.h"
#include "B5qSpmi.h"
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceMemory.h>
#include <IOKit/IOPlatformExpert.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <libkern/OSKextLib.h>
#include <libkern/c++/OSNumber.h>
#include <kern/thread.h>
#include <pexpert/pexpert.h>
#include <pexpert/arm64/boot.h>
extern kmod_info_t g_kernel_kmod_info;
extern "C" {
int armcpu_spi_attach(uint32_t,bool,void(*)(void*),void*,uint32_t*,uint64_t*);
int armcpu_spi_mask(uint32_t,bool);
void b5q_usb_static_init(void) __asm__("__GLOBAL__sub_I_B5qUsbHost.cpp");
volatile int b5q_usb_state=0;
}
namespace {
void barrier(){__asm__ volatile("dsb sy" ::: "memory");}
constexpr uint64_t kUsbCoreBytes = 0x10000;
constexpr uint64_t kQscratchBase = 0xa6f8000ULL;
constexpr uint64_t kGccBase = 0x100000ULL;
constexpr uint64_t kGccBytes = 0x1f0000ULL;

struct Mapping {
 IODeviceMemory *memory=nullptr;
 IOMemoryMap *map=nullptr;
 volatile uint8_t *va=nullptr;
 bool open(uint64_t base,uint64_t bytes) {
  memory=IODeviceMemory::withRange(base,bytes);
  map=memory?memory->map(kIOMapAnywhere|kIOMapInhibitCache):nullptr;
  va=map?reinterpret_cast<volatile uint8_t *>(map->getVirtualAddress()):nullptr;
  return va!=nullptr;
 }
 void close() { OSSafeReleaseNULL(map); OSSafeReleaseNULL(memory); va=nullptr; }
 ~Mapping() { close(); }
};

template <typename T>
bool readReg(volatile uint8_t *base,uint64_t bytes,uint32_t off,T &out) {
 if(!base || off%4 || uint64_t(off)+sizeof(T)>bytes)return false;
 const volatile uint32_t *p=reinterpret_cast<const volatile uint32_t *>(base+off);
 if constexpr(sizeof(T)==4) out=T(*p);
 else out=T(p[0])|(T(p[1])<<32);
 return true;
}
bool writeReg(volatile uint8_t *base,uint64_t bytes,uint32_t off,uint32_t value) {
 if(!base || off%4 || uint64_t(off)+4>bytes)return false;
 *reinterpret_cast<volatile uint32_t *>(base+off)=value;barrier();return true;
}

void monitor(void *argument,wait_result_t) {
 Mapping *mapping=static_cast<Mapping *>(argument);
 uint32_t cap=0;readReg(mapping->va,kUsbCoreBytes,0,cap);const uint32_t op=cap&255;
 uint32_t last[4]={0,0,0,0};unsigned samples=0,lastDevices=~0u,lastId=~0u;
 for(;;) {
  uint32_t values[4]={0,0,0,0};
  readReg(mapping->va,kUsbCoreBytes,op,values[0]);
  readReg(mapping->va,kUsbCoreBytes,op+4,values[1]);
  readReg(mapping->va,kUsbCoreBytes,op+0x400,values[2]);
  readReg(mapping->va,kUsbCoreBytes,op+0x410,values[3]);
  bool changed=samples<5;
  for(unsigned i=0;i<4;++i) changed|=values[i]!=last[i];
  OSDictionary *matching=IOService::serviceMatching("IOUSBHostDevice");
  unsigned devices=0;uint32_t lastIdNow=0;
  if(matching) {
   OSIterator *iterator=IOService::getMatchingServices(matching);matching->release();
   if(iterator) {
    while(OSObject *object=iterator->getNextObject()) {
     IORegistryEntry *device=OSDynamicCast(IORegistryEntry,object);++devices;
     if(device) {
      OSNumber *vendor=OSDynamicCast(OSNumber,device->getProperty("idVendor"));
      OSNumber *product=OSDynamicCast(OSNumber,device->getProperty("idProduct"));
      if(vendor && product)lastIdNow=(vendor->unsigned32BitValue()<<16)|(product->unsigned32BitValue()&0xffff);
     }
    }
    iterator->release();
   }
  }
  changed|=devices!=lastDevices || lastIdNow!=lastId;
  if(changed) {
   IOLog("B5qUsb: cmd=%08x sts=%08x port1=%08x port2=%08x devs=%u last=%08x\n",
     values[0],values[1],values[2],values[3],devices,lastIdNow);
   for(unsigned i=0;i<4;++i)last[i]=values[i];
   lastDevices=devices;lastId=lastIdNow;
  }
  ++samples;
  IOSleep(2000);
 }
}
}
class B5qUsbHost : public AppleUSBXHCI {
 OSDeclareDefaultStructors(B5qUsbHost)
public:
 uint32_t XHCI_DESIRED_POWER() override {return 3;}
 uint64_t XHCI_READ64(void *base,uint32_t offset) override {
  auto *p=reinterpret_cast<volatile uint32_t*>(static_cast<uint8_t*>(base)+offset);
  const uint32_t lo=p[0];return lo|(uint64_t(p[1])<<32);
 }
 void XHCI_WRITE64(void *base,uint32_t offset,uint64_t value) override {
  auto *p=reinterpret_cast<volatile uint32_t*>(static_cast<uint8_t*>(base)+offset);
  p[1]=uint32_t(value>>32);barrier();p[0]=uint32_t(value);barrier();
 }
};
OSDefineMetaClassAndStructors(B5qUsbHost,AppleUSBXHCI)
class B5qUsbNub : public IOService {
 OSDeclareDefaultStructors(B5qUsbNub)
 IOInterruptAction action=nullptr;OSObject *owner=nullptr;void *context=nullptr;
 bool enabled=false,attachedLine=false;
 static void interrupt(void *p) {
  auto *self=static_cast<B5qUsbNub*>(p);
  if(self->enabled && self->action)self->action(self->owner,self->context,self,0);
 }
public:
 IOReturn getInterruptType(int source,int *type) override {
  if(source || !type)return kIOReturnNoInterrupt;*type=kIOInterruptTypeLevel;return 0;
 }
 IOReturn registerInterrupt(int source,OSObject *target,IOInterruptAction handler,void *ref) override {
  if(source || !target || !handler || action)return kIOReturnNoResources;
  if(!attachedLine) {
   if(armcpu_spi_attach(B5qHardware::usbIrq,false,interrupt,this,nullptr,nullptr))return kIOReturnNoResources;
   // ArmCpu has no detach API. Pin this callback context for the kernel lifetime.
   retain();attachedLine=true;
  }
  target->retain();owner=target;context=ref;action=handler;barrier();return 0;
 }
 IOReturn unregisterInterrupt(int source) override {
  if(source)return kIOReturnNoInterrupt;enabled=false;armcpu_spi_mask(B5qHardware::usbIrq,true);barrier();
  // The possibly in-flight IRQ retains a stable owner. This one-shot driver
  // does not release registered callback storage during failed startup.
  action=nullptr;return 0;
 }
 IOReturn enableInterrupt(int source) override {
  if(source || !action)return kIOReturnNoInterrupt;enabled=true;barrier();return armcpu_spi_mask(B5qHardware::usbIrq,false);
 }
 IOReturn disableInterrupt(int source) override {
  if(source)return kIOReturnNoInterrupt;enabled=false;barrier();return armcpu_spi_mask(B5qHardware::usbIrq,true);
 }
};
OSDefineMetaClassAndStructors(B5qUsbNub,IOService)
namespace {
static void worker(void *,wait_result_t) {
 const char *stage="boot-ram";Mapping core,qScratch,gcc;B5qUsbNub *nub=nullptr;
 IODeviceMemory *memory=nullptr;OSArray *ranges=nullptr;B5qUsbHost *host=nullptr;
 bool attached=false,hostAttached=false,startAttempted=false;
 do {
  auto *boot=static_cast<boot_args*>(PE_state.bootArgs);
  if(!boot || !B5qUsbPolicy::validRam(boot->physBase,boot->memSize))break;
  stage="map-core";
  if(!core.open(B5qHardware::usbBase,kUsbCoreBytes) ||
     !qScratch.open(kQscratchBase,0x1000) || !gcc.open(kGccBase,kGccBytes))break;
  uint32_t gdsc=0,master=0;
  readReg(gcc.va,kGccBytes,0x39004,gdsc);readReg(gcc.va,kGccBytes,0x39018,master);
  IOLog("B5qUsb: stage=warm-clocks initial-gdsc=%08x master=%08x\n",gdsc,master);
  auto gccRead=[&](unsigned off,uint32_t &v){return readReg(gcc.va,kGccBytes,off,v);};
  auto gccWrite=[&](unsigned off,uint32_t v){return writeReg(gcc.va,kGccBytes,off,v);};
  stage=B5qUsbPolicy::clocks(gccRead,gccWrite,[](unsigned us){IODelay(us);});if(stage)break;
  uint32_t hs=0,ss=0;
  readReg(qScratch.va,0x1000,0x810,hs);readReg(qScratch.va,0x1000,0x830,ss);
  IOLog("B5qUsb: stage=warm-phy scratch-hs=%08x scratch-ss=%08x\n",hs,ss);
  auto scratchRead=[&](unsigned off,uint32_t &v){return readReg(qScratch.va,0x1000,off,v);};
  auto scratchWrite=[&](unsigned off,uint32_t v){return writeReg(qScratch.va,0x1000,off,v);};
  stage=B5qUsbPolicy::scratch(scratchRead,scratchWrite,[](unsigned us){IODelay(us);});if(stage)break;
  b5q_usb_repeater_host(); // Optional repeater failure is logged; host preparation continues.
  auto snapshot=[&](const char *phase) {
   uint32_t v[11]={};const unsigned offsets[]={0xc120,0xc110,0xc704,0xc70c,0xc200,0xc2c0,0,0x10};
   for(unsigned i=0;i<8;++i)readReg(core.va,kUsbCoreBytes,offsets[i],v[i]);
   for(unsigned i=0;i<3;++i)readReg(qScratch.va,0x1000,i==0?0x808:i==1?0x810:0x830,v[8+i]);
   IOLog("B5qUsb: %s gsnpsid=%08x gctl=%08x dctl=%08x dsts=%08x gusb2phycfg=%08x gusb3pipectl=%08x cap=%08x hccparams1=%08x qscratch_cfg=%08x qscratch_hs=%08x qscratch_ss=%08x\n",phase,v[0],v[1],v[2],v[3],v[4],v[5],v[6],v[7],v[8],v[9],v[10]);
  };
  snapshot("before-prepare");
  stage="prepare-host";
  auto read=[&](uint32_t off,uint32_t &v){return readReg(core.va,kUsbCoreBytes,off,v);};
  auto write=[&](uint32_t off,uint32_t v){return writeReg(core.va,kUsbCoreBytes,off,v);};
  stage=B5qUsbPolicy::prepare(read,write,[](unsigned us){IODelay(us);});snapshot("after-prepare");if(stage)break;
  const char *families[]={"com.apple.iokit.IOUSBHostFamily","com.apple.driver.usb.AppleUSBXHCI"};
  bool familiesLoaded=true;
  for(const char *family:families) {
   stage=family;OSReturn status=OSKextLoadKextWithIdentifier(family);
   if(status!=kOSReturnSuccess) { IOLog("B5qUsb: stage=%s load=%08x\n",family,status);familiesLoaded=false;break; }
  }
  if(!familiesLoaded)break;
  stage="metaclasses";void *handle=OSMetaClass::preModLoad(g_kernel_kmod_info.name);if(!handle)break;
  b5q_usb_static_init();if(OSMetaClass::postModLoad(handle))break;
  stage="provider";nub=OSTypeAlloc(B5qUsbNub);
  OSSafeReleaseNULL(memory);memory=IODeviceMemory::withRange(B5qHardware::usbBase,0x8000);
  ranges=memory?OSArray::withObjects((const OSObject**)&memory,1):nullptr;
  if(!nub || !nub->init() || !ranges)break;
  OSData *bus=OSData::withBytes("\0\0\0\0",4);
  bool properties=bus && nub->setProperty("bus-number",bus);OSSafeReleaseNULL(bus);if(!properties)break;
  nub->setName("b5q-usb-host0");nub->setDeviceMemory(ranges);
  if(!(attached=nub->attach(IOService::getPlatform())))break;
  stage="start-AppleUSBXHCI";host=OSTypeAlloc(B5qUsbHost);
  if(!host || !host->init() || !(hostAttached=host->attach(nub)))break;
  // start may allocate DMA rings before returning false. Pin both objects in
  // that case; no shared-context reset or release of live DMA storage.
  nub->registerService();
  startAttempted=true;
  if(!host->start(nub)){host->retain();nub->retain();break;}
  host->registerService();host->retain();nub->retain();
  b5q_usb_state=1;stage="host-started";
  OSKextLoadKextWithIdentifier("com.apple.driver.usb.AppleUSBHub");
  OSKextLoadKextWithIdentifier("com.apple.driver.usb.AppleUSBHostCompositeDevice");
  OSKextLoadKextWithIdentifier("com.apple.driver.AppleHIDKeyboard");
  OSReturn hid=OSKextLoadKextWithIdentifier("com.apple.driver.usb.IOUSBHostHIDDevice");
  IOLog("B5qUsb: stage=%s base=0x%llx irq=%llu HID-load=0x%x\n",stage,B5qHardware::usbBase,B5qHardware::usbIrq,hid);
  Mapping *monitorMapping=new Mapping;
  if(monitorMapping && monitorMapping->open(B5qHardware::usbBase,kUsbCoreBytes)) {
   thread_t monitorThread=nullptr;
   if(kernel_thread_start(monitor,monitorMapping,&monitorThread)==KERN_SUCCESS) {
    thread_deallocate(monitorThread);monitorMapping=nullptr;
   }
  }
  delete monitorMapping;
 }while(false);
 if(b5q_usb_state!=1) {
  if(hostAttached && !startAttempted)host->detach(nub);
  if(attached && !startAttempted)nub->detach(IOService::getPlatform());
  b5q_usb_state=-1;
  IOLog("B5qUsb: stage=%s base=0x%llx SID=0x%llx; USB stopped; UFS and apps_smmu unchanged\n",stage,B5qHardware::usbBase,B5qHardware::usbSid);
 }
 OSSafeReleaseNULL(host);OSSafeReleaseNULL(nub);OSSafeReleaseNULL(ranges);OSSafeReleaseNULL(memory);
 thread_terminate(current_thread());
}
}
extern "C" void b5q_usb_start(void) {
 unsigned enabled=0;if(!PE_parse_boot_argn("b5q-usb",&enabled,sizeof(enabled)) || enabled!=1)return;
 static uint32_t once=0;if(__atomic_exchange_n(&once,1U,__ATOMIC_ACQ_REL))return;
 thread_t thread=nullptr;
 if(kernel_thread_start(worker,nullptr,&thread)==KERN_SUCCESS)thread_deallocate(thread);
 else {b5q_usb_state=-2;IOLog("B5qUsb: stage=thread-allocation\n");}
}
