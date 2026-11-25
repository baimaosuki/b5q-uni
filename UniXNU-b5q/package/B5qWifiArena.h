/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#ifndef B5Q_WIFI_ARENA_H
#define B5Q_WIFI_ARENA_H
#include <stdint.h>
#include <stddef.h>
#include <string.h>
namespace B5qWifi {
// The mainline WifiProbe allocator, with explicit overflow/bounds checks.
// Its memory is supplied exclusively by the retained firmware domain.
template<unsigned Capacity> struct Arena {
    struct Block {uint32_t offset,bytes;bool used;};
    Block blocks[Capacity];unsigned count=0;uint8_t *base=nullptr;
    uint64_t iova=0;uint32_t bytes=0,used=0,peak=0,failures=0;
    bool init(void *p,uint64_t bus,uint32_t size) {
        if(!p || !size || size>0x4000000 || (size&4095) || (bus&0x3fffff))return false;
        base=static_cast<uint8_t*>(p);iova=bus;bytes=size;count=1;
        blocks[0]={0,size,false};used=peak=failures=0;return true;
    }
    void *allocate(size_t n,uint64_t *bus) {
        if(!base || !n || n>bytes){failures++;return nullptr;}
        uint32_t size=uint32_t((n+63)&~size_t(63));
        if(size>=4096)size=(size+4095)&~4095u;
        uint32_t alignment=64;
        if(size>=4096){alignment=4096;while(alignment<size)alignment<<=1;}
        for(unsigned i=0;i<count;i++) {
            Block whole=blocks[i];if(whole.used)continue;
            uint32_t start=(whole.offset+alignment-1)&~(alignment-1),pad=start-whole.offset;
            if(pad>whole.bytes || size>whole.bytes-pad)continue;
            bool tail=whole.bytes>pad+size;
            unsigned extra=(pad?1:0)+(tail?1:0);
            if(count+extra>Capacity)continue;
            memmove(blocks+i+extra,blocks+i,(count-i)*sizeof(Block));count+=extra;
            unsigned at=i;if(pad)blocks[at++]={whole.offset,pad,false};
            blocks[at]={start,size,true};
            if(tail)blocks[at+1]={start+size,whole.bytes-pad-size,false};
            used+=size;if(used>peak)peak=used;
            memset(base+start,0,size);if(bus)*bus=iova+start;return base+start;
        }
        failures++;return nullptr;
    }
    bool release(void *p) {
        uintptr_t value=reinterpret_cast<uintptr_t>(p),first=reinterpret_cast<uintptr_t>(base);
        if(!base || value<first || value-first>=bytes)return false;
        uint32_t offset=uint32_t(value-first);
        for(unsigned i=0;i<count;i++)if(blocks[i].offset==offset && blocks[i].used) {
            used-=blocks[i].bytes;blocks[i].used=false;
            if(i+1<count && !blocks[i+1].used) {
                blocks[i].bytes+=blocks[i+1].bytes;
                memmove(blocks+i+1,blocks+i+2,(count-i-2)*sizeof(Block));count--;
            }
            if(i && !blocks[i-1].used) {
                blocks[i-1].bytes+=blocks[i].bytes;
                memmove(blocks+i,blocks+i+1,(count-i-1)*sizeof(Block));count--;
            }
            return true;
        }
        return false;
    }
    uint64_t map(const void *p,size_t n)const {
        uintptr_t value=reinterpret_cast<uintptr_t>(p),first=reinterpret_cast<uintptr_t>(base);
        if(!base || !n || value<first || value-first>=bytes || n>bytes-(value-first))return 0;
        uint32_t offset=uint32_t(value-first);
        for(unsigned i=0;i<count;i++)if(blocks[i].used && offset>=blocks[i].offset &&
            offset-blocks[i].offset<blocks[i].bytes && n<=blocks[i].bytes-(offset-blocks[i].offset))return iova+offset;
        return 0;
    }
};
}
#endif
