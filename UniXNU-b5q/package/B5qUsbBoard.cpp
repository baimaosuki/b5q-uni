// SPDX-License-Identifier: BSD-2-Clause-Patent
// Samsung b5q PHY/Type-C interfaces consumed by the original QcomDwc3.
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceMemory.h>
#include "BootResetCore.h"
#include "GeniI2c.h"
#include "B5qUsbBoardCore.h"
#include "B5qMax77705.h"
#include "B5qQupClock.h"
extern "C" bool sm8550_gcc_update32(volatile uint32_t *,uint32_t,uint32_t);
namespace {
void barrier(){__asm__ volatile("dsb sy":::"memory");}
struct Map {
 IOMemoryMap *map=nullptr;volatile uint32_t *va=nullptr;
 bool open(uint64_t base,uint64_t bytes){auto *d=IODeviceMemory::withRange(base,bytes);map=d?d->map(kIOMapAnywhere|kIOMapInhibitCache):nullptr;OSSafeReleaseNULL(d);va=map?reinterpret_cast<volatile uint32_t*>(map->getVirtualAddress()):nullptr;return va;}
 ~Map(){OSSafeReleaseNULL(map);}
};
uint32_t seRead(void *ctx,uint32_t reg){return static_cast<volatile uint32_t*>(ctx)[reg/4];}
void seWrite(void *ctx,uint32_t reg,uint32_t value){static_cast<volatile uint32_t*>(ctx)[reg/4]=value;barrier();}
struct Bus {
 Map engine;GeniI2c bus={};IOLock *lock=nullptr;bool ready=false;
 bool open(bool hub){
  if(ready)return true;
  Map gcc,tlmm;
  if(!gcc.open(0x100000,0x1f0000)||!tlmm.open(0xf100000,0x100000))return false;
  const unsigned se=hub?8:6;
  auto read=[&](unsigned off){return gcc.va[off/4];};
  auto write=[&](unsigned off,uint32_t value){gcc.va[off/4]=value;barrier();};
  auto branch=[&](unsigned off){
   uint32_t last=0;const bool ok=B5qQupClock::branch(read,[](unsigned us){IODelay(us);},off,last);
   IOLog("qcom-dwc3: GENI SE%u branch=%08x cbcr=%08x hw_ctl=%u wait_skipped=%u ok=%u\n",se,off,last,!!(last&2u),!!(last&2u),ok);
   return ok;
  };
  if(hub){
   if(!sm8550_gcc_update32(gcc.va+0x52008/4,0,1u<<8)||!sm8550_gcc_update32(gcc.va+0x52010/4,0,1u<<14)||
      !branch(0x23144)||!branch(0x170e4))return false;
  }else{
   if(!sm8550_gcc_update32(gcc.va+0x52008/4,0,(15u<<18)|(1u<<28)))return false;
   const unsigned halts[]={0x23294,0x23284,0x2327c,0x23280,0x18754};
   for(unsigned off:halts)if(!branch(off))return false;
  }
  const unsigned rcg=hub?0x170e8:0x18760;
  unsigned level=8;uint32_t dfs=0;
  const bool clock=B5qQupClock::xo(read,write,[](unsigned us){IODelay(us);},rcg,level,dfs,!hub);
  IOLog("qcom-dwc3: GENI SE%u clock rcg=%08x dfs=%08x level=%u xo=%u\n",se,rcg,dfs,level,clock);
  if(!clock)return false;
  if(hub){
   for(unsigned pin=206;pin<208;++pin)tlmm.va[pin*0x1000/4]=(tlmm.va[pin*0x1000/4]&~0x23cu)|(1u<<2);
   barrier();
  }else{
   uint32_t sda=0,scl=0;
   const bool ok=B5qUsbBoardCore::configureSe6Pads(
       [&](unsigned pin){return tlmm.va[pin*0x1000/4];},
       [&](unsigned pin,uint32_t value){tlmm.va[pin*0x1000/4]=value;barrier();},
       sda,scl);
   IOLog("qcom-dwc3: SE6 TLMM gpio48=%08x gpio49=%08x verified=%u\n",sda,scl,ok);
   if(!ok)return false;
  }
  if(!engine.open(hub?0x9a0000:0xa98000,0x4000))return false;
  const GeniIo io={seRead,seWrite,const_cast<uint32_t*>(engine.va)};uint32_t config=0;
  seWrite(io.ctx,GENI_CLK_SEL,level);
  if(seRead(io.ctx,GENI_CLK_SEL)!=level){IOLog("qcom-dwc3: GENI SE%u CLK_SEL verify failed level=%u\n",se,level);return false;}
  const int cold=geni_se_init(&io);
  IOLog("qcom-dwc3: GENI SE%u cold-init rc=%d level=%u\n",se,cold,level);
  if(cold)return false;
  const int rc=hub?geni_i2c_prepare_hub_xo(&bus,&io,0x66,&config):geni_i2c_prepare_xo(&bus,&io,0x3e,&config);
  IOLog("qcom-dwc3: GENI SE%u base=%x cfg=%x rc=%d\n",hub?8:6,hub?0x9a0000:0xa98000,config,rc);
  if(rc)return false;
  lock=IOLockAlloc();ready=lock;return ready;
 }
 bool finish(){
  for(unsigned phase=0;phase<3;++phase){
   for(unsigned n=0;n<2500;++n){int rc=geni_i2c_poll(&bus);if(rc==GeniDone)return true;if(rc==GeniFailed)return false;IODelay(10);}
   if(geni_i2c_timeout(&bus)!=GeniPending)return false;
  }return false;
 }
 bool read(uint8_t address,uint8_t reg,uint8_t &value){bus.address=address;if(geni_i2c_start_read(&bus,reg)||!finish())return false;value=bus.data;return true;}
 bool write(uint8_t address,uint8_t reg,uint8_t value){bus.address=address;return !geni_i2c_start_write(&bus,reg,value)&&finish();}
 uint32_t ios() const {return seRead(bus.io.ctx,B5qUsbBoardCore::geniIos);}
 B5qUsbBoardCore::Transfer tiTransfer(bool reading,uint8_t address,uint8_t reg,uint8_t value=0){
  // The shared FIFO code can retire an error before the hardware goes idle.
  // A retry must not reprogram M_CMD0 while the previous command is active.
  if(geni_i2c_busy(&bus)||(seRead(bus.io.ctx,GENI_STATUS)&GENI_STATUS_M_ACTIVE)){
   return {false,0,GeniErrBusy,seRead(bus.io.ctx,GENI_M_IRQ_STATUS),ios()};
  }
  const uint32_t stale=seRead(bus.io.ctx,GENI_M_IRQ_STATUS);
  if(stale)seWrite(bus.io.ctx,GENI_M_IRQ_CLEAR,stale);
  bus.error_status=0; // Never report a previous attempt's status with this result.
  const bool ok=reading?read(address,reg,value):write(address,reg,value);
  const uint8_t error=ok?uint8_t(GeniOk):bus.error?bus.error:uint8_t(GeniErrState);
  return {ok,uint8_t(ok?value:0),error,bus.error_status,ios()};
 }
};
Bus *ti,*maxim;bool maximReady=false;bool otgOn=false;
// PM8550VS SID3 GPIO4 => PPID38b. Select only an APPS-owned channel.
bool releaseTiReset(){
 Map core,cnfg,obs,channel;if(!core.open(0xc400000,0x3000)||!cnfg.open(0xc42d000,0x4000))return false;
 const uint32_t version=core.va[0],count=core.va[1]&0x7ff;
 if(version<BR_VERSION_V7_MIN||version>=BR_VERSION_V8_MIN||!count||count>1024)return false;
 int apid=-1;
 for(unsigned i=0;i<count;++i)if(((core.va[(0x2000+4*i)/4]>>8)&0xfff)==0x38b&&(cnfg.va[i]&7)==0){if(apid>=0)return false;apid=int(i);}
 if(apid<0||!obs.open(0xc440000+uint64_t(apid)*0x20,0x20)||!channel.open(0xc500000+uint64_t(apid)*0x1000,0x1000))return false;
 auto read=[&](uint8_t reg,uint8_t &value){
  obs.va[BR_CMD/4]=br_cmd(BR_OP_EXT_READL,reg,0);
  barrier();
  const int rc=br_wait(obs.va);
  if(rc){
   IOLog("qcom-dwc3: TI reset SID3 GPIO4 apid=%d read reg=%02x rc=%d\n",apid,reg,rc);
   return false;
  }
  value=uint8_t(obs.va[BR_RDATA0/4]);
  return true;
 };
 auto write=[&](uint8_t reg,uint8_t value){
  channel.va[BR_WDATA0/4]=value;
  barrier();
  channel.va[BR_CMD/4]=br_cmd(BR_OP_EXT_WRITEL,reg,0);
  barrier();
  const int rc=br_wait(channel.va);
  if(rc)IOLog("qcom-dwc3: TI reset SID3 GPIO4 apid=%d write reg=%02x rc=%d\n",apid,reg,rc);
  return rc==0;
 };
 auto report=[&](const char *phase,uint8_t type,uint8_t subtype,
                 const B5qUsbBoardCore::ResetRegisters &r,bool readOk,bool ok){
  IOLog("qcom-dwc3: TI reset SID3 GPIO4 apid=%d type=%02x subtype=%02x phase=%s 40=%02x 41=%02x 42=%02x 44=%02x 45=%02x 46=%02x readback=%u verified=%u\n",
        apid,type,subtype,phase,r.mode,r.vin,r.pull,r.source,r.drive,r.enable,readOk,ok);
 };
 return B5qUsbBoardCore::resetTi(read,write,[](unsigned ms){IOSleep(ms);},report);
}
}
extern "C" bool b5q_usb_repeater(bool init,bool host){
 if(init){
  if(!releaseTiReset())return false;
  if(!ti){
   auto *candidate=new Bus;
   if(!candidate)return false;
   if(!candidate->open(false)){delete candidate;return false;}
   ti=candidate;
  }
 }
 if(!ti||!ti->ready)return false;
 using namespace B5qUsbBoardCore;
 IOLockLock(ti->lock);
 const uint32_t lines=ti->ios();
 const bool sda=lines&sdaHigh,scl=lines&sclHigh;
 IOLog("qcom-dwc3: TI SE6 before transfer GENI_IOS=%08x SDA=%u SCL=%u role=%s\n",
       lines,sda,scl,host?"host":"device");
 const bool ok=sda&&scl&&configureTi(
     [](uint8_t address,uint8_t reg){return ti->tiTransfer(true,address,reg);},
     [](uint8_t address,uint8_t reg,uint8_t value){return ti->tiTransfer(false,address,reg,value);},
     [](unsigned us){IODelay(us);},
     [](TiOperation operation,uint8_t address,uint8_t reg,const Transfer &result,unsigned attempts){
      switch(operation){
      case TiOperation::Revision:
       IOLog("qcom-dwc3: TI3e revision read=%u version=%02x bus.error=%u bus.error_status=%08x GENI_IOS=%08x attempts=%u\n",
             result.ok,result.value,result.error,result.errorStatus,result.ios,attempts);
       break;
      case TiOperation::AlternateRevision:
       IOLog("qcom-dwc3: TI4f diagnostic revision read=%u version=%02x bus.error=%u bus.error_status=%08x GENI_IOS=%08x attempts=%u\n",
             result.ok,result.value,result.error,result.errorStatus,result.ios,attempts);
       break;
      case TiOperation::OverrideWrite:
      case TiOperation::OverrideRead:
       IOLog("qcom-dwc3: TI%02x override %s reg=%02x ok=%u value=%02x bus.error=%u bus.error_status=%08x GENI_IOS=%08x attempts=%u\n",
             address,operation==TiOperation::OverrideWrite?"write":"readback",reg,result.ok,
             result.value,result.error,result.errorStatus,result.ios,attempts);
       break;
      }
     });
 IOLockUnlock(ti->lock);
 return ok;
}
extern "C" bool b5q_usb_typec_init(void){
 maxim=new Bus;if(!maxim||!maxim->open(true))return false;
 uint8_t id=0,rev=0,cc=0,water=0;IOLockLock(maxim->lock);
 maximReady=maxim->read(0x66,0,id)&&maxim->read(0x66,1,rev)&&maxim->read(0x25,0x0a,cc)&&
            maxim->read(0x25,0x0b,water)&&id!=0xff&&!(water&2);
 bool roleCommandOk=false;
 if(maximReady)roleCommandOk=B5qMax77705::drp(*maxim,[](unsigned us){IODelay(us);},
  [](const B5qMax77705::OpcodeResult &r){
   IOLog("qcom-dwc3: max77705 DRP opcode=%02x reply=%02x irq=%02x polls=%u triggered=%u reg=%02x ok=%u\n",
         r.opcode,r.reply,r.interrupt,r.polls,r.triggered,r.failedReg,r.ok);
  });
 IOLockUnlock(maxim->lock);
 IOLog("qcom-dwc3: max77705 PMIC66 id=%x rev=%x CC25=%x water=%u bus-ready=%u role-command-ok=%u\n",
       id,rev,cc,!!(water&2),maximReady,roleCommandOk);
 return maximReady;
}
extern "C" int b5q_usb_cable_role(void){
 if(!maximReady)return 0;uint8_t cc0=0,cc1=0;IOLockLock(maxim->lock);
 const bool ok=maxim->read(0x25,0x0a,cc0)&&maxim->read(0x25,0x0b,cc1);IOLockUnlock(maxim->lock);
 const int role=ok?B5qMax77705::role(cc0,cc1):0;
 static int previous=-1;if(role!=previous){IOLog("qcom-dwc3: max77705 CC0=%x CC1=%x role=%d valid=%u\n",cc0,cc1,role,ok);previous=role;}
 return role;
}
extern "C" bool b5q_usb_otg(bool on){
 if(!maximReady)return false;IOLockLock(maxim->lock);
 // Always disable explicitly on a non-host transition, including firmware's prior state.
 const bool ok=B5qMax77705::otg(*maxim,on,[](unsigned us){IODelay(us);});
 if(ok)otgOn=on;uint8_t mode=0,ilim=0,c3=0;maxim->read(0x69,0xb7,mode);maxim->read(0x69,0xb9,ilim);maxim->read(0x69,0xc3,c3);
 IOLockUnlock(maxim->lock);IOLog("qcom-dwc3: Charger69 OTG=%u verified=%u B7=%02x B9=%02x C3=%02x\n",on,ok,mode,ilim,c3);return ok;
}
