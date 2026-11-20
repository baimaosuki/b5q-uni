// SPDX-License-Identifier: BSD-2-Clause-Patent
// b5q warm host path. The original AppleUSBXHCI owns rings and USB/HID.
// No Xiaomi rails/retimer/UCSI/GPIO and no apps_smmu register access.
#include "OriginalUsbXhciABI.h"
#include "B5qUsbPolicy.h"
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceMemory.h>
#include <IOKit/IOPlatformExpert.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <libkern/OSKextLib.h>
#include <kern/thread.h>
#include <pexpert/pexpert.h>
#include <pexpert/arm/boot.h>
extern kmod_info_t g_kernel_kmod_info;
extern "C" {
int armcpu_spi_attach(uint32_t,bool,void(*)(void*),void*,uint32_t*,uint64_t*);
int armcpu_spi_mask(uint32_t,bool);
void b5q_usb_static_init(void) __asm__("__GLOBAL__sub_I_B5qUsbHost.cpp");
volatile int b5q_usb_state=0;
}
namespace {
void barrier(){__asm__ volatile("dsb sy" ::: "memory");}
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
 const char *stage="dma-handoff";IOMemoryMap *mapping=nullptr;B5qUsbNub *nub=nullptr;
 IODeviceMemory *memory=nullptr;OSArray *ranges=nullptr;B5qUsbHost *host=nullptr;
 bool attached=false,hostAttached=false;
 do {
  IORegistryEntry *chosen=IORegistryEntry::fromPath("/chosen",gIODTPlane);
  OSData *handoff=chosen?OSDynamicCast(OSData,chosen->getProperty("b5q-usb-handoff")):nullptr;
  auto *boot=static_cast<boot_args*>(PE_state.bootArgs);
  bool valid=boot && handoff && B5qUsbPolicy::accepts(handoff->getBytesNoCopy(),handoff->getLength(),boot->physBase,boot->memSize);
  OSSafeReleaseNULL(chosen);
  if(!valid)break;
  stage="load-AppleUSBXHCI";
  OSReturn loaded=OSKextLoadKextWithIdentifier("com.apple.driver.usb.AppleUSBXHCI");
  if(loaded!=kOSReturnSuccess && loaded!=kOSKextReturnStartStopError)break;
  stage="map-core";memory=IODeviceMemory::withRange(B5qHardware::usbBase,B5qHardware::usbBytes);
  mapping=memory?memory->map(kIOMapAnywhere|kIOMapInhibitCache):nullptr;if(!mapping)break;
  auto *reg=reinterpret_cast<volatile uint32_t*>(mapping->getVirtualAddress());
  auto read=[&](uint32_t off,uint32_t &v){if(off%4 || off>B5qHardware::usbBytes-4)return false;v=reg[off/4];return true;};
  auto write=[&](uint32_t off,uint32_t v){if(off%4 || off>B5qHardware::usbBytes-4)return false;reg[off/4]=v;barrier();return true;};
  stage=B5qUsbPolicy::prepare(read,write,[](unsigned us){IODelay(us);});if(stage)break;
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
  if(!host || !host->init() || !(hostAttached=host->attach(nub)) || !host->start(nub))break;
  host->registerService();nub->registerService();host->retain();nub->retain();
  b5q_usb_state=1;stage="host-started";
  OSReturn hid=OSKextLoadKextWithIdentifier("com.apple.driver.usb.IOUSBHostHIDDevice");
  IOLog("B5qUsb: stage=%s base=0x%llx irq=%llu HID-load=0x%x\n",stage,B5qHardware::usbBase,B5qHardware::usbIrq,hid);
 }while(false);
 if(b5q_usb_state!=1) {
  if(hostAttached)host->detach(nub);
  if(attached)nub->detach(IOService::getPlatform());
  b5q_usb_state=-1;
  IOLog("B5qUsb: stage=%s base=0x%llx SID=0x%llx; USB stopped; UFS and apps_smmu unchanged\n",stage,B5qHardware::usbBase,B5qHardware::usbSid);
 }
 OSSafeReleaseNULL(host);OSSafeReleaseNULL(nub);OSSafeReleaseNULL(ranges);OSSafeReleaseNULL(mapping);OSSafeReleaseNULL(memory);
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
