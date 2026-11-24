/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#ifndef B5Q_PCIE_CORE_H
#define B5Q_PCIE_CORE_H
#include <stdint.h>
#include "B5qPcieInputs.h"
namespace B5qPcie {
// Common SM8550 controller recipe from mainline WifiProbe. Offsets and
// physical resources are checked against b5q DTS and Samsung gcc-kalama.
// Each wait is bounded; no access to controller/PHY precedes power+clocks.
template<class IO> int train(IO &io) {
    if(!io.power())return -9;
    io.pin(94,0x201,0);io.pin(95,7,-1);io.pin(96,3,-1);
    if(!io.radio(true))return -10;
    if(!io.gcc(0x52020,9,0))return -11;
    unsigned tries=0;
    while(tries++<100 && (!(io.readGcc(0x6b004)&(1u<<31)) || !(io.readGcc(0x6c000)&(1u<<31))))io.delay(10);
    if(!(io.readGcc(0x6b004)&(1u<<31)) || !(io.readGcc(0x6c000)&(1u<<31)))return -11;
    // CMD_UPDATE is a pulse: hardware clears it on a successful switch.
    // Never verify it with the persistent RMW/readback helper.
    if(!io.gcc(0x6b078,~0u,0) || !io.rcg(0x6b074) ||
       !io.gcc(0x6b05c,~0u,(6u<<8)|5) || !io.rcg(0x6b058))return -12;
    if(!io.gcc(0x6b070,3,2) || !io.gcc(0x52008,0,0x7f) ||
       !io.gcc(0x52000,0,(1u<<12)|(1u<<19)|(1u<<22)) || !io.clkref())return -12;
    io.delay(200);
    const uint32_t branches[]={0x6b020u,0x6b02cu,0x6b038u,0x6b03cu,0x6b01cu,0x10030u,0x1003cu,0x1004cu,0x6b054u};
    for(uint32_t reg: branches)
        if(io.readGcc(reg)&(1u<<31))return -12;
    const uint32_t resets[]={0x6b000u,0x6c01cu};
    for(uint32_t reg: resets) {
        if(!io.gcc(reg,0,1))return -12;io.delay(1000);
        if(!io.gcc(reg,1,0))return -12;io.delay(1000);
    }
    if(!io.openController())return -13;
    io.parf(0x1000,~0u,4);io.parf(0x40,1,0);
    io.parf(0x350,~0u,0x60000000);io.parf(0x354,~0u,0);
    io.parf(0x634,~0u,0x60001000);io.parf(0x638,~0u,0);
    io.parf(0x358,~0u,0);io.parf(0x35c,~0u,0x80000000);
    io.parf(0,(1u<<29),0);io.parf(0x174,0,1u<<4);
    io.parf(0x20,1u<<5,0);io.parf(0x1a8,0,1u<<31);
    if(!io.openPhy())return -14;
    for(const auto &entry:B5qPcieInputs::phy){io.phy(entry.offset,entry.value);if(entry.delayUs)io.delay(entry.delayUs);}
    if(!io.gcc(0x6b070,3,0))return -14;
    tries=0;while((io.readPhy(0x214)&0x40) && tries++<100)io.delay(100);
    if(io.readPhy(0x214)&0x40)return -14;
    // Requester-ID to SID translation is PCIe PARF, never SMMU MMIO.
    // qcom_pcie_config_sid_sm8250: BDF[31:16], offset[15:8], NEXT[7:0].
    // b5q iommu-map: RID0100 -> SID1401, base1400 => offset1.
    constexpr uint32_t endpointEntry=(0x0100u<<16)|(1u<<8);
    for(unsigned i=0;i<256;i++)io.parf(0x2000+4*i,~0u,0);
    io.parf(0x2c00,1,0);
    uint8_t crc=0;
    const unsigned requester[]={1,0};
    for(unsigned byte: requester){crc^=byte;for(unsigned bit=0;bit<8;bit++)crc=(crc&128)?uint8_t((crc<<1)^7):uint8_t(crc<<1);}
    io.parf(0x2000+4*crc,~0u,endpointEntry);
    io.dbi(0x18,~0u,0x00010100);io.dbi(4,0,6);
    io.delay(100000);io.pin(94,0x201,1);io.delay(1000);
    io.parf(0x1b0,0,1u<<8);
    tries=0;while(tries++<1000){if((io.readDbi(0x72c)&16) && (io.readDbi(0x728)&63)==0x11)return 0;io.delay(1000);}
    return -16;
}
}
#endif
