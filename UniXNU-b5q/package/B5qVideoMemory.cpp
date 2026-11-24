/* SPDX-License-Identifier: GPL-2.0-only */
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceMemory.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <libkern/c++/OSData.h>
#include <sys/errno.h>
#include "B5qMediaDma.h"
#include "B5qMediaPool.h"
#include "B5qVideoMemory.h"
namespace {
using Pool=B5qMedia::Pool<2048>;
Pool *pool;
IOMemoryMap *poolMap;
void barrier(){__asm__ volatile("dsb sy":::"memory");}
bool copyBounds(const QcomIrisBuffer &b,uint64_t at,uint64_t length) {
    const uint64_t low=b.offset&4095;
    return b.memory&&b.cpu&&at<=b.clientBytes&&length<=b.clientBytes-at&&
        low<=b.bytes&&at<=b.bytes-low&&length<=b.bytes-low-at&&
        b.offset<=b.memory->getLength()&&length<=b.memory->getLength()-b.offset&&
        pool&&pool->contains(b.cpu,b.bytes);
}
}
bool b5q_video_memory_init() {
    if(pool)return true;
    uint32_t flag=0;B5qMediaDma::State s{};
    auto *chosen=IORegistryEntry::fromPath("/chosen",gIODTPlane);
    auto *ready=chosen?OSDynamicCast(OSData,chosen->getProperty("b5q-video-dma-ready")):nullptr;
    auto *state=chosen?OSDynamicCast(OSData,chosen->getProperty("b5q-video-dma-state")):nullptr;
    if(ready&&ready->getLength()==sizeof(flag))memcpy(&flag,ready->getBytesNoCopy(),sizeof(flag));
    if(state&&state->getLength()==sizeof(s))memcpy(&s,state->getBytesNoCopy(),sizeof(s));
    OSSafeReleaseNULL(chosen);
    IOLog("B5qVideo: DMA ready=%u HAL=%llx/%x/%x/%x/%x prepare=%llx retain=%llx\n",
        flag,s.locate,s.create,s.configure,s.attach[0],s.attach[1],s.prepareStatus,s.retentionStatus);
    if(!B5qMediaDma::ready(flag,s,B5qMediaDma::Kind::Video))return false;
    auto *memory=IODeviceMemory::withRange(s.poolBase,s.poolBytes);
    // Original b5q non_secure_cb and non_secure_pixel_cb are dma-coherent.
    // This is the sole CPU mapping of reserved WBIS memory, not XNU pages.
    auto *mapping=memory?memory->map(kIOMapAnywhere|kIOMapDefaultCache):nullptr;
    OSSafeReleaseNULL(memory);
    auto *made=IONewZero(Pool,1);
    if(!mapping||!made||!made->init(reinterpret_cast<void*>(mapping->getVirtualAddress()),s.iova,uint32_t(s.poolBytes))) {
        if(made)IODelete(made,Pool,1);OSSafeReleaseNULL(mapping);return false;
    }
    poolMap=mapping;pool=made;
    IOLog("B5qVideo: retained-pool bytes=%llu iova=%llx WBIS coherent=1\n",s.poolBytes,s.iova);
    return true;
}
uint32_t b5q_video_memory_used(){return pool?pool->used:0;}
int b5q_video_allocate(uint64_t bytes,uint32_t alignment,QcomIrisBuffer *b) {
    if(!b)return -EINVAL;*b={};
    uint32_t iova=0;void *cpu=pool?pool->allocate(bytes,alignment,&iova):nullptr;
    if(!cpu)return -ENOMEM;
    *b={nullptr,iova,0,(bytes+4095)&~uint64_t(4095),cpu,nullptr,bytes};barrier();return 0;
}
int b5q_video_map(IOMemoryDescriptor *memory,uint64_t offset,uint64_t bytes,QcomIrisBuffer *b) {
    if(!b)return -EINVAL;*b={};
    if(!memory||!bytes||offset>memory->getLength()||bytes>memory->getLength()-offset)return -EINVAL;
    if(bytes>0x8000000-(offset&4095))return -ENOMEM;
    const int error=b5q_video_allocate(bytes+(offset&4095),4096,b);if(error)return error;
    if(memory->prepare(kIODirectionInOut)!=kIOReturnSuccess){b5q_video_release(b);return -ENOMEM;}
    memory->retain();b->memory=memory;b->offset=offset;b->clientBytes=bytes;return 0;
}
void b5q_video_release(QcomIrisBuffer *b) {
    if(!b)return;
    if(b->cpu&&pool)pool->release(b->cpu);
    if(b->memory){b->memory->complete(kIODirectionInOut);b->memory->release();}*b={};
}
bool b5q_video_input(QcomIrisBuffer *b,uint64_t bytes) {
    if(!b||!copyBounds(*b,0,bytes))return false;
    // A reused bitstream slot is copied at every QBUF, not just at map time.
    if(b->memory->readBytes(b->offset,static_cast<uint8_t*>(b->cpu)+(b->offset&4095),bytes)!=bytes)return false;
    barrier();return true;
}
bool b5q_video_output(QcomIrisBuffer *b,uint64_t at,uint64_t bytes) {
    if(!b||!copyBounds(*b,at,bytes))return false;
    barrier();
    const void *data=static_cast<uint8_t*>(b->cpu)+(b->offset&4095)+at;
    if(b->memory->writeBytes(b->offset,data,bytes)!=bytes)return false;
    barrier();return true;
}
