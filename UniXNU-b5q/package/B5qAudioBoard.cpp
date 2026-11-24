/* SPDX-License-Identifier: GPL-2.0-only */
/* Samsung I2C18/TFA9878 speaker hardware. Original b5q pins/reset/clocks,
 * no CS35l43, no EL1 SMMU, no DMA, no nonvolatile amplifier calibration. */
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceMemory.h>
#include <sys/errno.h>
#include "GeniI2c.h"
#include "B5qQupClock.h"
#include "B5qTfa9878.h"
extern "C" bool sm8550_gcc_update32(volatile uint32_t *,uint32_t,uint32_t);
extern "C" int sheng_fw_open(const char *,void **,uint64_t *);
extern "C" int sheng_fw_read(void *,uint64_t,void *,size_t);
extern "C" void sheng_fw_close(void *);
namespace {
void barrier(){__asm__ volatile("dsb sy":::"memory");}
struct Window {
    IOMemoryMap *mapping=nullptr;volatile uint32_t *va=nullptr;
    bool open(uint64_t base,uint64_t bytes){
        auto *memory=IODeviceMemory::withRange(base,bytes);
        mapping=memory?memory->map(kIOMapAnywhere|kIOMapInhibitCache):nullptr;
        OSSafeReleaseNULL(memory);va=mapping?reinterpret_cast<volatile uint32_t*>(mapping->getVirtualAddress()):nullptr;return va;
    }
    ~Window(){OSSafeReleaseNULL(mapping);}
    Window()=default;Window(const Window&)=delete;Window&operator=(const Window&)=delete;
};
uint32_t readSe(void *ctx,uint32_t reg){return static_cast<volatile uint32_t*>(ctx)[reg/4];}
void writeSe(void *ctx,uint32_t reg,uint32_t value){static_cast<volatile uint32_t*>(ctx)[reg/4]=value;barrier();}
struct Transport {
    Window engine;GeniI2c bus{};IOLock *lock=nullptr;
    ~Transport(){if(lock)IOLockFree(lock);}
    bool finish(){
        for(unsigned phase=0;phase<3;++phase){
            for(unsigned tick=0;tick<2500;++tick){
                const int state=geni_i2c_poll(&bus);
                if(state==GeniDone)return true;if(state==GeniFailed)return false;IODelay(10);
            }
            if(geni_i2c_timeout(&bus)!=GeniPending)return false;
        }
        return false;
    }
    bool idle(){return !geni_i2c_busy(&bus)&&!(readSe(bus.io.ctx,GENI_STATUS)&GENI_STATUS_M_ACTIVE);}
    bool read(uint8_t address,uint8_t reg,uint16_t &value){
        for(unsigned attempt=0;attempt<3;++attempt){
            if(!idle())break;uint8_t bytes[2]{};bus.address=address;
            const bool ok=!geni_i2c_start_read_buffer(&bus,&reg,1,bytes,2)&&finish();
            if(ok){value=uint16_t(bytes[0])<<8|bytes[1];return true;}IODelay(500);
        }
        IOLog("B5qAudio: I2C18 read addr=%02x reg=%02x error=%u status=%08x ios=%08x\n",address,reg,bus.error,bus.error_status,readSe(bus.io.ctx,0x908));return false;
    }
    bool write(uint8_t address,uint8_t reg,uint16_t value){
        const uint8_t bytes[]={reg,uint8_t(value>>8),uint8_t(value)};
        for(unsigned attempt=0;attempt<3;++attempt){
            if(!idle())break;bus.address=address;
            if(!geni_i2c_start_write_bytes(&bus,bytes,sizeof bytes)&&finish())return true;IODelay(500);
        }
        IOLog("B5qAudio: I2C18 write addr=%02x reg=%02x error=%u status=%08x ios=%08x\n",address,reg,bus.error,bus.error_status,readSe(bus.io.ctx,0x908));return false;
    }
    void delay(unsigned us){IODelay(us);}
    bool open(){
        Window gcc,pins;
        if(!gcc.open(0x100000,0x53000)||!pins.open(0xf100000,0x82000))return false;
        // Samsung gcc-kalama.c: hub core52008bit8, S6bit16, CBCR170ac,
        // ordinary RCG170b0. This is hub SE6, distinct from USBQUP1SE6.
        if(!sm8550_gcc_update32(gcc.va+0x52008/4,0,(1u<<8)|(1u<<16)))return false;
        auto read=[&](unsigned off){return gcc.va[off/4];};
        auto write=[&](unsigned off,uint32_t v){gcc.va[off/4]=v;barrier();};
        const unsigned branches[]={0x23144u,0x170acu};
        for(unsigned off:branches){
            uint32_t last=0;const bool ok=B5qQupClock::branch(read,[](unsigned us){IODelay(us);},off,last);
            IOLog("B5qAudio: I2C18 branch=%x value=%08x ok=%u\n",off,last,ok);if(!ok)return false;
        }
        unsigned level=0;uint32_t dfs=0;
        if(!B5qQupClock::xo(read,write,[](unsigned us){IODelay(us);},0x170b0,level,dfs,false))return false;
        for(unsigned gpio=8;gpio<=9;++gpio){
            volatile uint32_t *cfg=pins.va+gpio*0x1000/4;
            *cfg=(*cfg&~0x3ffu)|(1u<<2)|3u;barrier();
            if((*cfg&0x3ffu)!=7u)return false;
        }
        if(!engine.open(0x998000,0x4000))return false;
        const GeniIo io={readSe,writeSe,const_cast<uint32_t*>(engine.va)};
        writeSe(io.ctx,GENI_CLK_SEL,level);
        if(readSe(io.ctx,GENI_CLK_SEL)!=level)return false;
        const int cold=geni_se_init(&io);uint32_t config=0;
        const int error=cold?cold:geni_i2c_prepare_hub_xo(&bus,&io,0x34,&config);
        IOLog("B5qAudio: I2C18 base=998000 gpio=8/9 cfg=%08x cold=%d error=%d ios=%08x\n",config,cold,error,readSe(io.ctx,0x908));
        if(error)return false;
        // b5q reset-gpio0, shared by34/35. No GPIO14/154 writes.
        pins.va[4/4]=0;barrier();pins.va[0]=(pins.va[0]&~0x3ffu)|(1u<<9);barrier();
        IOSleep(2);pins.va[4/4]=2;barrier();IOSleep(5);
        // PrimaryTDM pins126sck/129ws/127data0/128data1, function1,2mA.
        // Clocks are started by AudioReach's endpoint, never by guessing PLLs.
        for(unsigned gpio=126;gpio<=129;++gpio){
            volatile uint32_t *cfg=pins.va+gpio*0x1000/4;
            *cfg=(*cfg&~0x3ffu)|(1u<<2);barrier();
            if((*cfg&0x3ffu)!=4u)return false;
        }
        lock=IOLockAlloc();return lock;
    }
};
struct Speakers {
    Transport io;B5qTfa::Amplifier<Transport> bottom,top;
    Speakers():bottom(io,0x34),top(io,0x35){}
    bool stop(){const bool a=bottom.quiesce(),b=top.quiesce();return a&&b;}
};
Speakers *speakers=nullptr;
}
extern "C" bool b5q_audio_amps_prepare(){
    if(speakers)return speakers->bottom.prepared()&&speakers->top.prepared();
    void *file=nullptr;uint64_t bytes=0;
    const char *path="/private/var/ngpu/firmware/qcom/sm8550/b5q/tfa98xx.cnt";
    int error=sheng_fw_open(path,&file,&bytes);
    if(error){IOLog("B5qAudio: container open=%d\n",error);return false;}
    uint8_t *raw=bytes&&bytes<=256*1024?static_cast<uint8_t*>(IOMallocData(bytes)):nullptr;
    error=raw?sheng_fw_read(file,0,raw,bytes):ENOMEM;sheng_fw_close(file);
    B5qTfa::Container container;B5qTfa::Program bottom{},top{};
    const bool valid=!error&&container.init(raw,bytes)&&container.program(0x34,"default",bottom)&&container.program(0x35,"default",top);
    if(raw)IOFreeData(raw,bytes);
    if(!valid){IOLog("B5qAudio: container invalid error=%d\n",error);return false;}
    auto *made=new Speakers;
    if(!made||!made->io.open()){delete made;return false;}
    IOLockLock(made->io.lock);
    const bool ok=made->bottom.prepare(bottom)&&made->top.prepare(top);
    if(!ok)made->stop();
    IOLog("B5qAudio: amps prepare=%u bottom=%04x/%u top=%04x/%u profiles=%u/%u\n",ok,made->bottom.revision(),unsigned(made->bottom.error),made->top.revision(),unsigned(made->top.error),bottom.count,top.count);
    IOLockUnlock(made->io.lock);
    if(!ok){delete made;return false;}speakers=made;return true;
}
extern "C" bool b5q_audio_amps_start(){
    if(!speakers)return false;IOLockLock(speakers->io.lock);
    const bool ok=speakers->bottom.start()&&speakers->top.start();if(!ok)speakers->stop();
    IOLog("B5qAudio: amps start=%u bottom=%u/%04x top=%u/%04x\n",ok,unsigned(speakers->bottom.error),speakers->bottom.state,unsigned(speakers->top.error),speakers->top.state);
    IOLockUnlock(speakers->io.lock);return ok;
}
extern "C" bool b5q_audio_amps_stop(){
    if(!speakers)return true;IOLockLock(speakers->io.lock);const bool ok=speakers->stop();IOLockUnlock(speakers->io.lock);
    IOLog("B5qAudio: amps stop=%u\n",ok);return ok;
}
