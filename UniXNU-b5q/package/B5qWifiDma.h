/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#ifndef B5Q_WIFI_DMA_H
#define B5Q_WIFI_DMA_H
#include <stdint.h>
namespace B5qWifiDma {
struct State {
    uint32_t version,sidMask;uint64_t locate;
    uint32_t create,configure,attach,map;
    uint64_t poolBase,poolBytes,iova,tableBase,tableBytes,prepareStatus,retentionStatus;
};
static_assert(sizeof(State)==88,"PCIe firmware wire ABI");
constexpr bool ready(uint32_t flag,const State &s) {
    return flag==1 && s.version==2 && s.sidMask==0x007f1400 && !s.locate &&
        !s.create && !s.configure && !s.attach && !s.map && !s.prepareStatus && !s.retentionStatus &&
        s.poolBytes==0x4000000 && s.poolBase>=0x80000000ULL && s.poolBase<=0xfc000000ULL &&
        !(s.poolBase&0x3fffff) && s.iova==0xa0000000 && s.tableBytes==32*4096 &&
        s.tableBase>=0x80000000ULL && s.tableBase<=0x100000000ULL-s.tableBytes && !(s.tableBase&4095) &&
        (s.tableBase+s.tableBytes<=s.poolBase || s.tableBase>=s.poolBase+s.poolBytes);
}
}
#endif
