// SPDX-License-Identifier: BSD-2-Clause-Patent
// Samsung b5q PHY/Type-C interfaces consumed by the original QcomDwc3.
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceMemory.h>
#include "BootResetCore.h"
#include "GeniI2c.h"
#include "B5qUsbInputs.h"
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
  const unsigned first=hub?206:48;
  for(unsigned pin=first;pin<first+2;++pin)tlmm.va[pin*0x1000/4]=(tlmm.va[pin*0x1000/4]&~0x23cu)|(1u<<2);barrier();
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
 auto read=[&](uint8_t reg,uint8_t &v){obs.va[0]=br_cmd(BR_OP_EXT_READL,reg,0);barrier();if(br_wait(obs.va))return false;v=uint8_t(obs.va[BR_RDATA0/4]);return true;};
 auto write=[&](uint8_t reg,uint8_t v){channel.va[BR_WDATA0/4]=v;barrier();channel.va[0]=br_cmd(BR_OP_EXT_WRITEL,reg,0);barrier();return !br_wait(channel.va);};
 uint8_t type=0,sub=0,mode=0,source=0,en=0,check=0;
 if(!read(4,type)||!read(5,sub)||type!=0x10||!read(0x40,mode)||!read(0x46,en))return false;
 bool ok=false;
 if(sub>=0x10&&sub<=0x13){
  if(!read(0x44,source))return false;
  const uint8_t nextMode=(mode&~3u)|1u,nextSource=(source&~0x8fu)|0x80;
  ok=write(0x40,nextMode)&&write(0x44,nextSource)&&write(0x46,en|0x80)&&read(0x40,check)&&check==nextMode&&read(0x44,check)&&check==nextSource;
 }else if(sub==1||sub==5||sub==9||sub==13){
  const uint8_t value=(mode&~0x7fu)|0x11;
  ok=write(0x40,value)&&write(0x46,en|0x80)&&read(0x40,check)&&check==value;
 }
 ok=ok&&read(0x46,check)&&(check&0x80);
 IOLog("qcom-dwc3: TI reset SID3 GPIO4 apid=%d subtype=%x released=%u\n",apid,sub,ok);
 if(ok)IOSleep(20);return ok;
}
}
extern "C" bool b5q_usb_repeater(bool init,bool host){
 if(init){if(!releaseTiReset())return false;ti=new Bus;if(!ti||!ti->open(false))return false;}
 if(!ti||!ti->ready)return false;
 IOLockLock(ti->lock);uint8_t version=0;bool ok=ti->read(0x3e,0xb0,version)&&version!=0xff;
 for(const auto &pair:B5qUsbInputs::tiHost){uint8_t value=0;ok=ok&&ti->write(0x3e,pair.reg,pair.value)&&ti->read(0x3e,pair.reg,value)&&value==pair.value;}
 IOLockUnlock(ti->lock);IOLog("qcom-dwc3: TI3e version=%02x role=%s overrides=%u\n",version,host?"host":"device",ok);return ok;
}
extern "C" bool b5q_usb_typec_init(void){
 maxim=new Bus;if(!maxim||!maxim->open(true))return false;
 uint8_t id=0,rev=0,cc=0;IOLockLock(maxim->lock);
 maximReady=maxim->read(0x66,0,id)&&maxim->read(0x66,1,rev)&&maxim->read(0x25,0x0a,cc)&&id!=0xff;
 IOLockUnlock(maxim->lock);IOLog("qcom-dwc3: max77705 PMIC66 id=%x rev=%x CC25=%x ready=%u\n",id,rev,cc,maximReady);return maximReady;
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
