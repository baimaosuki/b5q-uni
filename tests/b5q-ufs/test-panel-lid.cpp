/* SPDX-License-Identifier: GPL-2.0-only */
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <map>
#include <vector>
#include "B5qPanelCommand.h"
#include "B5qPanelLevels.h"
using namespace B5qPanelCommand;
struct Dsi {
    std::map<uint32_t,uint32_t> regs{{control,5},{dmaControl,0xc4000021},
        {length,56},{interrupts,0x02220202}};
    std::vector<uint32_t> payload;
    unsigned elapsed=0,mode=0;
    bool active=false;
    uint32_t read(uint32_t reg) {
        if(reg==interrupts && active && elapsed>=20) {
            if(mode==0)regs[reg]|=done;
            if(mode==1)regs[reg]|=error;
        }
        return regs[reg];
    }
    void write(uint32_t reg,uint32_t value) {
        if(reg==interrupts){regs[reg]=(regs[reg]&~(value&(done|error)))|(value&~(done|error));return;}
        if(reg==fifo)payload.push_back(value);
        if(reg==trigger){assert(regs[pattern]==0x30006&&regs[length]==8);active=true;}
        if(reg==fifoReset&&value)active=false;
        regs[reg]=value;
    }
    Result send(unsigned level) {
        return brightness([&](uint32_t r){return read(r);},
            [&](uint32_t r,uint32_t v){write(r,v);},[&](unsigned us){elapsed+=us;},level);
    }
};
int main() {
    assert(B5qPanelLevels::forNits(0)==0&&B5qPanelLevels::forNits(-1)==0);
    assert(B5qPanelLevels::forNits(1)==1);
    for(unsigned nits=1;nits<=600;++nits) {
        const unsigned level=B5qPanelLevels::forNits(int32_t(nits<<16));
        assert(level>=1&&level<=256);
        assert(B5qPanelLevels::normal[level-1].raw<=2047);
        if(nits<=500)assert(B5qPanelLevels::normal[level-1].nits>=nits);
        else assert(level==256);
    }
    for(unsigned level=0;level<=4095;level++) {
        Dsi d;const auto before=d.regs;
        assert(d.send(level)==Result::Ok);
        assert(d.payload.size()==2&&d.payload[0]==0xc0390003);
        assert(d.payload[1]==(0xff000051u|((level>>8)<<8)|((level&255)<<16)));
        assert(d.regs[dmaControl]==before.at(dmaControl)&&d.regs[length]==before.at(length));
        assert(!d.regs[pattern]&&!d.regs[fifoReset]&&!(d.regs[interrupts]&done));
        assert((d.regs[interrupts]&0x02220202)==0x02220202&&d.elapsed<=5001);
    }
    for(unsigned mode:{1u,2u}) {
        Dsi d;d.mode=mode;
        assert(d.send(1800)==(mode==1?Result::Error:Result::Timeout));
        assert(d.regs[dmaControl]==0xc4000021&&d.regs[length]==56);
        assert(!d.regs[pattern]&&!d.regs[fifoReset]&&d.elapsed<=5001);
    }
    Dsi range;assert(range.send(4096)==Result::Range&&range.payload.empty());
    Dsi off;off.regs[control]=0;assert(off.send(1)==Result::Off&&off.payload.empty());
    Dsi busy;busy.regs[pattern]=1;assert(busy.send(1)==Result::Busy&&busy.payload.empty());
    Dsi mdp;mdp.regs[B5qPanelCommand::status]=4;
    const auto saved=mdp.regs;assert(mdp.send(1)==Result::Busy&&mdp.payload.empty()&&mdp.regs==saved);
    Dsi error;error.regs[interrupts]|=B5qPanelCommand::error;
    assert(error.send(1)==Result::Error&&error.payload.empty());
    puts("PASS 4096 Samsung DCS FIFO levels, completion/error/timeout/restoration and no-write rejects; no lid controller selected");
}
