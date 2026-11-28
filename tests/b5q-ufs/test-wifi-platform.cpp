#include <cassert>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include "B5qWifiArena.h"
#include "B5qWifiDma.h"
#include "B5qWifiFirmwareName.h"
#include "B5qPcieInputs.h"
int main() {
    char name[64];unsigned cases=0;
    for(unsigned chip: {0u,16u})for(unsigned board: {0u,1u,254u,255u,256u,65535u})for(unsigned antenna: {0u,1u,2u,10u}) {
        assert(b5q_wifi_bdf_name(name,sizeof(name),chip,board,antenna));
        assert(b5q_wifi_firmware_name(name));cases++;
    }
    for(const char *bad: {"bdwlan","bdwlan.","bdwlan.e","bdwlan.eff","bdwlan00.e01","bdwlan01.elf","bdwlang01.e02","bdwlan.elf11","../m3.bin","/amss.bin","qca/m3.bin","board-2.bin","wlan_mac.bin","bdwlan.e0011"})assert(!b5q_wifi_firmware_name(bad));
    assert(!b5q_wifi_bdf_name(name,sizeof(name),0,0x10000,0));
    assert(!b5q_wifi_bdf_name(name,sizeof(name),0,1,3));
    B5qWifi::Arena<4096> arena;
    auto *memory=static_cast<uint8_t*>(malloc(64*1024*1024));assert(memory);
    assert(arena.init(memory,0xa0000000,64*1024*1024));
    uint64_t bus=0;assert(!arena.allocate(SIZE_MAX,&bus));assert(!arena.allocate(0,&bus));
    void *p=arena.allocate(17,&bus);assert(p && !(bus&63));
    assert(arena.map(p,64)==bus && !arena.map(p,65));
    assert(!arena.release(static_cast<uint8_t*>(p)+1));assert(arena.release(p));assert(!arena.release(p));assert(!arena.map(p,1));
    void *allocations[2048];unsigned count=0;
    for(;count<2048;count++) {
        size_t bytes=(count%23+1)*4096;allocations[count]=arena.allocate(bytes,&bus);
        if(!allocations[count])break;
        uint64_t align=4096;while(align<bytes)align<<=1;assert(!(bus&(align-1)));
        assert(arena.map(allocations[count],bytes)==bus);
        assert(!arena.map(static_cast<uint8_t*>(allocations[count])+bytes-1,SIZE_MAX));
    }
    assert(count>100);
    for(unsigned i=0;i<count;i+=2)assert(arena.release(allocations[i]));
    for(unsigned i=1;i<count;i+=2)assert(arena.release(allocations[i]));
    assert(arena.used==0 && arena.count==1);
    p=arena.allocate(64*1024*1024,&bus);assert(p==memory && bus==0xa0000000);assert(arena.release(p));free(memory);
    B5qWifiDma::State state{2,0x007f1400,0,0,0,0,0,0xc0000000,0x4000000,0xa0000000,0xffe00000,32*4096,0,0};
    assert(B5qWifiDma::ready(1,state));auto old=state;old.poolBytes=0x2000000;assert(!B5qWifiDma::ready(1,old));assert(!B5qWifiDma::ready(0,state));
    for(unsigned i=0;i<sizeof(state);i++) {
        auto bad=state;reinterpret_cast<uint8_t*>(&bad)[i]^=0x80;
        // Physical pool/table positions can vary inside their retained ranges.
        if(i>=32 && i<40)continue;if(i>=56 && i<64)continue;
        assert(!B5qWifiDma::ready(1,bad));
    }
    assert(B5qPcieInputs::phy[0].offset==0x240 && B5qPcieInputs::phy[0].value==3);
    printf("PASS production Wi-Fi names %u cases, allocator ownership/alignment/exhaustion/reuse, firmware DMA status/bounds, original PHY table\n",cases);
}
