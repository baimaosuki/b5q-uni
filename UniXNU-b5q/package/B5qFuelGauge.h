/* SPDX-License-Identifier: GPL-2.0-only */
/* Read-only MAX77705 measurements, derived from Samsung max77705_fuelgauge.c
 * at 36ffdaa5a4e2bff6e66812b444874b0cb6133fa9 and b5q DTS fg_resistor=5.
 * No charging policy, calibration/reset or fuel-gauge writes belong here. */
#ifndef B5Q_FUEL_GAUGE_H
#define B5Q_FUEL_GAUGE_H
#include <stdint.h>
namespace B5qFuelGauge {
constexpr uint8_t address=0x36;
struct Raw {
    uint16_t status,soc,temperature,voltage,current,averageCurrent;
    uint16_t remaining,full,design,cycles;
};
struct Sample {
    bool present;
    uint32_t permille,millivolts,remainingMah,fullMah,designMah,cycles;
    int32_t milliamps,averageMilliamps,temperatureDeciC;
};
inline uint32_t voltage(uint16_t raw) {
    // Preserve Samsung's separate high/low integer calculation.
    return (uint32_t(raw&0xfff)*78125/1000000)+
        (((uint32_t(raw&0xf000)>>4)*78125/1000000)<<4);
}
inline int32_t current(uint16_t raw) {
    const int32_t value=(raw&0x8000)?int32_t(raw)-65536:int32_t(raw);
    return int32_t(int64_t(value)*15625*5/100000);
}
inline uint32_t capacity(uint16_t raw) {return uint32_t(raw)*5/2;}
inline Sample decode(const Raw &r) {
    Sample s{};s.present=!(r.status&8);
    uint32_t soc=((r.soc>>8)*100+(r.soc&255)*100/256)/10;
    s.permille=soc>1000?1000:soc;
    s.millivolts=voltage(r.voltage);s.milliamps=current(r.current);
    s.averageMilliamps=current(r.averageCurrent);
    const int32_t temp=(r.temperature&0x8000)?int32_t(r.temperature)-65536:int32_t(r.temperature);
    s.temperatureDeciC=temp*10/256;
    s.remainingMah=capacity(r.remaining);s.fullMah=capacity(r.full);s.designMah=capacity(r.design);
    s.cycles=r.cycles;return s;
}
template<class ReadWord> bool read(ReadWord reader,Raw &result) {
    Raw pending{};
    struct Field {uint8_t reg;uint16_t Raw::*member;};
    static constexpr Field fields[]={{0x00,&Raw::status},{0x06,&Raw::soc},
        {0x08,&Raw::temperature},{0x09,&Raw::voltage},{0x0a,&Raw::current},
        {0x0b,&Raw::averageCurrent},{0x05,&Raw::remaining},{0x10,&Raw::full},
        {0x18,&Raw::design},{0x17,&Raw::cycles}};
    for(const auto &f:fields)if(!reader(address,f.reg,pending.*f.member))return false;
    if(pending.status==0xffff || !pending.full || pending.full==0xffff ||
       !pending.design || pending.design==0xffff)return false;
    result=pending;return true;
}
}
#endif
