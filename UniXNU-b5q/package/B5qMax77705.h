// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>
namespace B5qMax77705 {
constexpr uint8_t pmic=0x66,charger=0x69,muic=0x25;
// Samsung max77705_chg_set_mode_state: preserve charger/buck state;
// UNO->OTG passes through buck for at least1ms.
// Native PDIC evidence: CC_STATUS0 0x0a bits7:6 are CCPinStat,
// bits2:0 are power role (1 sink,2 source). PD_STATUS1 0x0d bit7 is
// data role (0 UFP/device,1 DFP/host). Never infer data role from power.
struct Cable {
 uint8_t cc0=0,cc1=0,pd=0,bc=0;
 bool valid=false;
 bool water() const {return (cc1&2)!=0;}
 unsigned power() const {return valid&&!water()?(cc0&7):0;}
 bool attached() const {return power()==1 || power()==2;}
 int role() const {return attached()?((pd&0x80)?2:1):0;}
 int orientation() const {
  const unsigned pin=cc0>>6;
  return attached()&&(pin==1||pin==2)?int(pin-1):-1;
 }
 bool sourceVbus(int requestedRole) const {return requestedRole!=0&&power()==2;}
 // VBUS is an output while sourcing OTG. Its BC_STATUS feedback is not
 // a cable/role change; CC power/data/orientation/water remain significant.
 uint32_t signature() const {
  return valid?0x80000000u|(cc0&0xc7u)|(uint32_t(cc1&2)<<8)|
                     (uint32_t(pd&0x80)<<16):0;
 }
};
template<class Io> bool readCable(Io &io,Cable &out){
 Cable next;uint8_t end=0;
 // Reading status leaves all read-to-clear interrupt registers untouched.
 const bool ok=io.read(muic,0x0a,next.cc0)&&io.read(muic,0x0b,next.cc1)&&
               io.read(muic,0x0d,next.pd)&&io.read(muic,0x08,next.bc)&&
               io.read(muic,0x0a,end)&&next.cc0==end;
 next.valid=ok;out=next;return ok;
}
// Adopt firmware's live negotiated CC/PD state. Do not force a vendor
// set_sink(1) request on every boot: CcicDxe only proves that opcode takes a
// parameter, not that literal1 represents a native dual-role initialization.
template<class Io> bool update(Io &io,uint8_t reg,uint8_t mask,uint8_t value){
 uint8_t old=0,check=0;if(!io.read(charger,reg,old))return false;
 const uint8_t next=(old&~mask)|(value&mask);
 return (old==next||io.write(charger,reg,next))&&io.read(charger,reg,check)&&check==next;
}
template<class Io,class Delay> bool otg(Io &io,bool on,Delay delay){
 uint8_t mode=0,ok=0;if(!io.read(charger,0xb7,mode))return false;
 if(!on){
  unsigned m=mode&15;unsigned next=m==10?0:m==14?4:m==15?5:m;
  return update(io,0xbd,0x0c,0x0c)&&update(io,0xb7,15,next);
 }
 if(!io.read(charger,0xb2,ok) || !(ok&4) || (ok&0x20))return false;
 if(!update(io,0xbd,0x0c,0x0c)||!update(io,0xb9,0xc0,0x40)||!update(io,0xc2,0x7f,0))return false;
 unsigned m=mode&15,next=0;
 switch(m){case 0:next=10;break;case 4:next=14;break;case 5:next=15;break;
 case 8:case 12:case 13:if(!update(io,0xb7,15,4))return false;delay(1000);next=m==8?10:14;break;
 case 10:case 14:case 15:next=m;break;default:return false;}
 uint8_t c3=0;if(!io.read(charger,0xc3,c3))return false;
 // The Samsung mode-F WCIN workaround surrounds the mode write.
 if(next==15 && !update(io,0xc3,0x40,0))return false;
 bool success=update(io,0xb7,15,next);
 if(next==15)success=update(io,0xc3,0x40,c3)&&success;
 if(!success)update(io,0xb7,15,m==5?5:4);
 return success;
}
}
