/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#pragma once
#include <stdint.h>
namespace B5qLid {
// b5q hall_ic/flip: GPIO107, GPIO_ACTIVE_LOW, debounce-interval=50ms.
struct State {
    bool candidate=false,stable=false,observed=false,ready=false;
    uint64_t since=0;
    bool sample(bool high,uint64_t now) {
        const bool closed=!high;
        if(!observed || candidate!=closed || now<since) {
            observed=true;candidate=closed;since=now;return false;
        }
        if(now-since<50)return false;
        if(ready && stable==candidate)return false;
        ready=true;stable=candidate;return true;
    }
};
}
