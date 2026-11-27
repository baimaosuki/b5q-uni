// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>
namespace B5qUsbIrq {
struct Window {
 uint64_t began=0;
 uint32_t count=0;
 static constexpr uint32_t limit=65536;
 bool observe(uint64_t now,uint64_t oneSecond) {
  if(!count || now-began>=oneSecond){began=now;count=0;}
  return ++count>limit;
 }
};

struct Snapshot {uint32_t iman=0;uint64_t erdp=0;};
template<class Read32>
bool snapshot(unsigned runtime,unsigned index,unsigned windowBytes,Read32 read,Snapshot &out){
 if(index>2u||(runtime&31u)||windowBytes<0x40u+index*0x20u||
    runtime>windowBytes-(0x40u+index*0x20u))return false;
 const unsigned base=runtime+0x20u+index*0x20u;
 out.iman=read(base);
 out.erdp=uint64_t(read(base+0x18))|(uint64_t(read(base+0x1c))<<32);
 return true;
}

// IR1/IR2 have no GIC SPI on b5q. The host bridge polls only while an IP bit
// is set and feeds the registered filter through the normal interrupt path.
// A filter that keeps returning true without a workloop drain must not turn
// the 1 ms poll into a heat loop: only a run of active samples whose ERDPs
// do not advance backs off to 50 ms. An ERDP advance proves the event ring is
// being consumed even when the workloop has not yet cleared the IP bit.
enum class Delivery:uint8_t {Delivered,FilterRejected,BusyInFlight,NotEnabled,NotRegistered,BadSource};
struct Bridge {
 static constexpr uint32_t backoffAfter=1000;
 uint32_t kicks=0,ir1=0,ir2=0,noFilter=0,busy=0,disabled=0,backoff=0,misses=0;
 uint32_t ir1Delivered=0,ir2Delivered=0;
 bool throttled=false;
 uint64_t lastErdp1=0,lastErdp2=0;
 bool haveLast=false;
 void idle(){misses=0;throttled=false;haveLast=false;}
 unsigned intervalMs()const{return throttled?50u:1u;}
 void account(Delivery result){
  // secKicks is a successful-delivery count, not an active-sample count.
  if(result==Delivery::Delivered)++kicks;
  else if(result==Delivery::FilterRejected)++noFilter;
  else if(result==Delivery::BusyInFlight)++busy;
  else if(result==Delivery::NotEnabled||result==Delivery::NotRegistered||result==Delivery::BadSource)++disabled;
 }
 bool progress(bool active1,uint64_t erdp1,bool active2,uint64_t erdp2){
  if(!active1&&!active2){idle();return false;}
  if(!haveLast||erdp1!=lastErdp1||erdp2!=lastErdp2){
   haveLast=true;lastErdp1=erdp1;lastErdp2=erdp2;misses=0;throttled=false;return false;
  }
  const bool justThrottled=!throttled&&++misses>=backoffAfter;
  if(justThrottled){throttled=true;++backoff;}
  return justThrottled;
 }
 bool note(bool active1,uint64_t erdp1,bool active2,uint64_t erdp2,Delivery result){
  if(active1||active2)account(result);
  return progress(active1,erdp1,active2,erdp2);
 }
 bool noteSources(bool active1,uint64_t erdp1,Delivery d1,bool active2,uint64_t erdp2,Delivery d2){
  if(active1){account(d1);if(d1==Delivery::Delivered)++ir1Delivered;}
  if(active2){account(d2);if(d2==Delivery::Delivered)++ir2Delivered;}
  return progress(active1,erdp1,active2,erdp2);
 }
};
}
