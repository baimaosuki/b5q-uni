/* SPDX-License-Identifier: GPL-2.0-only */
/* Native b5q DP0 link owner. QcomDwc3's role worker serializes this owner
 * with shared USB/DP combo changes. No apps_smmu MMIO or primary-display
 * bank access; training alone neither enables scanout nor publishes IOMFB. */
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceMemory.h>
#include <kern/clock.h>
#include <mach/mach_time.h>
#include "AppsSmmuLock.h"
#include "B5qDpDpuResources.h"
#include "B5qDpBoard.h"
#include "B5qDpPort.h"
#include "B5qDpSession.h"
#include "B5qFeatures.h"
#include "B5qMax77705.h"
#include "QcomRpmh.h"
extern "C" bool b5q_usb_cable_state(B5qMax77705::Cable *);
namespace {
using B5qDp::Block;
void barrier(){asm volatile("dsb sy":::"memory");}
uint64_t nowUs(){uint64_t ns=0;absolutetime_to_nanoseconds(mach_absolute_time(),&ns);return ns/1000;}
struct Window {
 IOMemoryMap *map=nullptr;volatile uint32_t *va=nullptr;
 Window()=default;Window(const Window&)=delete;Window&operator=(const Window&)=delete;
 bool open(uint64_t base,unsigned bytes){
  if(va)return true;auto *d=IODeviceMemory::withRange(base,bytes);
  map=d?d->map(kIOMapAnywhere|kIOMapInhibitCache):nullptr;OSSafeReleaseNULL(d);
  va=map?reinterpret_cast<volatile uint32_t*>(map->getVirtualAddress()):nullptr;
  if(!va){OSSafeReleaseNULL(map);return false;}return true;
 }
 void close(){va=nullptr;OSSafeReleaseNULL(map);}
 ~Window(){close();}
};
struct Hardware {
 Window dp,phy,disp,gcc,dpu,sel,en,cmd,rsc;
 B5qDp::AuxPins pins;
 bool opened=false,mxOwned=false,fault=false,cablePresent=false;
 unsigned wantedReverse=0;uint64_t sampled=0;
 QcomRpmhResource mx{};
 uint64_t nowUs(){return ::nowUs();}
 void delay(unsigned us){if(us>=1000)IOSleep((us+999)/1000);else IODelay(us);}
 bool connected(){
  if(!opened||fault||!cablePresent)return false;
  const uint64_t now=nowUs();
  if(now-sampled>=20000){
   B5qMax77705::Cable cable;sampled=now;
   cablePresent=b5q_usb_cable_state(&cable)&&cable.attached()&&cable.orientation()==int(wantedReverse);
  }
  return cablePresent;
 }
 volatile uint32_t *address(Block b,unsigned off){
  switch(b){
  case Block::Ahb:if(off<0xfc&&dp.va)return dp.va+off/4;break;
  case Block::Aux:if(off<0xc0&&dp.va)return dp.va+(0x200+off)/4;break;
  case Block::Link:if(off<0x770&&dp.va)return dp.va+(0x400+off)/4;break;
  case Block::Pixel:if(off<0x98&&dp.va)return dp.va+(0x1000+off)/4;break;
  case Block::Pll:if(off<0x200&&phy.va)return phy.va+off/4;break;
  case Block::Tx0:if(off<0x200&&phy.va)return phy.va+(0x200+off)/4;break;
  case Block::Tx1:if(off<0x200&&phy.va)return phy.va+(0x600+off)/4;break;
  case Block::Phy:if(off<0x200&&phy.va)return phy.va+(0xa00+off)/4;break;
  case Block::DispCc:if(off<0x10000&&disp.va)return disp.va+off/4;break;
  case Block::Dpu:if(off<0x84000&&dpu.va)return dpu.va+off/4;break;
  default:break;
  }
  fault=true;return nullptr;
 }
 uint32_t read(Block b,unsigned off){auto *p=address(b,off);return p?*p:0;}
 void write(Block b,unsigned off,uint32_t value){auto *p=address(b,off);if(p){*p=value;barrier();}}
 volatile uint32_t *gpio(unsigned pin,unsigned off){
  Window *w=pin==pins.select?&sel:pin==pins.enable?&en:nullptr;
  if(!w||!w->va||(off!=0&&off!=4)){fault=true;return nullptr;}return w->va+off/4;
 }
 uint32_t gpioRead(unsigned pin,unsigned off){auto *p=gpio(pin,off);return p?*p:0;}
 void gpioWrite(unsigned pin,unsigned off,uint32_t value){auto *p=gpio(pin,off);if(p){*p=value;barrier();}}
 bool open(bool reverse){
  fault=false;wantedReverse=reverse;sampled=nowUs();cablePresent=true;
  if(!dp.open(0xae90000,0x2000)||!phy.open(0x88ea000,0x1000)||
     !disp.open(0xaf00000,0x10000)||!gcc.open(0x100000,0x60000)||
     !dpu.open(0xae00000,0x84000)||!sel.open(0xf100000+180*0x1000,0x1000)||
     !en.open(0xf100000+183*0x1000,0x1000))return false;
  // Original DP supplies share USB's already enabled ldoe1/ldoe3/ldof3/
  // ldob5 rails and GCC PHY GDSC. Do not become a second regulator owner.
  if(!(gcc.va[0x50018/4]&(1u<<31))||!(gcc.va[0x39004/4]&(1u<<31))||
     !(disp.va[0x9000/4]&(1u<<31)))return false;
  B5qDp::DpuResources resources;resources.inspect([&](unsigned off){return dpu.va[off/4];});
  if(resources.dpBusy)return false;
  // Original secdp_power_set_gpio, no aux-sel-inv/redriver on b5q:
  // first isolate active-low AUX enable, set CC polarity, then enable.
  if(!pins.begin(*this,reverse))return false;opened=true;return true;
 }
 bool voteMx(uint32_t value){
  if(!rsc.va)return false;const QcomRscLayout layout=qcom_rsc_layout(rsc.va[0]);
  AppsSmmuLock guard;if(!guard.ready())return false;
  constexpr unsigned tcs=2,base=0xd00;QcomRpmhWrite writes[16];
  // rpmh-rsc.c: STATUS==0 means busy. USB's initial rail programming
  // precedes this role worker. Never overwrite an unfinished transaction,
  // including our own timed-out vote; later stop/retry can reap it.
  if(!rsc.va[(base+layout.tcs_stride*tcs+layout.status)/4]){
   IOLog("B5qDP: mx TCS2 busy retained\n");return false;
  }
  if(rsc.va[(base+layout.irq_status)/4]&(1u<<tcs)){
   const unsigned count=qcom_rpmh_finish(&layout,tcs,writes,16);
   for(unsigned i=0;i<count;i++)rsc.va[(base+writes[i].offset)/4]=writes[i].value;
   barrier();
  }
  const unsigned n=qcom_rpmh_active_request(&layout,tcs,&mx.address,&value,1,writes,16);
  if(!n)return false;
  rsc.va[base/4]|=1u<<tcs;barrier();
  for(unsigned i=0;i<n;i++){rsc.va[(base+writes[i].offset)/4]=writes[i].value;barrier();}
  const uint64_t start=nowUs();uint32_t status=0;
  do{status=rsc.va[(base+layout.irq_status)/4];if(status&(1u<<tcs))break;IODelay(10);}while(nowUs()-start<20000);
  const bool done=status&(1u<<tcs);
  if(done){
   const unsigned end=qcom_rpmh_finish(&layout,tcs,writes,16);
   for(unsigned i=0;i<end;i++)rsc.va[(base+writes[i].offset)/4]=writes[i].value;
   barrier();
  }
  IOLog("B5qDP: mx index=%u completion=%u irq=%08x\n",value,done,status);return done;
 }
 bool prepareRate(unsigned rate){
  if(rate!=30)return finishRates();
  if(mxOwned)return true;
  if(!cmd.open(0x81c60000,0x20000)||!rsc.open(0x17a20000,0x10000))return false;
  auto *copy=static_cast<uint8_t*>(IOMallocData(0x20000));if(!copy)return false;
  for(unsigned i=0;i<0x20000;i+=4){const uint32_t v=cmd.va[i/4];memcpy(copy+i,&v,4);}
  bool ok=!qcom_cmd_db_find(copy,0x20000,"mx.lvl",&mx);IOFreeData(copy,0x20000);
  uint32_t index=0;
  // Samsung b5q qcom,pll-supply-entry: vdd_mx minimum0x180. ARC needs
  // the real cmd-db level index, not raw384 written as an index.
  ok=ok&&!qcom_rpmh_level_index(&mx,0x180,&index)&&index<mx.level_count&&mx.levels[index]>=0x180;
  if(!ok)return false;
  // A completion timeout still leaves ownership uncertain. Retain it
  // until an explicit zero vote succeeds during bounded stop/retry.
  mxOwned=true;return voteMx(index);
 }
 bool finishRates(){if(!mxOwned)return true;if(!voteMx(0))return false;mxOwned=false;return true;}
 bool close(){
  if(mxOwned)return false;
  if(!pins.end(*this))return false;
  opened=cablePresent=false;
  dp.close();phy.close();disp.close();gcc.close();dpu.close();sel.close();en.close();cmd.close();rsc.close();return true;
 }
};
struct Owner {
 Hardware io;B5qDp::Session<Hardware> session;uint32_t generation=0;
 uint64_t retryAt=0;bool accepted=false;
 Owner():session(io){}
 bool stop(){
  accepted=false;
  if(!session.stop()){IOLog("B5qDP: stop=retained clock=%x mx=%u\n",session.clock.failed,io.mxOwned);return false;}
  return io.close();
 }
 void update(const B5qDpPortState &p){
  if(!p.attached||!p.configured||!p.hpd||p.reverse<0||p.reverse>1||(p.lanes!=2&&p.lanes!=4)){
   stop();retryAt=0;return;
  }
  if(accepted&&generation==p.generation&&!p.hpdIrq&&io.wantedReverse==unsigned(p.reverse)){
   uint8_t status[6]{};bool healthy=io.connected()&&session.aux.dpcd(true,0x202,status,6)&&(status[2]&1);
   for(unsigned lane=0;lane<session.lanes;lane++)healthy=healthy&&((status[lane/2]>>(4*(lane&1)))&7)==7;
   if(healthy)return;
   IOLog("B5qDP: link-status lost aux=%u\n",unsigned(session.aux.error));
  }
  if(nowUs()<retryAt)return;
  if(!stop()){retryAt=nowUs()+1000000;return;}
  if(!io.open(p.reverse!=0)){
   IOLog("B5qDP: stage=power-gpio failed fault=%u\n",io.fault);io.close();retryAt=nowUs()+1000000;return;
  }
  const bool discovered=session.discover(p.lanes,p.reverse!=0);
  const bool trained=discovered&&session.train()&&!io.fault;
  IOLog("B5qDP: stage=link discovered=%u trained=%u error=%u aux=%u phy=%u clock=%x rate=%u lanes=%u modes=%u attempts=%u\n",
        discovered,trained,unsigned(session.error),unsigned(session.aux.error),session.phy.failed,session.clock.failed,
        session.rate,session.lanes,session.modes.count,session.attempts);
  if(!trained){stop();retryAt=nowUs()+1000000;return;}
  generation=p.generation;accepted=true;retryAt=0;
  IOLog("B5qDP: EDID %ux%u pclk=%u refresh_mHz=%u pin=%02x reverse=%d scanout=unattached\n",
        session.selected.width,session.selected.height,session.selected.pixelKHz,session.selected.refreshMilliHz(),p.pin,p.reverse);
 }
};
IOLock *lock;Owner *owner;
bool ensureLock(){
 if(__atomic_load_n(&lock,__ATOMIC_ACQUIRE))return true;
 IOLock *next=IOLockAlloc();if(!next)return false;IOLock *empty=nullptr;
 if(!__atomic_compare_exchange_n(&lock,&empty,next,false,__ATOMIC_RELEASE,__ATOMIC_ACQUIRE))IOLockFree(next);
 return true;
}
}
extern "C" bool b5q_dp_link_stop(void){
 // This runs on the same role worker as update. Before its first update
 // no DP hardware can be owned; stopping must not allocate kernel memory.
 IOLock *current=__atomic_load_n(&lock,__ATOMIC_ACQUIRE);if(!current)return true;
 IOLockLock(current);const bool ok=!owner||owner->stop();IOLockUnlock(current);return ok;
}
extern "C" void b5q_dp_link_update(const B5qDpPortState *state){
 if(!state)return;
 if(!B5qFeatures::option("b5q-dp",B5qFeatures::DisplayPort)){b5q_dp_link_stop();return;}
 if(!ensureLock())return;IOLockLock(lock);if(!owner)owner=new Owner;
 if(owner)owner->update(*state);IOLockUnlock(lock);
}
