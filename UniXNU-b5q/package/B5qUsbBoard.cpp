// SPDX-License-Identifier: BSD-2-Clause-Patent
// Samsung b5q PHY/Type-C interfaces consumed by the original QcomDwc3.
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceMemory.h>
#include "BootResetCore.h"
#include "GeniI2c.h"
#include "B5qUsbBoardCore.h"
#include "B5qMax77705.h"
#include "B5qQupClock.h"
#include "B5qFuelGauge.h"
#include "B5qDpPdic.h"
#include "B5qDpPort.h"
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
 ~Bus(){if(lock)IOLockFree(lock);}
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
 bool idle(){
  if(geni_i2c_busy(&bus))return false;
  unsigned tries=0;
  while((seRead(bus.io.ctx,GENI_STATUS)&GENI_STATUS_M_ACTIVE)&&tries++<2500)IODelay(10);
  if(seRead(bus.io.ctx,GENI_STATUS)&GENI_STATUS_M_ACTIVE){bus.error=GeniErrBusy;bus.error_status=seRead(bus.io.ctx,GENI_M_IRQ_STATUS);return false;}
  const uint32_t stale=seRead(bus.io.ctx,GENI_M_IRQ_STATUS);
  if(stale)seWrite(bus.io.ctx,GENI_M_IRQ_CLEAR,stale);
  return true;
 }
 bool read(uint8_t address,uint8_t reg,uint8_t &value){if(!idle())return false;bus.address=address;if(geni_i2c_start_read(&bus,reg)||!finish())return false;value=bus.data;return true;}
 bool readWord(uint8_t address,uint8_t reg,uint16_t &value){
  if(!idle())return false;uint8_t bytes[2]={};bus.address=address;
  if(geni_i2c_start_read_buffer(&bus,&reg,1,bytes,2)||!finish())return false;
  value=uint16_t(bytes[0])|(uint16_t(bytes[1])<<8);return true;
 }
 bool write(uint8_t address,uint8_t reg,uint8_t value){if(!idle())return false;bus.address=address;return !geni_i2c_start_write(&bus,reg,value)&&finish();}
 bool readBuffer(uint8_t address,uint8_t reg,uint8_t *value,unsigned bytes){
  if(!value||!bytes||bytes>33||!idle())return false;
  bus.address=address;return !geni_i2c_start_read_buffer(&bus,&reg,1,value,bytes)&&finish();
 }
 bool writeBuffer(uint8_t address,const uint8_t *value,unsigned bytes){
  if(!value||!bytes||bytes>34||!idle())return false;
  bus.address=address;return !geni_i2c_start_write_buffer(&bus,value,bytes)&&finish();
 }
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
volatile unsigned maximBusState;
bool openMaxim(){
 unsigned expected=0;
 if(__atomic_compare_exchange_n(&maximBusState,&expected,1u,false,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE)){
  Bus *candidate=new Bus;
  const bool ok=candidate&&candidate->open(true);
  if(ok)maxim=candidate;else delete candidate;
  __atomic_store_n(&maximBusState,ok?2u:0u,__ATOMIC_RELEASE);
  return ok;
 }
 for(unsigned i=0;i<600;++i){
  const unsigned state=__atomic_load_n(&maximBusState,__ATOMIC_ACQUIRE);
  if(state!=1)return state==2;
  IOSleep(10);
 }
 return false;
}
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
namespace {
// Control opcodes must work while detached to turn detection on. DP's
// attached-only PdicIo remains separate; both use the same production mailbox
// and one SE8 lock held across request/poll/response.
struct CcControlIo {
 bool read(uint8_t address,uint8_t reg,uint8_t *data,unsigned size){return maxim->readBuffer(address,reg,data,size);}
 bool write(uint8_t address,const uint8_t *data,unsigned size){return maxim->writeBuffer(address,data,size);}
 bool connected(){B5qMax77705::Cable cable;return B5qMax77705::readCable(*maxim,cable)&&!cable.water();}
 void delay(unsigned us){if(us>=1000)IOSleep(us/1000);else IODelay(us);}
 uint64_t nowUs(){uint64_t ns=0;absolutetime_to_nanoseconds(mach_absolute_time(),&ns);return ns/1000;}
};
uint8_t ccControlKnown=0xff;
void configureTypecDrp(){
 CcControlIo io;B5qDp::Mailbox<CcControlIo> mailbox(io);B5qMax77705::DrpState state;
 const bool ok=B5qMax77705::configureDrp(*maxim,mailbox,state);
 if(state.stage>=2)ccControlKnown=state.after;
 IOLog("qcom-dwc3: max77705 DRP stage=%u ok=%u error=%u CCCTRL1=%02x->%02x requested=%02x wrote=%u deferred=%u CC0=%02x CC1=%02x PD0=%02x PD1=%02x BC=%02x\n",
       state.stage,ok,unsigned(mailbox.error),state.before,state.after,state.requested,state.wrote,state.deferred,
       state.cable.cc0,state.cable.cc1,state.pd0,state.cable.pd,state.cable.bc);
}
void diagnoseTypecCc(const B5qMax77705::Cable &cable){
 const unsigned pin=cable.cc0>>6;
 if(!cable.valid||(cable.cc0&7)||(pin!=1&&pin!=2))return;
 static uint32_t previous=~0u;
 const uint32_t signature=cable.cc0|(uint32_t(cable.cc1)<<8)|(uint32_t(cable.pd)<<16);
 if(previous==signature)return;previous=signature;
 CcControlIo io;B5qDp::Mailbox<CcControlIo> mailbox(io);uint8_t response[2]={0,ccControlKnown},cc0=0,cc1=0,pd0=0,pd1=0;
 // An opcode reply can take500ms. Never spend the Source->VBUS window
 // waiting for diagnostics; DRP init already read back the control value.
 const bool cached=cable.vconnCandidate();
 const bool control=!cached&&mailbox.command(B5qMax77705::ccControlRead,nullptr,0,response,1);
 if(control)ccControlKnown=response[1];
 const bool status=maxim->read(0x25,0x0a,cc0)&&maxim->read(0x25,0x0b,cc1)&&
                   maxim->read(0x25,0x0c,pd0)&&maxim->read(0x25,0x0d,pd1);
 IOLog("qcom-dwc3: max77705 CC-diag control=%u error=%u CCCTRL1=%02x status=%u CC_STATUS0=%02x CC_STATUS1=%02x PD_STATUS0=%02x PD_STATUS1=%02x source-candidate=%u poll-ms=%u control-cached=%u policy=require-source-or-vconn-dfp\n",
       control,unsigned(mailbox.error),(control||cached)?response[1]:0xff,status,cc0,cc1,pd0,pd1,cable.sourceCandidate(),cable.pollIntervalMs(),cached);
}
}
extern "C" bool b5q_usb_typec_init(void){
 if(!openMaxim())return false;
 uint8_t id=0,rev=0;B5qMax77705::Cable cable;
 IOLockLock(maxim->lock);
 const bool ready=maxim->read(0x66,0,id)&&maxim->read(0x66,1,rev)&&id!=0xff&&
            B5qMax77705::readCable(*maxim,cable);
 if(ready)configureTypecDrp();
 IOLockUnlock(maxim->lock);
 IOLog("qcom-dwc3: max77705 PMIC66 id=%x rev=%x CC25=%x/%x PD=%x water=%u bus-ready=%u policy=firmware-negotiated\n",
       id,rev,cable.cc0,cable.cc1,cable.pd,cable.water(),ready);
 __atomic_store_n(&maximReady,ready,__ATOMIC_RELEASE);
 // Water blocks roles in Cable, not future dry-cable status observations.
 return __atomic_load_n(&maximReady,__ATOMIC_ACQUIRE);
}
namespace {
bool ensureMaximReady(){
 if(__atomic_load_n(&maximReady,__ATOMIC_ACQUIRE))return true;
 uint64_t ns=0;absolutetime_to_nanoseconds(mach_absolute_time(),&ns);
 static uint64_t lastAttempt=0;
 const uint64_t now=ns/1000000+1;
 uint64_t last=__atomic_load_n(&lastAttempt,__ATOMIC_ACQUIRE);
 if(__atomic_load_n(&maximBusState,__ATOMIC_ACQUIRE)!=2&&last&&now-last<1000)return false;
 if(!__atomic_compare_exchange_n(&lastAttempt,&last,now,false,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE))
  return __atomic_load_n(&maximReady,__ATOMIC_ACQUIRE);
 return b5q_usb_typec_init();
}
}
// Battery and USB share the same physical SE8 engine and lock. Read-only
// gauge/charger sampling never changes charge policy or clears IRQ status.
extern "C" bool b5q_battery_snapshot(B5qFuelGauge::Raw *raw,
                                     B5qMax77705::Cable *cable,uint8_t *detail){
 if(!raw||!cable||!detail||!openMaxim())return false;
 B5qFuelGauge::Raw pending{};B5qMax77705::Cable next{};uint8_t chargerDetail=0;
 IOLockLock(maxim->lock);
 const bool ok=B5qFuelGauge::read([](uint8_t address,uint8_t reg,uint16_t &value){
    return maxim->readWord(address,reg,value);
   },pending)&&B5qMax77705::readCable(*maxim,next)&&maxim->read(0x69,0xb3,chargerDetail);
 IOLockUnlock(maxim->lock);
 if(ok){*raw=pending;*cable=next;*detail=chargerDetail;}
 return ok;
}
extern "C" bool b5q_usb_cable_state(B5qMax77705::Cable *out){
 if(!out)return false;
 *out={};if(!ensureMaximReady())return false;
 IOLockLock(maxim->lock);const bool ok=B5qMax77705::readCable(*maxim,*out);
 if(ok)diagnoseTypecCc(*out);
 IOLockUnlock(maxim->lock);
 static uint32_t previous=~0u;
 if(__atomic_exchange_n(&previous,out->signature(),__ATOMIC_RELAXED)!=out->signature())
  IOLog("qcom-dwc3: max77705 CC0=%x CC1=%x PD=%x BC=%x power=%u data=%d reverse=%d valid=%u\n",
        out->cc0,out->cc1,out->pd,out->bc,out->power(),out->role(),out->orientation(),out->valid);
 // Valid orientation/DFP does not prove an attached CC power state. Preserve
 // the working Device policy; log these ambiguous PDIC snapshots once each.
 static uint32_t ambiguous=~0u;
 const uint32_t raw=out->cc0|(uint32_t(out->cc1)<<8)|(uint32_t(out->pd)<<16);
 if(ok&&out->valid&&!(out->cc0&7)&&(out->pd&0x80)&&
    __atomic_exchange_n(&ambiguous,raw,__ATOMIC_RELAXED)!=raw)
  IOLog("qcom-dwc3: pdic-ambiguous CC0=%x CC1=%x PD=%x BC=%x cc-power=0 vconn=%u DFP=1 policy=await-valid-cc\n",out->cc0,out->cc1,out->pd,out->bc,!!(out->cc0&8));
 return ok;
}
extern "C" int b5q_usb_cable_role(void){
 B5qMax77705::Cable cable;b5q_usb_cable_state(&cable);
 return cable.role();
}
extern "C" bool b5q_usb_otg(bool on){
 if(!ensureMaximReady())return false;IOLockLock(maxim->lock);
 // The caller follows the PDIC power role, independently of Host/Device.
 const bool ok=B5qMax77705::otg(*maxim,on,[](unsigned us){IODelay(us);});
 if(ok)otgOn=on;uint8_t mode=0,ilim=0,c3=0;maxim->read(0x69,0xb7,mode);maxim->read(0x69,0xb9,ilim);maxim->read(0x69,0xc3,c3);
 IOLockUnlock(maxim->lock);IOLog("qcom-dwc3: Charger69 OTG=%u verified=%u B7=%02x B9=%02x C3=%02x\n",on,ok,mode,ilim,c3);return ok;
}
namespace {
// No second GENI owner: an opcode, its response and any dependent VDM request
// stay under the same physical SE8 lock as Type-C and battery sampling.
struct PdicIo {
 bool read(uint8_t address,uint8_t reg,uint8_t *data,unsigned size){return maxim->readBuffer(address,reg,data,size);}
 bool write(uint8_t address,const uint8_t *data,unsigned size){return maxim->writeBuffer(address,data,size);}
 bool connected(){B5qMax77705::Cable cable;return B5qMax77705::readCable(*maxim,cable)&&cable.attached();}
 void delay(unsigned us){if(us>=1000)IOSleep(us/1000);else IODelay(us);}
 uint64_t nowUs(){uint64_t ns=0;absolutetime_to_nanoseconds(mach_absolute_time(),&ns);return ns/1000;}
};
B5qDp::AltMode dpAlt;bool dpStarted=false,dpFailed=false;uint32_t dpCable=0,dpPending=0;
uint64_t dpDeadline=0;
uint64_t dpNow(){uint64_t ns=0;absolutetime_to_nanoseconds(mach_absolute_time(),&ns);return ns/1000000;}
}
extern "C" bool b5q_dp_port_poll(B5qDpPortState *out){
 if(!out)return false;*out={};out->reverse=-1;
 if(!openMaxim())return false;
 IOLockLock(maxim->lock);
 B5qMax77705::Cable cable;const bool sampled=B5qMax77705::readCable(*maxim,cable);
 PdicIo io;B5qDp::Mailbox<PdicIo> mailbox(io);bool ok=sampled;
 const uint32_t signature=sampled?cable.signature():0;
 // Source must establish VBUS before optional DP opcode discovery can
 // wait on the same role worker. Keep an existing active DP link intact.
 if(sampled&&!dpStarted&&cable.sourceVbus(cable.role())&&!(cable.bc&0x80)){
  out->attached=true;out->reverse=int8_t(cable.orientation());out->generation=dpAlt.generation;
  IOLockUnlock(maxim->lock);return true;
 }
 if(!sampled||!cable.attached()||cable.orientation()<0){
  if(dpStarted)mailbox.enable(false);
  dpStarted=dpFailed=false;dpCable=dpPending=0;dpAlt.reset();
 }else{
  if(signature!=dpCable){
   if(dpStarted)mailbox.enable(false);
   dpAlt.reset();dpStarted=dpFailed=false;dpCable=signature;dpPending=0;
  }
  if(!dpStarted&&!dpFailed){
   dpStarted=dpAlt.start(mailbox,cable.power()==1&&cable.role()==2);dpFailed=!dpStarted;dpDeadline=dpNow()+3000;ok=dpStarted;
  }
  if(dpStarted){
   uint8_t pd=0,vdm=0;
   ok=maxim->read(0x25,4,pd)&&maxim->read(0x25,5,vdm);
   if(ok)dpPending|=(vdm&15)|((uint32_t(pd)&0x1c)<<2);
   // Firmware can omit an earlier VDM interrupt. Recover its cached packet
   // in the same order as Samsung max77705_receive_alternate_message.
   const unsigned awaited=unsigned(dpAlt.phase);
   if(awaited>=1&&awaited<=4&&(dpPending&0x0fu))dpPending|=1u<<(awaited-1);
   for(unsigned bit=0;ok&&bit<7;bit++)if(dpPending&(1u<<bit)){
    const uint8_t ids[]={1,2,3,4,0x10,0x11,6};const uint8_t id=ids[bit];
    const unsigned expected=unsigned(dpAlt.phase);
    if(bit<4&&expected!=bit+1){if(expected>bit+1)dpPending&=~(1u<<bit);continue;}
    // Status is also an active-mode update. A cached Configure ACK belongs
    // only to the in-flight configure, never to a later HPD interrupt.
    if(bit==4&&expected<unsigned(B5qDp::AltMode::Phase::Status))continue;
    if(bit==5&&dpAlt.phase!=B5qDp::AltMode::Phase::Configure){
     if(dpAlt.phase==B5qDp::AltMode::Phase::Active)dpPending&=~(1u<<bit);continue;
    }
    if(bit==6&&expected<unsigned(B5qDp::AltMode::Phase::Status))continue;
    uint8_t reply[33]={};ok=mailbox.get(id,reply);
    if(ok)ok=dpAlt.event(mailbox,id,reply,(id==1||id==2||id==3)?32:id==4?8:12);
    dpPending&=~(1u<<bit);dpDeadline=dpNow()+3000;
    IOLog("B5qDP: pdic id=%02x phase=%u pin=%02x lanes=%u hpd=%u irq=%u packet=%u error=%u mailbox=%u\n",
      id,unsigned(dpAlt.phase),dpAlt.pin,dpAlt.lanes(),dpAlt.hpd,dpAlt.hpdIrq,ok,unsigned(dpAlt.error),unsigned(mailbox.error));
    if(!ok)IOLog("B5qDP: pdic-raw id=%02x bytes=%02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x\n",
      id,reply[0],reply[1],reply[2],reply[3],reply[4],reply[5],reply[6],reply[7],reply[8],reply[9],reply[10],reply[11],reply[12],reply[13],reply[14],reply[15]);
   }
   if(ok&&dpAlt.phase==B5qDp::AltMode::Phase::Off){
    mailbox.enable(false);dpStarted=false;dpFailed=true;dpPending=0;
   }
   if(dpAlt.phase!=B5qDp::AltMode::Phase::Active&&dpNow()>dpDeadline){ok=false;dpAlt.reject(B5qDp::PdError::Timeout);}
   if(!ok||dpAlt.phase==B5qDp::AltMode::Phase::Failed){
    mailbox.enable(false);dpStarted=false;dpFailed=true;
   }
  }
 }
 out->phase=unsigned(dpAlt.phase);out->error=unsigned(dpAlt.error);out->generation=dpAlt.generation;
 out->pin=dpAlt.pin;out->lanes=uint8_t(dpAlt.lanes());out->reverse=int8_t(cable.orientation());
 out->attached=sampled&&cable.attached();out->hpd=dpStarted&&dpAlt.phase==B5qDp::AltMode::Phase::Active&&dpAlt.hpd;
 out->configured=dpStarted&&dpAlt.phase==B5qDp::AltMode::Phase::Active;
 out->hpdIrq=dpAlt.hpdIrq;dpAlt.hpdIrq=false;
 IOLockUnlock(maxim->lock);return ok;
}
extern "C" void b5q_dp_port_stop(void){
 if(!openMaxim())return;IOLockLock(maxim->lock);
 if(dpStarted){PdicIo io;B5qDp::Mailbox<PdicIo> mailbox(io);mailbox.enable(false);}
 dpStarted=dpFailed=false;dpPending=dpCable=0;dpAlt.reset();IOLockUnlock(maxim->lock);
}
