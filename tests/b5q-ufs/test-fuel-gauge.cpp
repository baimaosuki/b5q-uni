#include "B5qFuelGauge.h"
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
int main() {
    using namespace B5qFuelGauge;
    for(unsigned raw=0;raw<=65535;raw++) {
        const uint32_t expected=(raw&0xfff)*78125u/1000000+
            ((((raw&0xf000)>>4)*78125u/1000000)<<4);
        assert(voltage(raw)==expected);
        const int64_t value=(raw&32768)?int64_t(raw)-65536:raw;
        assert(current(raw)==value*15625*5/100000);
    }
    Raw input{0,0x3280,0x1980,0xc800,0x100,0xff00,600,1200,1320,73};
    Sample s=decode(input);
    assert(s.present&&s.permille==505&&s.millivolts==4000);
    assert(s.temperatureDeciC==255&&s.milliamps==200&&s.averageMilliamps==-200);
    assert(s.remainingMah==1500&&s.fullMah==3000&&s.designMah==3300&&s.cycles==73);
    input.status=8;input.soc=0xffff;input.temperature=0xf580;s=decode(input);
    assert(!s.present&&s.permille==1000&&s.temperatureDeciC==-105);
    const uint16_t values[]={0,0x3280,0x1980,0xc800,0x100,0xff00,600,1200,1320,73};
    const uint8_t regs[]={0,6,8,9,10,11,5,16,24,23};
    for(unsigned fail=0;fail<=10;fail++) {
        Raw out=input;unsigned at=0;
        bool ok=read([&](uint8_t addr,uint8_t reg,uint16_t &value){
            assert(addr==0x36&&reg==regs[at]);value=values[at];return at++!=fail;
        },out);
        assert(ok==(fail==10));
        if(!ok)assert(!memcmp(&out,&input,sizeof(out)));
        else assert(decode(out).permille==505&&at==10);
    }
    Raw unchanged=input;
    assert(!read([](uint8_t,uint8_t,uint16_t &v){v=0xffff;return true;},unchanged));
    assert(!memcmp(&unchanged,&input,sizeof(input)));
    puts("PASS read-only original MAX77705 address/register order, all65536 voltage/current values, signed temperature, atomic sample and10read failures");
}
