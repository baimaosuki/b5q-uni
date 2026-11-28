/* SPDX-License-Identifier: GPL-2.0-only */
/* b5q.dts dp_aux_* pinctrl + original secdp_power_set/unset_gpio.
 * No PS5169, USB GPIO11 guess, or alternate board pin is used. */
#pragma once
#include <stdint.h>
namespace B5qDp {
struct AuxPins {
 static constexpr unsigned select=180,enable=183;
 uint32_t config[2]{},out[2]{};bool owned=false;
 template<class Io>bool output(Io &io,unsigned pin,bool high){
  const uint32_t value=(io.gpioRead(pin,4)&~2u)|(high?2u:0u);
  io.gpioWrite(pin,4,value);
  // GPIO function0, bias-disable, drive2mA, OE=1; unrelated bits retained.
  io.gpioWrite(pin,0,(io.gpioRead(pin,0)&~0x1ffu)|0x200u);
  return (io.gpioRead(pin,0)&0x3ffu)==0x200u&&bool(io.gpioRead(pin,4)&1)==high;
 }
 template<class Io>bool begin(Io &io,bool reverse){
  if(owned)return false;
  config[0]=io.gpioRead(select,0);out[0]=io.gpioRead(select,4);
  config[1]=io.gpioRead(enable,0);out[1]=io.gpioRead(enable,4);owned=true;
  if(!output(io,enable,true)||!output(io,select,reverse))return false;
  io.delay(100);if(!output(io,enable,false))return false;io.delay(100);return true;
 }
 template<class Io>bool end(Io &io){
  if(!owned)return true;
  if(!output(io,enable,true))return false;io.delay(100);
  io.gpioWrite(select,4,out[0]);io.gpioWrite(select,0,config[0]);
  io.gpioWrite(enable,4,out[1]);io.gpioWrite(enable,0,config[1]);owned=false;return true;
 }
};
}
