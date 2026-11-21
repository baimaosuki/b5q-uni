// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>
namespace B5qMax77705 {
constexpr uint8_t pmic=0x66,charger=0x69,muic=0x25;
// Samsung max77705_chg_set_mode_state: preserve charger/buck state;
// UNO->OTG passes through buck for at least1ms. No writes to MUIC opcodes.
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
inline int role(uint8_t cc0,uint8_t cc1){
 if(cc1&2)return 0; // Samsung ConnStat water detection.
 return (cc0&7)==2?2:(cc0&7)==1?1:0; // Our source => Host; sink => Device.
}
}
