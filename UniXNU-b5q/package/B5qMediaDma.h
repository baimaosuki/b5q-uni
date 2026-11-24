/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#pragma once
#include <stdint.h>
namespace B5qMediaDma {
enum class Kind:uint32_t { Audio=1,Video=2 };
struct State {
    uint32_t version,kind,sid[2];
    uint64_t locate;
    uint32_t create,configure,attach[2],map,reserved;
    uint64_t poolBase,poolBytes,iova,tableBase,tableBytes,prepareStatus,retentionStatus;
};
static_assert(sizeof(State)==104,"UEFI multimedia DMA wire record");
inline bool ready(uint32_t flag,const State &s,Kind kind) {
    const bool audio=kind==Kind::Audio;
    const uint64_t bytes=audio?0x200000:0x8000000;
    const uint64_t iova=audio?0xa0000000:0x40000000;
    if(flag!=1||s.version!=1||s.kind!=uint32_t(kind)||s.reserved||s.locate||s.create||
       s.configure||s.attach[0]||s.attach[1]||s.map||s.prepareStatus||s.retentionStatus)return false;
    if(s.sid[0]!=(audio?0x00801001u:0x1940u)||s.sid[1]!=(audio?0x1061u:0x1947u))return false;
    if(s.poolBytes!=bytes||s.iova!=iova||s.poolBase<0x80000000||
       s.poolBase>0x100000000ULL-bytes||(s.poolBase&0x1fffff))return false;
    if(s.tableBytes!=0x20000||!s.tableBase||(s.tableBase&4095)||
       s.tableBase>0x100000000ULL-s.tableBytes)return false;
    return s.tableBase+s.tableBytes<=s.poolBase||s.tableBase>=s.poolBase+s.poolBytes;
}
}
