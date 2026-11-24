/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include "B5qMediaDma.h"
using UINT8=uint8_t;using UINT32=uint32_t;using UINT64=uint64_t;using UINTN=size_t;
using BOOLEAN=bool;
#define STATIC static
#define TRUE true
#define FALSE false
#define B5Q_USB_DMA_H
#define B5Q_USB_DMA_BASE 0x80000000ULL
#define B5Q_USB_DMA_LIMIT 0x1000000000ULL
#include "PcieDmaTables.h"
uint64_t walk(const USB_DMA_TABLES &t,uint64_t iova,unsigned &shift) {
    uint64_t *page=t.Pages;
    for(int s=39;s>=12;s-=9) {
        const uint64_t e=page[(iova>>s)&511];if(!(e&1))return 0;
        if(s==12||(e&3)==1){shift=unsigned(s);return e;}
        assert((e&3)==3&&(e&USB_DMA_PA_MASK)>=t.PhysicalBase);
        const uint64_t at=(e&USB_DMA_PA_MASK)-t.PhysicalBase;
        assert(at<t.Used*4096);page=t.Pages+at/8;
    }
    assert(false);return 0;
}
int main() {
    using namespace B5qMediaDma;
    alignas(4096)uint64_t pages[32*512];
    for(Kind kind:{Kind::Audio,Kind::Video}) {
        const bool audio=kind==Kind::Audio;
        State s{};s.version=1;s.kind=uint32_t(kind);s.sid[0]=audio?0x00801001:0x1940;s.sid[1]=audio?0x1061:0x1947;
        s.poolBase=0xb0000000;s.poolBytes=audio?0x200000:0x8000000;s.iova=audio?0xa0000000:0x40000000;
        s.tableBase=0xffe00000;s.tableBytes=0x20000;
        assert(ready(1,s,kind)&&!ready(0,s,kind)&&!ready(2,s,kind));
        assert(!ready(1,s,audio?Kind::Video:Kind::Audio));
        for(unsigned byte=0;byte<sizeof(s);++byte) {
            State bad=s;reinterpret_cast<uint8_t*>(&bad)[byte]^=1;
            // A legal alternate aligned pool/table base is allowed. Every
            // status/identity/size/IOVA change must fail closed.
            if(byte<48||(byte>=56&&byte<72)||byte>=80)assert(!ready(1,bad,kind));
        }
        State bad=s;bad.tableBase=s.poolBase;assert(!ready(1,bad,kind));
        bad=s;bad.poolBase=~0ULL;assert(!ready(1,bad,kind));
        bad=s;bad.tableBase=~0ULL-4095;assert(!ready(1,bad,kind));
        memset(pages,0,sizeof(pages));USB_DMA_TABLES t{pages,s.tableBase,0,32};
        assert(B5qPcieMapPool(&t,s.iova,s.poolBase,s.poolBytes));
        for(uint64_t at=0;at<s.poolBytes;at+=4096) {
            unsigned shift=0;const uint64_t e=walk(t,s.iova+at,shift);
            assert(shift==21&&(e&0x708)==0x708&&(e&(3ULL<<53))==(3ULL<<53));
            assert((e&USB_DMA_PA_MASK)+((s.iova+at)&((1ULL<<shift)-1))==s.poolBase+at);
        }
        unsigned shift=0;assert(!walk(t,s.iova-4096,shift)&&!walk(t,s.iova+s.poolBytes,shift));
        assert(!walk(t,0x15000000,shift)&&!walk(t,0xae00000,shift));
        assert(!B5qPcieMapPool(&t,s.iova,s.poolBase,s.poolBytes));
    }
    puts("PASS media handoff identities/status/overflow/overlap; actual shared WBIS tables all33280pages, bounded audio/video pools and unmapped Display/apps_smmu");
}
