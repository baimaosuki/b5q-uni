// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>
namespace B5qTouchPointer {
struct Sample {
    int dx=0,dy=0,wheel=0,pan=0;
    unsigned buttons=0;
    bool click=false,rightClick=false,send=false;
};
// Tap on lift; double-tap-and-hold or stationary hold drags. Two fingers
// scroll by centroid, or right-click on lift. Every reset/lift sends release.
struct Pointer {
    int id=-1,second=-1,previousX=0,previousY=0,startX=0,startY=0;
    int residualX=0,residualY=0;
    uint64_t began=0,lastTap=0;
    unsigned mode=0,buttons=0;
    bool hasContact=false,moved=false,tapPending=false;
    static int coordinate(int v) {return v<0?0:v>32767?32767:v;}
    static int magnitude(int v) {return v<0?-v:v;}
    static int saturate(int v,int limit) {return v < -limit ? -limit : v>limit ? limit:v;}
    static int accelerated(int delta,int scale,int &fraction) {
        fraction+=delta*scale;
        int pixels=fraction/32767;fraction%=32767;
        int gain=magnitude(pixels)>32?3:magnitude(pixels)>12?2:1;
        return saturate(pixels*gain,32767);
    }
    Sample update(unsigned count,const int *ids,const int *xs,const int *ys,
                  uint64_t now,uint64_t tapLimit,bool recovered=false) {
        Sample result;
        if(recovered || count>10 || (count && (!ids || !xs || !ys))) {
            *this={};result.send=true;return result;
        }
        if(!count) {
            result.send=true;
            if(!hasContact)return result;
            if(hasContact && !moved && now>=began && now-began<=tapLimit && !buttons) {
                result.click=mode==1;result.rightClick=mode==2;
            }
            const bool tapped=result.click;
            *this={};tapPending=tapped;lastTap=now;
            return result;
        }
        if(count>2) {mode=3;hasContact=true;moved=true;buttons=0;result.send=true;return result;}
        if(mode==3)return result;
        int active=-1,other=-1;
        for(unsigned i=0;i<count;++i) {
            if(ids[i]==id)active=int(i);
            if(ids[i]==second)other=int(i);
        }
        if(!hasContact) {
            // All edges are valid; no dead margin.
            id=ids[0];hasContact=true;mode=count==2?2:1;second=count==2?ids[1]:-1;
            previousX=startX=coordinate(xs[0]);previousY=startY=coordinate(ys[0]);
            if(count==2) {
                previousX=startX=(previousX+coordinate(xs[1]))/2;
                previousY=startY=(previousY+coordinate(ys[1]))/2;
            }
            began=now;
            if(mode==1 && tapPending && now>=lastTap && now-lastTap<=tapLimit) {
                buttons=1;moved=true;result.buttons=1;result.send=true;
            }
            tapPending=false;return result;
        }
        if(mode==1 && count==2) {
            mode=2;second=ids[ids[0]==id?1:0];buttons=0;
            previousX=startX=(coordinate(xs[0])+coordinate(xs[1]))/2;
            previousY=startY=(coordinate(ys[0])+coordinate(ys[1]))/2;
            residualX=residualY=0;began=now;moved=false;result.send=true;return result;
        }
        if(active<0 || (mode==2 && (count!=2 || other<0))) {
            // Partial lift or changed identity cancels; never jumps/clicks.
            result.rightClick=mode==2 && count==1 && active>=0 && !moved &&
                              now>=began && now-began<=tapLimit;
            mode=3;buttons=0;moved=true;result.send=true;return result;
        }
        int x=coordinate(xs[active]),y=coordinate(ys[active]);
        if(mode==2) {x=(x+coordinate(xs[other]))/2;y=(y+coordinate(ys[other]))/2;}
        moved|=magnitude(x-startX)>600 || magnitude(y-startY)>600;
        if(mode==2) {
            residualX+=x-previousX;residualY+=y-previousY;
            if(moved) {
                result.pan=saturate(residualX/400,127);result.wheel=saturate(-residualY/400,127);
                residualX-=result.pan*400;residualY+=result.wheel*400;
            }
        } else {
            result.dx=accelerated(x-previousX,1080,residualX);result.dy=accelerated(y-previousY,2640,residualY);
            if(!moved && now>=began && now-began>tapLimit) {buttons=1;moved=true;result.send=true;}
        }
        previousX=x;previousY=y;result.buttons=buttons;
        result.send|=result.dx || result.dy || result.wheel || result.pan;
        return result;
    }
};
}
