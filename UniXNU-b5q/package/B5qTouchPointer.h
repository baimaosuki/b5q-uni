// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>

namespace B5qTouchPointer {
// Use a short stationary contact as a click. Release cancels a gesture that
// gained another finger, lost its original identifier, or suffered a read error.
struct Sample {
    int dx=0,dy=0;
    bool click=false;
};
struct Pointer {
    int id=-1, previousX=0, previousY=0, startX=0, startY=0, residualX=0,residualY=0;
    uint64_t began=0;
    bool hasContact=false, cancelled=false, moved=false;

    Sample update(unsigned count, const int *ids, const int *xs, const int *ys,
                  uint64_t now, uint64_t tapLimit, bool recovered=false) {
        if(!count) {
            const bool click=hasContact && !cancelled && !moved && !recovered && now-began<=tapLimit;
            *this={};
            return {0,0,click};
        }
        if(count!=1 || (hasContact && ids[0]!=id)) {
            cancelled=true;
            return {};
        }
        if(cancelled)return {};
        if(!hasContact) {
            hasContact=true;
            id=ids[0];
            previousX=startX=xs[0];
            previousY=startY=ys[0];
            began=now;
            return {};
        }
        const int travelX=xs[0]-startX,travelY=ys[0]-startY;
        moved |= travelX < -144 || travelX > 144 || travelY < -144 || travelY > 144;
        // Scale to the internal panel and preserve subpixel deltas.
        residualX+=(xs[0]-previousX)*1080;
        residualY+=(ys[0]-previousY)*2640;
        previousX=xs[0];
        previousY=ys[0];
        const int dx=residualX/32767,dy=residualY/32767;
        residualX%=32767;
        residualY%=32767;
        return {dx,dy,false};
    }
};
}
