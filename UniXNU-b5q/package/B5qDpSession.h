/* SPDX-License-Identifier: GPL-2.0-only */
/* Native SST link lifecycle joining the source-qualified AUX/clock/PHY/
 * controller/training paths. Caller owns USB/DP combo, power and MMIO maps;
 * this object never borrows or modifies the primary Display DMA domain. */
#pragma once
#include "B5qDpAux.h"
#include "B5qDpClock.h"
#include "B5qDpController.h"
#include "B5qDpModes.h"
#include "B5qDpPhy.h"
#include "B5qDpTraining.h"
namespace B5qDp {
enum class LinkError:unsigned {None,Detached,Clock,Edid,Caps,Power,Training,Timeout,Stream};
template<class Io>struct Session {
 Io &io;Aux<Io> aux;Clock<Io> clock;Controller<Io> controller;Phy<Io> phy;
 Modes modes{};Mode selected{};LinkCaps caps{};uint8_t edid[1024]{};
 unsigned edidBytes=0,rate=0,lanes=0,attempts=0;bool reverse=false,clocksOwned=false,auxOn=false,sinkPowered=false,trained=false,streaming=false;
 uint64_t deadline=0;LinkError error=LinkError::None;TrainError trainError=TrainError::None;
 explicit Session(Io &owner):io(owner),aux(owner),clock(owner),controller(owner),phy(owner){}
 bool inTime(){return io.nowUs()<deadline;}
 bool sinkPower(bool on){
  // Original dp_link_power_up/down: DPCD >=1.1, RMW two low bits.
  if(caps.revision<0x11)return true;
  uint8_t power=0;if(!aux.dpcd(true,0x600,&power,1))return false;
  power=uint8_t((power&~3u)|(on?1u:2u));
  if(!aux.dpcd(false,0x600,&power,1))return false;
  if(on)io.delay(1000);return true;
 }
 struct TrainIo {
  Session &s;
  bool connected(){return s.inTime()&&s.io.connected();}
  void delay(unsigned us){s.io.delay(us);}
  bool dpcd(bool read,uint32_t address,uint8_t *p,unsigned n){return connected()&&s.aux.dpcd(read,address,p,n);}
  bool phy(unsigned rate,unsigned lanes){
   if(!connected())return false;
   s.controller.stop();if(!s.clock.stopLink())return false;s.phy.disable();
   return s.phy.configure(rate,lanes,s.reverse)&&s.phy.enable()&&s.clock.link()&&s.controller.source(lanes);
  }
  bool levels(unsigned voltage,unsigned pre,unsigned rate){return connected()&&s.phy.levels(voltage,pre,rate,s.io.read(Block::Ahb,0));}
  bool pattern(unsigned p){return p==0?s.controller.pattern(0):connected()&&s.controller.pattern(p);}
 };
 bool stop(){
  bool powerOk=true,clockOk=true;
  if(auxOn)controller.stop();
  if(sinkPowered){if(io.connected())powerOk=sinkPower(false);sinkPowered=false;}
  if(clocksOwned)clockOk=clock.stopLink();
  if(auxOn){
   phy.disable();
   io.write(Block::Aux,0x30,io.read(Block::Aux,0x30)&~1u);
  }
  if(clocksOwned)clockOk=clock.stopAux()&&clockOk;
  if(clockOk)auxOn=clocksOwned=false;
  trained=streaming=false;selected={};rate=lanes=0;return powerOk&&clockOk;
 }
 bool fail(LinkError why){error=why;stop();return false;}
 bool discover(unsigned routeLanes,bool flipped){
  if(!stop()){error=LinkError::Clock;return false;}
  modes={};caps={};edidBytes=0;attempts=0;error=LinkError::None;trainError=TrainError::None;reverse=flipped;
  if(!io.connected())return fail(LinkError::Detached);
  if(routeLanes!=2&&routeLanes!=4)return fail(LinkError::Caps);
  clocksOwned=true;if(!clock.aux())return fail(LinkError::Clock);
  controller.reset();phy.auxSetup();
  const uint32_t old=io.read(Block::Aux,0x30);
  io.write(Block::Aux,0x30,old|2);io.delay(1000);io.write(Block::Aux,0x30,(old&~2u)|1);
  io.write(Block::Aux,0x3c,0xffff);io.write(Block::Aux,0x40,0xffff);auxOn=true;aux.segmentUsed=false;
  uint8_t dpcd[16];if(!aux.dpcd(true,0,dpcd,16)||!caps.parse(dpcd,routeLanes))return fail(LinkError::Caps);
  if(!sinkPower(true))return fail(LinkError::Power);sinkPowered=true;
  if(!aux.edidBlock(0,edid))return fail(LinkError::Edid);
  const unsigned blocks=unsigned(edid[126])+1;
  if(blocks>8)return fail(LinkError::Edid);
  for(unsigned i=1;i<blocks;i++)if(!aux.edidBlock(i,edid+i*128))return fail(LinkError::Edid);
  edidBytes=blocks*128;if(!modes.parse(edid,edidBytes))return fail(LinkError::Edid);
  return true;
 }
 bool train(){
  if(!auxOn||!modes.count)return fail(LinkError::Caps);
  if(!io.connected())return fail(LinkError::Detached);
  // Bound the entire set of mode/rate fallbacks using elapsed time. A
  // slow/disconnected sink cannot multiply the bound by 32 advertised modes.
  deadline=io.nowUs()+5000000;uint32_t tried=0;TrainIo adapter{*this};
  for(unsigned n=0;n<modes.count;n++){
   unsigned best=modes.count;uint64_t score=0;
   for(unsigned i=0;i<modes.count;i++)if(!(tried&(1u<<i))){
    const auto &m=modes.values[i];if(m.width>5120||!m.fits(caps.lanes,caps.rate))continue;
    const uint64_t rank=uint64_t(m.width)*m.height*1000+m.refreshMilliHz();
    if(rank>score){best=i;score=rank;}
   }
   if(best==modes.count)break;tried|=1u<<best;
   Training<TrainIo> training(adapter);const bool ok=training.run(caps,modes.values[best]);
   attempts+=training.attempts;trainError=training.error;
   if(!inTime())return fail(LinkError::Timeout);
   if(!io.connected())return fail(LinkError::Detached);
   if(ok){selected=modes.values[best];rate=training.rate;lanes=training.lanes;trained=true;error=LinkError::None;return true;}
   if(trainError!=TrainError::ClockRecovery&&trainError!=TrainError::Equalization&&trainError!=TrainError::Bandwidth)break;
  }return fail(LinkError::Training);
 }
 // Only the scanout owner calls this after its retained-DMA/resource gate
 // and DPU setup passed. A trained link alone never sends video.
 bool video(){
  if(!trained||!io.connected())return fail(LinkError::Detached);
  if(!clock.pixel(selected.pixelKHz,rate)||!controller.stream(selected,rate,lanes,caps.enhanced)||!controller.video())return fail(LinkError::Stream);
  streaming=true;return true;
 }
};
}
