/* SPDX-License-Identifier: GPL-2.0-only */
/* Samsung dp_ctrl.c352..690 / dp_link.c1488..1564. No simulated success. */
#pragma once
#include <stdint.h>
#include "B5qDpModes.h"
namespace B5qDp {
enum class TrainError:unsigned {None,Caps,Detached,Io,ClockRecovery,Equalization,Phy,Bandwidth};
struct LinkCaps {
 uint8_t revision=0,rate=0,lanes=0,interval=0;bool enhanced=false,tps3=false,tps4=false;
 bool parse(const uint8_t d[16],unsigned routeLanes){
  *this={};if(!d||d[0]<0x10||d[0]>0x14||(routeLanes!=2&&routeLanes!=4))return false;
  revision=d[0];rate=d[1];lanes=d[2]&31;interval=d[14]&127;enhanced=d[2]&128;tps3=d[2]&64;tps4=d[3]&128;
  if((rate!=6&&rate!=10&&rate!=20&&rate!=30)||(lanes!=1&&lanes!=2&&lanes!=4)||interval>4)return false;
  if(lanes>routeLanes)lanes=routeLanes;return true;
 }
 unsigned delay(bool equalization)const{return interval?interval*4000:equalization?400:100;}
 unsigned pattern()const{return tps4?7:tps3?3:2;}
};
template<class Io>struct Training {
 Io &io;TrainError error=TrainError::None;unsigned rate=0,lanes=0,voltage=0,pre=0,attempts=0;uint8_t last[6]={};bool ready=false;
 explicit Training(Io &owner):io(owner){}
 bool write(uint32_t address,const uint8_t *data,unsigned bytes){return io.dpcd(false,address,const_cast<uint8_t*>(data),bytes);}
 bool byte(uint32_t address,uint8_t value){return write(address,&value,1);}
 bool clockRecovered()const{for(unsigned i=0;i<lanes;i++)if(!((last[i/2]>>(4*(i&1)))&1))return false;return true;}
 bool equalized()const{for(unsigned i=0;i<lanes;i++)if(((last[i/2]>>(4*(i&1)))&7)!=7)return false;return last[2]&1;}
 void adjust(){
  unsigned v=0,p=0;for(unsigned i=0;i<lanes;i++){unsigned n=(last[4+i/2]>>(4*(i&1)))&15;if((n&3)>v)v=n&3;if((n>>2)>p)p=n>>2;}
  voltage=v>2?2:v;pre=p>3-voltage?3-voltage:p;
 }
 bool levels(){
  if(!io.levels(voltage,pre,rate))return false;uint8_t values[4];
  for(unsigned i=0;i<lanes;i++)values[i]=uint8_t(voltage|(pre<<3)|(voltage==2?4:0)|(pre==3?32:0));
  return write(0x103,values,lanes);
 }
 bool status(const LinkCaps &caps,bool eq){
  io.delay(caps.delay(eq));if(!io.connected()){error=TrainError::Detached;return false;}
  for(unsigned i=0;i<100;i++){if(!io.dpcd(true,0x202,last,6)){error=TrainError::Io;return false;}if(!(last[2]&128))return true;}
  error=TrainError::Io;return false;
 }
 bool pattern(unsigned p){return io.pattern(p)&&byte(0x102,uint8_t(p|(p&&p!=7?32:0)));}
 bool one(const LinkCaps &caps){
  voltage=pre=0;const uint8_t config[]={uint8_t(rate),uint8_t(lanes|(caps.enhanced?128:0))};
  if(!io.phy(rate,lanes)||!write(0x100,config,2)||!byte(0x107,0)||!byte(0x108,1)){error=TrainError::Phy;return false;}
  if(!pattern(1)){error=TrainError::Io;return false;}unsigned same=0,previous=0;bool cr=false;
  for(unsigned n=0;n<20;n++){
   if(!levels()){error=TrainError::Phy;return false;}if(!status(caps,false))return false;
   if(clockRecovered()){cr=true;break;}if(voltage==2)break;
   if(previous==voltage){if(++same>=5)break;}else{same=0;previous=voltage;}adjust();
  }
  if(!cr){error=TrainError::ClockRecovery;return false;}
  if(!pattern(caps.pattern())){error=TrainError::Io;return false;}
  for(unsigned n=0;n<6;n++){
   if(!levels()){error=TrainError::Phy;return false;}if(!status(caps,true))return false;
   if(!clockRecovered()){error=TrainError::ClockRecovery;return false;}
   if(equalized()){error=TrainError::None;return true;}adjust();
  }error=TrainError::Equalization;return false;
 }
 bool run(const LinkCaps &caps,const Mode &mode){
  ready=false;error=TrainError::None;rate=caps.rate;lanes=caps.lanes;attempts=0;
  if(!mode.valid()||(lanes!=1&&lanes!=2&&lanes!=4)){error=TrainError::Caps;return false;}
  const unsigned rates[]={30,20,10,6};
  for(unsigned r:rates){if(r>caps.rate||!mode.fits(lanes,r))continue;rate=r;++attempts;
   if(!io.connected()){error=TrainError::Detached;return false;}
   const bool ok=one(caps);const bool cleared=pattern(0);if(!cleared)error=TrainError::Io;
   if(ok&&cleared){ready=true;return true;}
   if(error==TrainError::Detached||error==TrainError::Io)return false;
  }if(!attempts)error=TrainError::Bandwidth;return false;
 }
};
}
