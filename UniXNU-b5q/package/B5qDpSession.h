/* SPDX-License-Identifier: GPL-2.0-only */
/* Native SST link lifecycle joining the source-qualified AUX/clock/PHY/
 * controller/training paths. Caller owns USB/DP combo, power and MMIO maps;
 * this object never borrows or modifies the primary Display DMA domain. */
#pragma once
#include "B5qDpAux.h"
#include "B5qDpClock.h"
#include "B5qDpController.h"
#include "B5qDpModes.h"
#include <string.h>
#include "B5qDpPhy.h"
#include "B5qDpTraining.h"
namespace B5qDp {
enum class LinkError:unsigned {None,Detached,Clock,Edid,Caps,Power,Training,Timeout,Stream};
template<class Io>struct Session {
 Io &io;Aux<Io> aux;Clock<Io> clock;Controller<Io> controller;Phy<Io> phy;
 Modes modes{};Mode selected{};LinkCaps caps{};uint8_t edid[1024]{},dpcd[16]{};
 unsigned discoverStep=0;
 unsigned edidBytes=0,rate=0,lanes=0,attempts=0;bool reverse=false,clocksOwned=false,auxOn=false,sinkPowered=false,trained=false,streaming=false;
 // Review16: diagnostics only; these never feed a register choice.
 uint32_t lastRate=0,lastLanes=0,clockLast=0;uint8_t trainStatus[6]{};unsigned videoStage=0;
 uint32_t auxFailRegs[10]{};bool haveAuxFailRegs=false;
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
   return s.io.prepareRate(rate)&&s.phy.configure(rate,lanes,s.reverse)&&s.phy.enable()&&s.clock.link()&&s.controller.source(lanes);
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
  if(clockOk)powerOk=io.finishRates()&&powerOk;
  if(clockOk)auxOn=clocksOwned=false;
  trained=streaming=false;selected={};rate=lanes=0;return powerOk&&clockOk;
 }
 void captureAuxFailure(){
  if(haveAuxFailRegs)return;
  auxFailRegs[0]=io.read(Block::Ahb,0x00);auxFailRegs[1]=io.read(Block::Ahb,0x20);
  auxFailRegs[2]=io.read(Block::Aux,0x30);auxFailRegs[3]=io.read(Block::Aux,0x38);
  auxFailRegs[4]=io.read(Block::Aux,0x50);auxFailRegs[5]=io.read(Block::Aux,0x54);
  auxFailRegs[6]=io.read(Block::Aux,0x58);auxFailRegs[7]=io.read(Block::DispCc,0x8058);
  auxFailRegs[8]=io.read(Block::DispCc,0x81bc);auxFailRegs[9]=io.read(Block::Phy,0xe4);
  haveAuxFailRegs=true;
 }
 bool fail(LinkError why){
  error=why;clockLast=clock.last;
  if(auxOn)captureAuxFailure();
  stop();return false;
 }
 bool discover(unsigned routeLanes,bool flipped){
  discoverStep=0;haveAuxFailRegs=false;for(auto &byte:dpcd)byte=0;
  if(!stop()){error=LinkError::Clock;return false;}
  modes={};caps={};edidBytes=0;attempts=0;error=LinkError::None;trainError=TrainError::None;reverse=flipped;
  if(!io.connected())return fail(LinkError::Detached);
  if(routeLanes!=2&&routeLanes!=4)return fail(LinkError::Caps);
  discoverStep=1;clocksOwned=true;if(!clock.aux())return fail(LinkError::Clock);
  controller.reset();phy.auxSetup();
  const uint32_t old=io.read(Block::Aux,0x30);
  io.write(Block::Aux,0x30,old|2);io.delay(1000);io.write(Block::Aux,0x30,(old&~2u)|1);
  io.write(Block::Aux,0x3c,0xffff);io.write(Block::Aux,0x40,0xffff);auxOn=true;aux.segmentUsed=false;
  discoverStep=2;if(!aux.dpcd(true,0,dpcd,16)||!caps.parse(dpcd,routeLanes))return fail(LinkError::Caps);
  discoverStep=3;if(!sinkPower(true))return fail(LinkError::Power);sinkPowered=true;
  discoverStep=4;if(!aux.edidBlock(0,edid))return fail(LinkError::Edid);
  const unsigned blocks=unsigned(edid[126])+1;
  if(blocks>8)return fail(LinkError::Edid);
  if(blocks>1)discoverStep=5;
  for(unsigned i=1;i<blocks;i++)if(!aux.edidBlock(i,edid+i*128))return fail(LinkError::Edid);
  discoverStep=6;edidBytes=blocks*128;if(!modes.parse(edid,edidBytes))return fail(LinkError::Edid);
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
   lastRate=training.rate;lastLanes=training.lanes;clockLast=clock.last;
   memcpy(trainStatus,training.last,6);
   if(!inTime())return fail(LinkError::Timeout);
   if(!io.connected())return fail(LinkError::Detached);
   if(ok){selected=modes.values[best];rate=training.rate;lanes=training.lanes;trained=true;error=LinkError::None;return true;}
   if(trainError!=TrainError::ClockRecovery&&trainError!=TrainError::Equalization&&trainError!=TrainError::Bandwidth)break;
  }return fail(LinkError::Training);
 }
 // Only the scanout owner calls this after its retained-DMA/resource gate
 // and DPU setup passed. A trained link alone never sends video.
 bool video(){
  videoStage=0;
  if(!trained||!io.connected())return fail(LinkError::Detached);
  if(!clock.pixel(selected.pixelKHz,rate)){videoStage=1;clockLast=clock.last;return fail(LinkError::Stream);}
  if(!controller.stream(selected,rate,lanes,caps.enhanced)){videoStage=2;clockLast=clock.last;return fail(LinkError::Stream);}
  if(!controller.video()){videoStage=3;clockLast=clock.last;return fail(LinkError::Stream);}
  streaming=true;return true;
 }
};
}
