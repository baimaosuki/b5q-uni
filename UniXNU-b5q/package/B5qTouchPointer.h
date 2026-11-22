// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>

namespace B5qTouchPointer {
// Keep one interior contact by identifier while ignoring grip contacts.
// A failed transfer cancels a tap; release of the tracked finger ends it even
// when grip contacts remain on the edges.
struct Sample {
    int dx=0,dy=0;
    bool click=false;
};
struct Pointer {
    int id=-1, previousX=0, previousY=0, startX=0, startY=0, residualX=0,residualY=0;
    uint64_t began=0;
    bool hasContact=false, moved=false;

    Sample update(unsigned count, const int *ids, const int *xs, const int *ys,
                  uint64_t now, uint64_t tapLimit, bool recovered=false) {
        if(recovered) {*this={};return {};}
        int active=-1;
        for(unsigned i=0;i<count;++i)if(hasContact && ids[i]==id){active=int(i);break;}
        if(hasContact && active<0) {
            const bool click=!moved && now-began<=tapLimit;
            *this={};
            return {0,0,click};
        }
        if(!hasContact) {
            // The observed grip contacts at 181/4095 and 3925/4095 lie in
            // these side margins. Never reject a tracked finger at an edge.
            for(unsigned i=0;i<count;++i)
                if(xs[i]>=2048 && xs[i]<=32767-2048){active=int(i);break;}
            if(active<0)return {};
            hasContact=true;
            id=ids[active];
            previousX=startX=xs[active];
            previousY=startY=ys[active];
            began=now;
            return {};
        }
        const int travelX=xs[active]-startX,travelY=ys[active]-startY;
        moved |= travelX < -600 || travelX > 600 || travelY < -600 || travelY > 600;
        // Scale to the internal panel and preserve subpixel deltas.
        residualX+=(xs[active]-previousX)*1080;
        residualY+=(ys[active]-previousY)*2640;
        previousX=xs[active];
        previousY=ys[active];
        const int dx=residualX/32767,dy=residualY/32767;
        residualX%=32767;
        residualY%=32767;
        return {dx,dy,false};
    }
};
}
