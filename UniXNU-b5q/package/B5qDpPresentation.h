/* SPDX-License-Identifier: BSD-2-Clause-Patent */
/* Two retained, independently DMA-qualified scanout buffers. The native
 * display's work-loop gate serializes offer/frame/stop. Tags refer to
 * family-owned requests, never grant ownership of an IOSurface or fence.
 * No memory is freed or borrowed from the primary framebuffer here. */
#pragma once
#include "B5qDpDpu.h"
namespace B5qDp {
struct ScanoutBuffer {uint64_t address=0,bytes=0;};
struct Presentation {
 Dpu dpu;ScanoutBuffer buffers[2]{};Mode mode{};
 uint64_t pendingTag=0,submittedAt=0;uint32_t stride=0,lastFrame=0;
 unsigned current=0,next=0;bool ready=false,closing=false,irqOwned=false;
 static bool disjoint(const ScanoutBuffer &a,const ScanoutBuffer &b){
  return a.address&&b.address&&a.bytes&&b.bytes&&
   a.address<=UINT64_MAX-a.bytes&&b.address<=UINT64_MAX-b.bytes&&
   (a.address+a.bytes<=b.address||b.address+b.bytes<=a.address);
 }
 template<class Io>bool begin(Io &io,const DpuResources &r,const Mode &m,
                             const ScanoutBuffer (&memory)[2],unsigned pitch){
  if(ready||dpu.active||irqOwned||pendingTag||!disjoint(memory[0],memory[1]))return false;
  if(!m.valid()||pitch<m.width*4u||pitch>65535||(pitch&3))return false;
  const uint64_t bytes=uint64_t(pitch)*m.height;
  // Both buffers must independently pass the retained-device-address
  // check. A reservation or a CPU physical pointer is not that check.
  for(const auto &b:memory)if(b.bytes<bytes||!io.dmaAllowed(b.address,b.bytes))return false;
  for(const auto &b:memory)if(!io.fill(b,bytes)||!io.clean(b,bytes))return false;
  if(!dpu.make(r,m,memory[0].address,memory[0].bytes,pitch)||!dpu.apply(io))return false;
  buffers[0]=memory[0];buffers[1]=memory[1];mode=m;stride=pitch;current=next=0;closing=false;
  // A partially started stream retains its mappings until stop succeeds.
  // Set ownership before arm: a synchronous IRQ must see a valid owner.
  irqOwned=true;
  if(!io.arm(this)){irqOwned=false;return false;}
  if(!io.video()||!dpu.start(io))return false;
  lastFrame=io.read(0x350ac);ready=true;return true;
 }
 // Source copying validates IOSurface dimensions/format and producer
 // completion in the native adapter. This layer accepts no pending tag
 // until a full copy/cache clean and the hardware flush both succeed.
 template<class Io>bool offer(Io &io,uint64_t tag,const void *source,bool blank=false){
  if(!ready||closing||pendingTag||!tag||(!source&&!blank))return false;
  const unsigned slot=current^1u;const uint64_t bytes=uint64_t(stride)*mode.height;
  if(!io.dmaAllowed(buffers[slot].address,buffers[slot].bytes))return false;
  const bool copied=blank?io.fill(buffers[slot],bytes):io.copy(buffers[slot],source,mode,stride);
  if(!copied||!io.clean(buffers[slot],bytes)||
     !dpu.flip(io,buffers[slot].address,buffers[slot].bytes,stride))return false;
  next=slot;pendingTag=tag;submittedAt=io.nowUs();return true;
 }
 // The sole completion source is the real INTF0 IRQ worker. A duplicate
 // callback, a frame before CTL consumed the flush, or a stale counter
 // cannot release a request/buffer. Callers do not synthesize this tick.
 template<class Io>uint64_t frame(Io &io,uint32_t frame,uint64_t timestamp){
  const uint32_t delta=frame-lastFrame;
  if(!ready||closing||!irqOwned||!delta||delta>0x7fffffffu)return 0;
  lastFrame=frame;io.notify(frame,timestamp);
  if(!pendingTag||!dpu.latched(io))return 0;
  current=next;const uint64_t tag=pendingTag;pendingTag=submittedAt=0;return tag;
 }
 template<class Io>bool timedOut(Io &io)const{
  return pendingTag&&io.nowUs()-submittedAt>=100000;
 }
 // Stop/drain IRQ callbacks before disabling the owned DPU pipeline. On
 // failure every buffer, tag and MMIO mapping remains retained. A stopped
 // request is returned for cancellation, never reported as presented.
 template<class Io>bool stop(Io &io,uint64_t &cancelled){
  cancelled=0;ready=false;closing=true;
  if(irqOwned){if(!io.disarm())return false;irqOwned=false;}
  if(!dpu.quiesce(io))return false;
  if(!io.stopVideo())return false;
  cancelled=pendingTag;pendingTag=submittedAt=0;
  buffers[0]=buffers[1]={};mode={};stride=lastFrame=0;current=next=0;return true;
 }
};
}
