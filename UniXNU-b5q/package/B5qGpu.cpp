// SPDX-License-Identifier: BSD-2-Clause-Patent
// b5q firmware/GMU loading boundary. No Xiaomi power/vote/SMMU tables.
#include "B5qGmuLoad.h"
#include "NativeAdrenoSha256.h"
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IODeviceMemory.h>
#include <kern/thread.h>
#include <pexpert/pexpert.h>
extern "C" {volatile int b5q_gpu_state=0;}
namespace {
bool firmware(IORegistryEntry *chosen,const char *property,uint64_t bytes,const uint8_t hash[32],OSData *&out) {
 out=OSDynamicCast(OSData,chosen->getProperty(property));if(!out || out->getLength()!=bytes)return false;
 uint8_t actual[32];NativeAdrenoSha256::hash(static_cast<const uint8_t*>(out->getBytesNoCopy()),out->getLength(),actual);
 return !memcmp(hash,actual,32);
}
struct GmuHandoff {
 uint64_t magic;
 uint32_t version,sid,flags,reserved;
 uint64_t icachePhysical,icacheBytes,icacheIova;
};
static void worker(void *,wait_result_t) {
 const char *stage="firmware-inputs";IORegistryEntry *chosen=IORegistryEntry::fromPath("/chosen",gIODTPlane);
 IODeviceMemory *cacheMemory=nullptr,*registerMemory=nullptr;IOMemoryMap *cache=nullptr,*registers=nullptr;
 do {
  OSData *gmu=nullptr,*sqe=nullptr,*zap=nullptr;
  if(!chosen || !firmware(chosen,"b5q-gmu-fw",B5qHardware::gmuFirmwareBytes,B5qHardware::gmuFirmwareSha256,gmu) ||
     !firmware(chosen,"b5q-sqe-fw",B5qHardware::sqeFirmwareBytes,B5qHardware::sqeFirmwareSha256,sqe) ||
     !firmware(chosen,"b5q-zap-fw",B5qHardware::zapFirmwareBytes,B5qHardware::zapFirmwareSha256,zap))break;
  const auto *image=static_cast<const uint8_t*>(gmu->getBytesNoCopy());AdrenoFirmwareBlock plan[32];size_t count=0;
  stage="GMU-firmware-plan";if(!B5qGmu::plan(image,gmu->getLength(),plan,count))break;
  IOLog("B5qGpu: Samsung GMU/SQE/ZAP identity verified; GMU blocks=%lu GPU=0x%llx GMU=0x%llx SMMU=0x%llx\n",
        count,B5qHardware::gpuBase,B5qHardware::gmuBase,B5qHardware::gpuSmmuBase);
  b5q_gpu_state=1;stage="power-and-GMU-mapping-handoff";
  OSData *property=OSDynamicCast(OSData,chosen->getProperty("b5q-gmu-handoff"));GmuHandoff handoff={};
  if(!property || property->getLength()!=sizeof(handoff))break;
  memcpy(&handoff,property->getBytesNoCopy(),sizeof(handoff));
  // Firmware must own the reservation, establish this GMU stream and hold
  // the CM3 in reset while the loader writes code. No
  // source currently manufactures that evidence or changes the GPU SMMU.
  if(handoff.magic!=0x314d5547513542ULL || handoff.version!=1 || handoff.sid!=5 ||
     handoff.flags!=15 || handoff.reserved || !handoff.icachePhysical || handoff.icachePhysical%4096 ||
     handoff.icacheBytes!=0xffc000 || handoff.icacheIova!=0x4000 ||
     handoff.icacheBytes>UINT64_MAX-handoff.icachePhysical)break;
  stage="map-owned-GMU-windows";
  cacheMemory=IODeviceMemory::withRange(handoff.icachePhysical,handoff.icacheBytes);
  registerMemory=IODeviceMemory::withRange(B5qHardware::gmuBase,B5qHardware::gmuBytes);
  cache=cacheMemory?cacheMemory->map(kIOMapAnywhere):nullptr;
  registers=registerMemory?registerMemory->map(kIOMapAnywhere|kIOMapInhibitCache):nullptr;
  if(!cache || !registers)break;
  auto *cpu=reinterpret_cast<uint8_t*>(cache->getVirtualAddress());
  auto *mmio=reinterpret_cast<volatile uint32_t*>(registers->getVirtualAddress());
  stage="load-GMU-firmware";
  if(!B5qGmu::load(image,gmu->getLength(),handoff.icacheBytes,true,
    [&](uint32_t off,uint32_t value){if(off%4 || off>B5qHardware::gmuBytes-4)return false;mmio[off/4]=value;return true;},
    [&](uint32_t off,const uint8_t *data,uint32_t n){if(off>handoff.icacheBytes || n>handoff.icacheBytes-off)return false;memcpy(cpu+off,data,n);return true;},
    [&](){for(uint64_t at=0;at<handoff.icacheBytes;at+=64){uintptr_t p=reinterpret_cast<uintptr_t>(cpu+at);__asm__ volatile("dc cvac, %0"::"r"(p):"memory");}__asm__ volatile("dsb sy":::"memory");}))break;
  b5q_gpu_state=2;stage="GMU-firmware-loaded; HFI/power-votes/PAS-start-pending";
 }while(false);
 IOLog("B5qGpu: stage=%s state=%d; no Metal-ready service published\n",stage,b5q_gpu_state);
 OSSafeReleaseNULL(registers);OSSafeReleaseNULL(cache);OSSafeReleaseNULL(registerMemory);OSSafeReleaseNULL(cacheMemory);OSSafeReleaseNULL(chosen);
 thread_terminate(current_thread());
}
}
extern "C" void b5q_gpu_start(void) {
 unsigned enabled=0;if(!PE_parse_boot_argn("b5q-gpu",&enabled,sizeof(enabled)) || enabled!=1)return;
 static uint32_t once=0;if(__atomic_exchange_n(&once,1U,__ATOMIC_ACQ_REL))return;
 thread_t thread=nullptr;
 if(kernel_thread_start(worker,nullptr,&thread)==KERN_SUCCESS)thread_deallocate(thread);
 else {b5q_gpu_state=-1;IOLog("B5qGpu: stage=thread-allocation\n");}
}
