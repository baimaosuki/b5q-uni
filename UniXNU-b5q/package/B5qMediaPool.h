/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>
namespace B5qMedia {
// Extents in a firmware-retained pool. The device lock serializes all calls.
// Allocation metadata stays in XNU memory; no firmware table is ever changed.
template<unsigned Capacity> struct Pool {
    struct Extent {uint32_t offset,bytes;bool live;};
    Extent extents[Capacity]{};
    uint8_t *base=nullptr;
    uint32_t bytes=0,count=0,used=0,peak=0;
    uint64_t iova=0;
    bool init(void *address,uint64_t bus,uint32_t length) {
        if(base||!address||!length||(length&4095)||(bus&4095)||
           length>0x8000000||bus>0x100000000ULL-length)return false;
        base=static_cast<uint8_t*>(address);iova=bus;bytes=length;
        extents[0]={0,length,false};count=1;return true;
    }
    void *allocate(uint64_t requested,uint32_t alignment,uint32_t *bus) {
        if(!base||!bus||!requested||requested>bytes||alignment<4096||
           alignment>bytes||(alignment&(alignment-1))||(iova&(alignment-1)))return nullptr;
        const uint32_t size=uint32_t((requested+4095)&~uint64_t(4095));
        for(unsigned i=0;i<count;++i) {
            const Extent e=extents[i];if(e.live)continue;
            const uint32_t start=(e.offset+alignment-1)&~(alignment-1);
            const uint32_t pad=start-e.offset;
            if(pad>e.bytes||size>e.bytes-pad)continue;
            const uint32_t tail=e.bytes-pad-size;
            const unsigned extra=unsigned(pad!=0)+unsigned(tail!=0);
            if(extra>Capacity-count)continue;
            memmove(extents+i+extra,extents+i,(count-i)*sizeof(Extent));count+=extra;
            unsigned at=i;if(pad)extents[at++]={e.offset,pad,false};
            extents[at++]={start,size,true};if(tail)extents[at]={start+size,tail,false};
            used+=size;if(used>peak)peak=used;
            memset(base+start,0,size);*bus=uint32_t(iova+start);return base+start;
        }
        return nullptr;
    }
    bool contains(const void *address,uint64_t length)const {
        const uintptr_t value=reinterpret_cast<uintptr_t>(address),first=reinterpret_cast<uintptr_t>(base);
        if(!base||!length||value<first||value-first>=bytes||length>bytes-(value-first))return false;
        const uint32_t offset=uint32_t(value-first);
        for(unsigned i=0;i<count;++i) {
            const Extent &e=extents[i];
            if(e.live&&offset>=e.offset&&offset-e.offset<e.bytes&&length<=e.bytes-(offset-e.offset))return true;
        }
        return false;
    }
    bool release(void *address) {
        const uintptr_t value=reinterpret_cast<uintptr_t>(address),first=reinterpret_cast<uintptr_t>(base);
        if(!base||value<first||value-first>=bytes)return false;
        for(unsigned i=0;i<count;++i)if(extents[i].live&&extents[i].offset==value-first) {
            used-=extents[i].bytes;extents[i].live=false;
            if(i+1<count&&!extents[i+1].live) {
                extents[i].bytes+=extents[i+1].bytes;
                memmove(extents+i+1,extents+i+2,(count-i-2)*sizeof(Extent));--count;
            }
            if(i&&!extents[i-1].live) {
                extents[i-1].bytes+=extents[i].bytes;
                memmove(extents+i,extents+i+1,(count-i-1)*sizeof(Extent));--count;
            }
            return true;
        }
        return false;
    }
};
}
