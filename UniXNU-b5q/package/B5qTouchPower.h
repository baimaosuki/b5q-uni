// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>

namespace B5qTouchPower {
constexpr unsigned sda=20, scl=21;
constexpr uint8_t address=0x60;

// GPIO callbacks only drive low or release the line. All clock stretching
// waits are bounded, including a STOP after a NACK or partial transaction.
template<class Pins> class Bus {
 Pins &pins;
 bool clockHigh() {
  pins.low(scl,false);
  for(unsigned i=0;i<500;++i){if(pins.high(scl)){pins.delay(2);return true;}pins.delay(2);}
  return false;
 }
 bool start() {
  pins.low(sda,false);pins.delay(2);
  if(!clockHigh() || !pins.high(sda))return false;
  pins.low(sda,true);pins.delay(2);pins.low(scl,true);return true;
 }
 bool stop() {
  pins.low(scl,true);pins.low(sda,true);pins.delay(2);
  const bool idle=clockHigh();pins.low(sda,false);pins.delay(2);
  return idle && pins.high(sda);
 }
 bool send(uint8_t byte) {
  for(unsigned bit=0;bit<8;++bit){
   pins.low(sda,!(byte&0x80));pins.delay(2);
   if(!clockHigh())return false;
   pins.low(scl,true);byte=uint8_t(byte<<1);
  }
  pins.low(sda,false);pins.delay(2);
  if(!clockHigh())return false;
  const bool ack=!pins.high(sda);pins.low(scl,true);return ack;
 }
 bool receive(uint8_t &byte) {
  byte=0;pins.low(sda,false);
  for(unsigned bit=0;bit<8;++bit){
   pins.delay(2);if(!clockHigh())return false;
   byte=uint8_t((byte<<1)|pins.high(sda));pins.low(scl,true);
  }
  // Single-byte reads terminate with NACK (SDA released).
  pins.delay(2);if(!clockHigh())return false;
  pins.low(scl,true);return true;
 }
public:
 explicit Bus(Pins &p):pins(p) {}
 bool read(uint8_t reg,uint8_t &v) {
  const bool ok=start() && send(address<<1) && send(reg) && start() && send((address<<1)|1) && receive(v);
  return stop() && ok;
 }
 bool write(uint8_t reg,uint8_t v) {
  const bool ok=start() && send(address<<1) && send(reg) && send(v);
  return stop() && ok;
 }
};

template<class Io> bool enable(Io &io,uint8_t &before,uint8_t &after) {
 const uint8_t registers[]={0x05,0x06}, selectors[]={0x0e,0x18};
 for(unsigned i=0;i<2;++i){
  uint8_t old=0,confirmed=0;
  if(!io.read(registers[i],old))return false;
  const uint8_t value=(old&0x80)|selectors[i];
  if((old!=value && !io.write(registers[i],value)) || !io.read(registers[i],confirmed) || confirmed!=value)return false;
 }
 if(!io.read(0x03,before))return false;
 const uint8_t value=before|0x06;
 return (before==value || io.write(0x03,value)) && io.read(0x03,after) && after==value;
}
}
