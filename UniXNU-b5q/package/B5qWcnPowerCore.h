/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#ifndef B5Q_WCN_POWER_CORE_H
#define B5Q_WCN_POWER_CORE_H
#include <stdint.h>
namespace B5qWcn {
// b5q.dts six BT logical supplies share four physical VRM resources.
// Wi-Fi AON adds smpg2; no Xiaomi smpg5/850mV or PMK8550 GPIO3.
struct Rail {const char *name;unsigned mv;};
constexpr Rail rails[]={{"ldob15",1800},{"smpe4",966},{"smpg6",1900},{"smpg4",1350},{"smpg2",1012}};
constexpr uint8_t masks[]={0x1f,0x0f};
struct Power {
    uint8_t owners=0,retained=0,refs[5]={};
    template<class Vote> bool get(unsigned radio,Vote vote) {
        if(radio>1)return false;
        if(owners&(1u<<radio))return true;
        for(unsigned i=0;i<5;i++)if(masks[radio]&(1u<<i)) {
            if(!refs[i] && !vote(i,rails[i]))return false;
            retained|=uint8_t(1u<<i);
        }
        owners|=uint8_t(1u<<radio);
        for(unsigned i=0;i<5;i++)if(masks[radio]&(1u<<i))refs[i]++;
        return true;
    }
    bool put(unsigned radio) {
        if(radio>1)return false;
        if(!(owners&(1u<<radio)))return true;
        owners&=uint8_t(~(1u<<radio));
        for(unsigned i=0;i<5;i++)if(masks[radio]&(1u<<i))refs[i]--;
        // Boot firmware/USB may hold these VRM rails without a WCN ownership
        // vote. Last put drops the radio's vote, never forces a global disable.
        // BT_EN/WLAN_EN isolate an off radio; retained documents the floor.
        return true;
    }
};
// btpower.c: XO high 100..200us before BT_EN, held 4..6ms after.
// Cold starts without WLAN discharge up to500ms. No temperature is fabricated.
template<class Read,class Pin,class Delay> bool enable(unsigned radio,bool on,
        Read read,Pin pin,Delay delay) {
    if(radio>1)return false;
    const unsigned own=radio?81:80,peer=radio?80:81;
    if(!on){pin(own,false);delay(100000);return !read(own);}
    pin(own,false);delay(50000);
    if(!read(peer))delay(500000);
    pin(204,true);delay(200);pin(own,true);delay(5000);pin(204,false);delay(50000);
    return read(own);
}
}
#endif
