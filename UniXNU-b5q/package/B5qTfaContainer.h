/* SPDX-License-Identifier: GPL-2.0-only */
#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include "B5qUfs/B5qRootFormat.h"
namespace B5qTfa {
// The original Samsung PM3_01 container carries register-only amplifier
// profiles. Preserve device-list then selected-profile order, as
// tfa_cont_write_regs_dev/prof do. This parser performs no hardware access.
struct Update {uint8_t address,reg;uint16_t mask,value;};
struct Program {Update updates[96]{};unsigned count=0;};
struct Container {
    const uint8_t *data=nullptr;size_t bytes=0;
    static uint16_t le16(const uint8_t *p){return uint16_t(p[0])|(uint16_t(p[1])<<8);}
    bool span(uint32_t at,size_t n)const{return data&&at<=bytes&&n<=bytes-at;}
    bool pointer(uint32_t at,unsigned &kind,uint32_t &offset)const {
        if(!span(at,4))return false;const uint32_t word=B5qFormat::le32(data+at);
        kind=word>>24;offset=word&0xffffff;return offset<bytes;
    }
    bool text(uint32_t at,const char *expected)const {
        unsigned kind;uint32_t off;
        if(!expected||!pointer(at,kind,off)||kind!=3)return false;
        const size_t n=strlen(expected)+1;return span(off,n)&&!memcmp(data+off,expected,n);
    }
    bool init(const void *p,size_t n) {
        data=nullptr;bytes=0;if(!p||n<46||n>256*1024)return false;
        const auto *b=static_cast<const uint8_t*>(p);
        if(memcmp(b,"PM3_01",6)||B5qFormat::le32(b+6)!=n||
            B5qFormat::crc32(b+14,n-14)!=B5qFormat::le32(b+10))return false;
        const unsigned devices=le16(b+40);
        if(devices!=3||46u+devices*4>n)return false;
        data=b;bytes=n;return true;
    }
    bool append(uint32_t entry,uint8_t address,Program &p)const {
        unsigned kind;uint32_t off;if(!pointer(entry,kind,off))return false;
        if(kind!=16&&kind!=2)return false;
        if(p.count==sizeof(p.updates)/sizeof(p.updates[0]))return false;
        Update value{};value.address=address;
        if(kind==16) {
            if(!span(off,4))return false;
            const uint16_t field=le16(data+off+2),bits=uint16_t((field&15)+1),shift=uint16_t((field>>4)&15);
            const uint32_t raw=le16(data+off);
            if(bits+shift>16||raw>=(1u<<bits))return false;
            value.reg=uint8_t(field>>8);value.mask=uint16_t(((1u<<bits)-1)<<shift);
            value.value=uint16_t(raw<<shift);
        } else {
            if(!span(off,5))return false;value.reg=data[off];value.mask=le16(data+off+3);
            value.value=uint16_t(le16(data+off+1)&value.mask);
        }
        p.updates[p.count++]=value;return true;
    }
    bool program(uint8_t address,const char *profile,Program &out)const {
        out={};if(!data||(address!=0x34&&address!=0x35)||!profile)return false;
        uint32_t dev=0;bool found=false;
        for(unsigned i=0;i<le16(data+40);++i) {
            unsigned kind;uint32_t off;
            if(!pointer(46+4*i,kind,off)||kind!=0||!span(off,12))return false;
            if(data[off+2]!=address)continue;
            if(found||data[off+1]!=0||data[off+3]!=0)return false;dev=off;found=true;
        }
        if(!found||!span(dev+12,size_t(data[dev])*4))return false;
        // Preflight every selected descriptor before exposing the program.
        Program made{};bool registers=true;uint32_t selected=0;
        for(unsigned i=0;i<data[dev];++i) {
            unsigned kind;uint32_t off;const uint32_t at=dev+12+4*i;
            if(!pointer(at,kind,off))return false;
            if(kind==1) {
                registers=false;
                if(!span(off,8)||le16(data+off+2)!=0x1234||!data[off])return false;
                if(text(off+4,profile)){if(selected)return false;selected=off;}
            } else if(kind==4||kind==5)registers=false;
            else if(registers&&(kind==16||kind==2)) {if(!append(at,address,made))return false;}
            // dsc_last is Samsung's "sysfs" trailer, not a register write.
            else if(registers&&kind!=29)return false;
        }
        if(!selected)return false;
        const unsigned entries=unsigned(data[selected])-1;
        if(!span(selected+8,size_t(entries)*4))return false;
        bool end=false;
        for(unsigned i=0;i<entries;++i) {
            unsigned kind;uint32_t off;const uint32_t at=selected+8+4*i;
            if(!pointer(at,kind,off))return false;
            if(kind==17){end=true;break;}
            if(!append(at,address,made))return false;
        }
        if(!end||!made.count)return false;
        out=made;return true;
    }
};
template<class Read,class Write> bool apply(const Program &p,Read read,Write write) {
    for(unsigned i=0;i<p.count;++i) {
        const Update &u=p.updates[i];uint16_t before;
        if(!read(u.address,u.reg,before)||!write(u.address,u.reg,uint16_t((before&~u.mask)|u.value)))return false;
    }
    return true;
}
}
