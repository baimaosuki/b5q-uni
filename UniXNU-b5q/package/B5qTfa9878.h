/* SPDX-License-Identifier: GPL-2.0-only */
#pragma once
#include "B5qTfaContainer.h"
namespace B5qTfa {
// TFA9878 is DSP-free (Samsung tfa_set_query_info, rev78). The original
// default physical-device profiles carry only register settings. Firmware
// calibration/MTP programming and pseudo-device DSP messages are not issued.
// IO returns true only after an actual completed register transaction.
template<class IO> class Amplifier {
    IO &io;uint8_t address_;bool prepared_=false,running_=false;uint16_t revision_=0;
    bool field(uint8_t reg,uint16_t mask,uint16_t value) {
        uint16_t previous=0;return io.read(address_,reg,previous)&&
            io.write(address_,reg,uint16_t((previous&~mask)|(value&mask)));
    }
    bool put(uint8_t reg,uint16_t value){return io.write(address_,reg,value);}
    bool optimal() {
        // Original tfa9878_specific, generated version28/12. Key2 sequence
        // opens shadow registers; no nonvolatile copy/calibration command.
        uint16_t key=0;
        if(!put(0x0f,0x5a6b)||!io.read(address_,0xfb,key)||!put(0xa0,key^0x005a)||
            !put(0x0f,0x5a6b)||!put(0xa1,0x005a))return false;
        if(!put(0x01,0x2e18)||!put(0x02,0x0628)||!put(0x04,revision_==0x0a78?0x0240:0x0241)||
            !put(0x52,0x587c)||!put(0x61,0x0183)||!put(0x63,0x055a)||!put(0x65,0x0542))return false;
        if(revision_==0x1a78&&!put(0x70,0xb7ff))return false;
        if(!put(0x71,0x303e)||!put(0x83,0x009a))return false;
        if(revision_==0x1a78&&(!put(0x84,0x0211)||!put(0x8c,0x0210)||!put(0xce,0x2202)||!put(0xd5,0)))return false;
        // tfa_irq_init: disable, clear sticky status, then selected alarms.
        return put(0x48,0)&&put(0x44,0xffff)&&put(0x48,0x003c);
    }
public:
    enum class Error {None,InvalidProgram,Identity,Transfer,ClockTimeout,StateTimeout,NotPrepared};
    Error error=Error::None;uint16_t status=0,state=0;unsigned polls=0;
    Amplifier(IO &transport,uint8_t address):io(transport),address_(address){}
    uint16_t revision()const{return revision_;}
    bool prepared()const{return prepared_;}
    bool running()const{return running_;}
    // Called with TDM stopped and the other chip already quiescent. The plan
    // must have passed the original signed-file/CRC/container validation.
    bool prepare(const Program &program) {
        prepared_=running_=false;error=Error::None;polls=0;
        if((address_!=0x34&&address_!=0x35)||!program.count||program.count>96){error=Error::InvalidProgram;return false;}
        for(unsigned i=0;i<program.count;++i)
            if(program.updates[i].address!=address_){error=Error::InvalidProgram;return false;}
        if(!io.read(address_,3,revision_)||(revision_!=0x0a78&&revision_!=0x1a78)){error=Error::Identity;return false;}
        // Source tfa98xx_init writes I2CR directly (reg00bit1) before optimal.
        if(!put(0,2)||!optimal()) {error=Error::Transfer;quiesce();return false;}
        if(!apply(program,[&](uint8_t a,uint8_t r,uint16_t &v){return io.read(a,r,v);},
            [&](uint8_t a,uint8_t r,uint16_t v){return io.write(a,r,v);})){error=Error::Transfer;quiesce();return false;}
        if(!quiesce()){error=Error::Transfer;return false;}
        prepared_=true;return true;
    }
    // Source powerdown/AMPE workaround: always remove amp enable and power.
    // Cleanup attempts both writes even if one transaction fails.
    bool quiesce() {
        running_=false;
        const bool power=field(0,1,1),amp=field(0,8,0);
        return power&&amp;
    }
    bool start() {
        if(!prepared_){error=Error::NotPrepared;return false;}
        error=Error::None;polls=0;
        // tfa_dev_set_state INIT_CF then OPERATING for DSP-free probus:
        // MANSCONF -> PWDN clear -> waitCLKS -> AMPE, with bounded waits.
        if(!field(1,4,4)||!field(0,1,0)){error=Error::Transfer;quiesce();return false;}
        bool clock=false;
        for(unsigned i=0;i<50;++i){
            ++polls;
            if(!io.read(address_,0x10,status)){error=Error::Transfer;quiesce();return false;}
            if(status&0x40){clock=true;break;}io.delay(1000);
        }
        if(!clock){error=Error::ClockTimeout;quiesce();return false;}
        if(!field(0,8,8)){error=Error::Transfer;quiesce();return false;}
        for(unsigned i=0;i<50;++i){
            ++polls;
            if(!io.read(address_,0x14,state)){error=Error::Transfer;quiesce();return false;}
            // Original tfa_dev_get_state decodes MANSTATE9=OPERATING.
            if(((state>>3)&15)==9){running_=true;return true;}
            io.delay(1000);
        }
        error=Error::StateTimeout;quiesce();return false;
    }
};
}
