/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceMemory.h>
#include <IOKit/IORegistryEntry.h>
#include <libkern/c++/OSData.h>
#include "B5qMediaDma.h"
extern const IORegistryPlane *gIODTPlane;
namespace {IOMemoryMap *retained;}
extern "C" bool b5q_audio_dma_buffer(uint8_t **cpu,uint64_t *physical,uint64_t *dsp){
    if(!cpu||!physical||!dsp||retained){IOLog("B5qAudio: stage=dma-arguments result=invalid retained=%u\n",retained!=nullptr);return false;}
    *cpu=nullptr;*physical=*dsp=0;
    uint32_t flag=0;B5qMediaDma::State s{};
    auto *chosen=IORegistryEntry::fromPath("/chosen",gIODTPlane);
    auto *ready=chosen?OSDynamicCast(OSData,chosen->getProperty("b5q-audio-dma-ready")):nullptr;
    auto *state=chosen?OSDynamicCast(OSData,chosen->getProperty("b5q-audio-dma-state")):nullptr;
    if(ready&&ready->getLength()==sizeof(flag))memcpy(&flag,ready->getBytesNoCopy(),sizeof(flag));
    if(state&&state->getLength()==sizeof(s))memcpy(&s,state->getBytesNoCopy(),sizeof(s));
    OSSafeReleaseNULL(chosen);
    IOLog("B5qAudio: DMA ready=%u HAL=%llx/%x/%x/%x/%x prepare=%llx retain=%llx\n",flag,s.locate,s.create,s.configure,s.attach[0],s.attach[1],s.prepareStatus,s.retentionStatus);
    if(!B5qMediaDma::ready(flag,s,B5qMediaDma::Kind::Audio))return false;
    auto *memory=IODeviceMemory::withRange(s.poolBase,s.poolBytes);
    auto *mapping=memory?memory->map(kIOMapAnywhere|kIOMapCopybackCache):nullptr;OSSafeReleaseNULL(memory);
    if(!mapping||!mapping->getVirtualAddress()){IOLog("B5qAudio: stage=dma-copyback-map base=%llx bytes=%llu result=failed\n",s.poolBase,s.poolBytes);OSSafeReleaseNULL(mapping);return false;}
    retained=mapping;*cpu=reinterpret_cast<uint8_t*>(mapping->getVirtualAddress());*physical=s.poolBase;
    // AudioReach's upper address word encodes stream-index1, not PA high bits.
    *dsp=s.iova|(1ULL<<32);memset(*cpu,0,65536);
    IOLog("B5qAudio: retained WBIS pool=%llu bytes DMA IOVA=%llx buffer=65536\n",s.poolBytes,*dsp);return true;
}
