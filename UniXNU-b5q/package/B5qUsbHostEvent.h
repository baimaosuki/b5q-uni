// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>

namespace B5qUsbHostEvent {

struct Event {
    uint64_t parameter;
    uint32_t status, control;
    unsigned completion, type, slot, endpoint, cycle;
};

struct Interrupter {uint32_t iman,erstsz;uint64_t erst,erdp;};
template<class Read32>
bool interrupter(unsigned runtime,unsigned index,unsigned windowBytes,Read32 read,Interrupter &out){
    if(index>1u||(runtime&31u)||windowBytes<0x40u+index*0x20u||
       runtime>windowBytes-(0x40u+index*0x20u))return false;
    const unsigned base=runtime+0x20u+index*0x20u;
    out={read(base),read(base+8)&65535u,
         uint64_t(read(base+0x10))|(uint64_t(read(base+0x14))<<32),
         uint64_t(read(base+0x18))|(uint64_t(read(base+0x1c))<<32)};
    return true;
}

struct TransferBases {
    uint64_t values[2]{};unsigned count=0;
    void observe(const Event &event){
        if(event.type!=32u||event.completion==1u)return;
        const uint64_t base=event.parameter&~0xffULL;
        if(!base)return;
        for(unsigned i=0;i<count;i++)if(values[i]==base)return;
        if(count<2)values[count++]=base;
    }
};
template<class Read,class Emit>
bool transfer(uint64_t base,Read read,Emit emit){
    if(!base||(base&255u)||base>UINT64_MAX-0x60u)return false;
    for(unsigned i=0;i<6;i++){
        uint64_t lo=0,hi=0;
        if(!read(base+16u*i,lo)||!read(base+16u*i+8u,hi))return false;
        emit(i,lo,hi);
    }
    return true;
}
struct Endpoint {uint64_t address=0,words[2]{};};
template<class Read>
bool endpoint(uint64_t dcbaa,unsigned stride,unsigned slot,unsigned dci,Read read,Endpoint &out){
    if(!dcbaa||(dcbaa&63u)||(stride!=32&&stride!=64)||!slot||slot>255||!dci||dci>31||dcbaa>UINT64_MAX-uint64_t(slot)*8u)return false;
    uint64_t context=0;
    if(!read(dcbaa+uint64_t(slot)*8,context)||!context||(context&63u)||context>UINT64_MAX-uint64_t(dci)*stride-16u)return false;
    out.address=context+uint64_t(dci)*stride;
    return read(out.address,out.words[0])&&read(out.address+8,out.words[1]);
}
template<class Read>
bool hubPortStatus(const Event &e,Read read,unsigned &port,uint32_t &status){
    // A successfully completed EP0 Status Stage identifies its preceding
    // Data and Setup TRBs. Never read a buffer from a pending/failed transfer.
    if(e.type!=32||e.completion!=1||e.slot!=1||e.endpoint!=1||(e.parameter&15u)||e.parameter<32||e.parameter>UINT64_MAX-8)return false;
    uint64_t ctl=0,data=0,dc=0,setup=0,sc=0;
    if(!read(e.parameter+8,ctl)||((ctl>>42)&63u)!=4u||
       !read(e.parameter-16,data)||!read(e.parameter-8,dc)||((dc>>42)&63u)!=3u||(uint32_t(dc)&0x1ffffu)!=4u||
       !read(e.parameter-32,setup)||!read(e.parameter-24,sc)||((sc>>42)&63u)!=2u||
       (setup&0xffffu)!=0x00a3u||(setup>>48)!=4u||!data||data>UINT64_MAX-8)return false;
    port=unsigned(setup>>32)&65535u;if(!port||port>255)return false;
    uint64_t value=0;if(!read(data,value))return false;status=uint32_t(value);return true;
}
struct Slot1 {uint64_t address=0,slot[2]{},ep0[2]{};};
template<class Read>
bool slot1(uint64_t dcbaa,unsigned stride,Read read,Slot1 &out){
    if(!dcbaa||(dcbaa&63u)||dcbaa>UINT64_MAX-16u||(stride!=32&&stride!=64))return false;
    if(!read(dcbaa+8,out.address)||!out.address||(out.address&63u)||
       out.address>UINT64_MAX-stride-16u)return false;
    return read(out.address,out.slot[0])&&read(out.address+8,out.slot[1])&&
           read(out.address+stride,out.ep0[0])&&read(out.address+stride+8,out.ep0[1]);
}

// Locate ERDP in one of the bounded ERST segments and visit the most recent
// entries preceding it. Read is the loader-qualified physical RAM reader.
template <class Read, class Emit>
bool latest(uint64_t table, unsigned tableEntries, uint64_t erdp,
            unsigned limit, Read read, Emit emit)
{
    constexpr unsigned maxTableEntries = 64;
    if (!table || (table & 63) || !tableEntries ||
        tableEntries > maxTableEntries || !limit) return false;
    const uint64_t pointer = erdp & ~15ULL;
    for (unsigned segment = 0; segment < tableEntries; ++segment) {
        if (table > UINT64_MAX - uint64_t(segment) * 16 - 16) return false;
        const uint64_t descriptor = table + uint64_t(segment) * 16;
        uint64_t baseWord = 0, sizeWord = 0;
        if (!read(descriptor, baseWord) || !read(descriptor + 8, sizeWord)) return false;
        const uint64_t base = baseWord & ~63ULL;
        const unsigned entries = uint32_t(sizeWord) & 0xffffu;
        if (!base || entries < 16 || entries > 65536) continue;
        const uint64_t bytes = uint64_t(entries) * 16;
        if (base > UINT64_MAX - bytes || pointer < base || pointer >= base + bytes ||
            ((pointer - base) & 15)) continue;
        const unsigned current = unsigned((pointer - base) / 16);
        const unsigned count = limit < entries ? limit : entries;
        for (unsigned back = 1; back <= count; ++back) {
            const unsigned index = (current + entries - back) % entries;
            uint64_t parameter = 0, words = 0;
            if (!read(base + uint64_t(index) * 16, parameter) ||
                !read(base + uint64_t(index) * 16 + 8, words)) return false;
            const uint32_t status = uint32_t(words), control = uint32_t(words >> 32);
            emit(segment,index,Event{parameter,status,control,status >> 24,
                (control >> 10) & 63u,(control >> 24) & 255u,
                (control >> 16) & 31u,control & 1u});
        }
        return true;
    }
    return false;
}

} // namespace B5qUsbHostEvent
