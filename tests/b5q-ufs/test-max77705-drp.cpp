// SPDX-License-Identifier: BSD-2-Clause-Patent
#include "B5qMax77705.h"
#include <cassert>
#include <cstdio>
#include <vector>

struct Bus {
    struct Write {unsigned reg,value;};
    std::vector<Write> writes;
    unsigned polls=0, waits=0, replies=0;
    unsigned failWrite=0,failRead=0,readyAt=3,reply=0x5e;
    bool triggered=false,stale=true;
    bool read(uint8_t address,uint8_t reg,uint8_t &value) {
        assert(address==0x25);
        if(reg==failRead)return false;
        if(reg==2) {
            if(!triggered){value=stale?0x80:0;stale=false;}
            else {++polls;value=polls>=readyAt?0x80:0;}
        } else {assert(reg==0x51);++replies;value=uint8_t(reply);}
        return true;
    }
    bool write(uint8_t address,uint8_t reg,uint8_t value) {
        assert(address==0x25);
        writes.push_back({reg,value});
        if(reg==failWrite)return false;
        if(reg==0x41){assert(value==0);triggered=true;}
        return true;
    }
    auto run(uint8_t command=0x5e,uint8_t value=1) {
        return B5qMax77705::opcode(*this,command,value,[&](unsigned us){assert(us==1000);++waits;});
    }
};

int main() {
    Bus good;auto result=good.run();
    assert(result.ok&&result.reply==0x5e&&result.polls==3&&good.replies==1);
    assert(good.writes.size()==3);
    assert(good.writes[0].reg==0x21&&good.writes[0].value==0x5e);
    assert(good.writes[1].reg==0x22&&good.writes[1].value==1);
    assert(good.writes[2].reg==0x41&&good.writes[2].value==0);
    Bus swap;assert(!swap.run(0x37,4).ok&&swap.writes.empty());
    // A stale matching reply without a fresh APCMDRES event never succeeds.
    Bus timeout;timeout.readyAt=101;
    result=timeout.run();assert(!result.ok&&result.triggered&&result.polls==100&&timeout.replies==0);
    Bus wrong;wrong.reply=0x37;assert(!wrong.run().ok&&wrong.polls==100);
    for(unsigned reg=0x21;reg<=0x41;++reg) {
        if(reg!=0x21&&reg!=0x22&&reg!=0x41)continue;
        Bus failed;failed.failWrite=reg;result=failed.run();
        assert(!result.ok&&result.failedReg==reg&&!failed.triggered&&failed.writes.back().reg==reg);
    }
    for(unsigned reg:{2u,0x51u}) {
        Bus failed;failed.failRead=reg;result=failed.run();
        assert(!result.ok&&result.failedReg==reg);
    }
    for(auto command:{0u,0x35u,0x55u,0xffu}) {
        Bus rejected;assert(!rejected.run(command,0).ok&&rejected.writes.empty());
    }
    Bus invalid;assert(!invalid.run(0x5e,0).ok&&invalid.writes.empty());
    unsigned calls=0;
    Bus failedSequence;failedSequence.readyAt=101;
    assert(!B5qMax77705::drp(failedSequence,[](unsigned){},[&](const auto &r){assert(!r.ok);++calls;}));
    assert(calls==1); // Failed first command must not issue the role command.
    Bus single;calls=0;
    assert(B5qMax77705::drp(single,[](unsigned){},[&](const auto &r){assert(r.ok);++calls;}));
    assert(calls==1&&single.writes.size()==3&&single.writes[0].value==0x5e);
    puts("PASS MAX77705: only5e/01, three writes, no swap request; fresh completion, stale/wrong replies, timeouts and I2C failures");
}
