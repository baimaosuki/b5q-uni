// SPDX-License-Identifier: BSD-2-Clause-Patent
// Retained original PMGR's unsupported base semantics and original nub.
// No virtual-machine declaration, forged latch state, PMGR MMIO or CPU-power backend.
#include <IOKit/IOService.h>
#include <IOKit/IOPlatformExpert.h>
#include <IOKit/IOLib.h>
#include <libkern/OSKextLib.h>
#include <libkern/c++/OSSymbol.h>
extern "C" {
void b5q_original_pmgr_construct(void *,const OSMetaClass *);
IOService *b5q_original_pmgr_factory(IORegistryEntry *,IOService *);
uint32_t b5q_original_pmgr_read(IOService *);
void b5q_original_pmgr_write(IOService *,uint32_t);
}
extern "C" void b5q_pmgr_start(void) {
 static bool done=false;if(done)return;done=true;
 OSReturn status=OSKextLoadKextWithIdentifier("com.apple.driver.ApplePMGR");if(status)panic("B5qPmgr: original family load %x",status);
 const OSSymbol *name=OSSymbol::withCString("ApplePMGR");const OSMetaClass *meta=name?OSMetaClass::getMetaClassWithName(name):nullptr;OSSafeReleaseNULL(name);
 if(!meta||meta->getClassSize()<sizeof(IOService)||meta->getClassSize()>2*1024*1024)panic("B5qPmgr: invalid exact original base storage");
 // The public original metaclass is abstract; this bridge invokes its original
 // base constructor explicitly. All pure operations remain original refusals.
 // Neither ApplePMGR::start nor any Apple hardware initialization is invoked.
 void *memory=OSObject::operator new(meta->getClassSize());if(!memory)panic("B5qPmgr: original provider allocation");
 bzero(memory,meta->getClassSize());b5q_original_pmgr_construct(memory,meta);auto *provider=static_cast<IOService*>(memory);
 if(!provider->IOService::init())panic("B5qPmgr: base service init");
 auto *description=new IORegistryEntry;if(!description||!description->init())panic("B5qPmgr: description");description->setName("b5q-original-pmgr-base");
 IOService *nub=b5q_original_pmgr_factory(description,provider);if(!nub||!nub->metaCast("ApplePMGRNub"))panic("B5qPmgr: original nub factory");
 if(b5q_original_pmgr_read(nub)!=0xffffffffU)panic("B5qPmgr: original unsupported read contract");
 // This is the actual original unsupported base write, statically verified RET.
 b5q_original_pmgr_write(nub,0xffffffffU);if(b5q_original_pmgr_read(nub)!=0xffffffffU)panic("B5qPmgr: unsupported write contract");
 IOService *platform=IOService::getPlatform();if(!platform||!provider->attach(platform)||!provider->IOService::start(platform)||!nub->attach(provider)||!nub->IOService::start(provider))panic("B5qPmgr: service attachment");
 nub->registerService(kIOServiceSynchronous);description->release();
 IOLog("B5qPmgr: original ApplePMGRNub published; base reports unsupported; no hardware power backend\n");
}
