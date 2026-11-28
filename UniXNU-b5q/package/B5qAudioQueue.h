/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#pragma once
#include <stdint.h>
namespace B5qAudio {
// Ownership of each DSP period. A duplicate/late completion cannot retire
// a different period or make its DMA buffer writable while still in flight.
struct Queue {
    static constexpr unsigned slots=8;
    struct Entry {uint32_t token=0;bool pending=false;} entry[slots]{};
    uint32_t nextToken=0,handle=0,periodBytes=0;uint64_t base=0;
    unsigned pending=0;bool valid=false;
    bool init(uint64_t address,uint32_t map,uint32_t period) {
        valid=false;
        if(!map||!period||period>65536/slots||address>UINT64_MAX-uint64_t(period)*slots)return false;
        base=address;handle=map;periodBytes=period;pending=0;
        for(auto &e:entry)e.pending=false;
        valid=true;return true;
    }
    bool reserve(unsigned slot,uint32_t &token) {
        if(!valid||slot>=slots||entry[slot].pending||pending==slots)return false;
        if(!++nextToken)++nextToken;
        entry[slot]={nextToken,true};token=nextToken;++pending;return true;
    }
    bool cancel(unsigned slot,uint32_t token) {
        if(!valid||slot>=slots||!entry[slot].pending||entry[slot].token!=token)return false;
        entry[slot].pending=false;--pending;return true;
    }
    bool complete(uint64_t address,uint32_t map,uint32_t token) {
        if(!valid||map!=handle||address<base||address-base>=uint64_t(periodBytes)*slots||
            (address-base)%periodBytes)return false;
        return cancel(unsigned((address-base)/periodBytes),token);
    }
};
}
