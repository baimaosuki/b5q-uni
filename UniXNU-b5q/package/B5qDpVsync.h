/* SPDX-License-Identifier: GPL-2.0-only */
/* Original sde_hw_interrupts.c INTF0 and sde_hwio.h MDP TOP offsets.
 * The native IRQ owner serializes begin/end and the shared register RMWs.
 * service() runs in IRQ context: no allocation, sleep, or work-loop lock. */
#pragma once
#include <stdint.h>
namespace B5qDp {
struct Vsync {
 static constexpr uint32_t frameBit=1u<<25,underrunBit=1u<<24,mask=frameBit|underrunBit;
 uint32_t active=0,frames=0,underruns=0,lastFrame=0;
 template<class Io>bool begin(Io &io){
  if(__atomic_load_n(&active,__ATOMIC_ACQUIRE))return false;
  const uint32_t enabled=io.read(0x1010);
  if(enabled&mask)return false; // another owner already requested INTF0
  io.write(0x1018,mask);io.barrier();
  __atomic_store_n(&active,1u,__ATOMIC_RELEASE);
  io.write(0x1010,enabled|mask);io.barrier();return true;
 }
 template<class Io>void end(Io &io){
  if(!__atomic_exchange_n(&active,0u,__ATOMIC_ACQ_REL))return;
  io.write(0x1010,io.read(0x1010)&~mask);io.write(0x1018,mask);io.barrier();
 }
 template<class Io>bool service(Io &io){
  if(!__atomic_load_n(&active,__ATOMIC_ACQUIRE))return false;
  const uint32_t pending=io.read(0x1014)&mask;
  if(!pending)return false;
  // W1C only our own INTF0 bits; never acknowledge DSI, PP, or DP3.
  io.write(0x1018,pending);io.barrier();
  if(pending&underrunBit)__atomic_add_fetch(&underruns,1u,__ATOMIC_RELAXED);
  if(pending&frameBit){
   const uint32_t frame=io.read(0x350ac);
   __atomic_store_n(&lastFrame,frame,__ATOMIC_RELEASE);
   __atomic_add_fetch(&frames,1u,__ATOMIC_RELAXED);io.vsync(frame);
  }return true;
 }
};
}
