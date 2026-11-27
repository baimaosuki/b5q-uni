/* SPDX-License-Identifier: GPL-2.0-only */
/* Native b5q DP0 link owner. QcomDwc3's role worker serializes this owner
 * with shared USB/DP combo changes. No apps_smmu MMIO or primary-display
 * bank access; training alone neither enables scanout nor publishes IOMFB. */
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceMemory.h>
#include <kern/clock.h>
#include <mach/mach_time.h>
#include <IOKit/IOPlatformExpert.h>
#include <IOKit/IOMemoryDescriptor.h>
#include <mach/kmod.h>
#include <pexpert/pexpert.h>
#include "B5qDpDma.h"
#include "B5qDpDisplay.h"
#include "B5qDpIrq.h"
#include "B5qDpPresentation.h"
#include "AppsSmmuLock.h"
#include "B5qDpDpuResources.h"
#include "B5qDpBoard.h"
#include "B5qDpPort.h"
#include "B5qDpSession.h"
#include "B5qFeatures.h"
#include "B5qMax77705.h"
#include "QcomRpmh.h"
extern "C" bool b5q_usb_cable_state(B5qMax77705::Cable *);
extern kmod_info_t g_kernel_kmod_info;
extern "C" void b5q_dp_display_static_init(void) __asm__("__GLOBAL__sub_I_B5qDpDisplay.cpp");
namespace {
using B5qDp::Block;
void barrier(){asm volatile("dsb sy":::"memory");}
uint64_t nowUs(){uint64_t ns=0;absolutetime_to_nanoseconds(mach_absolute_time(),&ns);return ns/1000;}
struct Window {
 IOMemoryMap *map=nullptr;volatile uint32_t *va=nullptr;
 Window()=default;Window(const Window&)=delete;Window&operator=(const Window&)=delete;
 bool open(uint64_t base,unsigned bytes,IOOptionBits cache=kIOMapInhibitCache){
  if(va)return true;auto *d=IODeviceMemory::withRange(base,bytes);
  map=d?d->map(kIOMapAnywhere|cache):nullptr;OSSafeReleaseNULL(d);
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
 bool dpBusy=false;
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
 bool openFailure(const char *step){
  IOLog("B5qDP: stage=hw-open failed step=%s gcc50018=%08x gcc39004=%08x disp9000=%08x dpBusy=%u sel=%08x/%08x en=%08x/%08x\n",
    step,gcc.va?gcc.va[0x50018/4]:0,gcc.va?gcc.va[0x39004/4]:0,disp.va?disp.va[0x9000/4]:0,
    dpBusy,sel.va?sel.va[0]:0,sel.va?sel.va[1]:0,en.va?en.va[0]:0,en.va?en.va[1]:0);return false;
 }
 bool open(bool reverse){
  fault=false;wantedReverse=reverse;sampled=nowUs();cablePresent=true;
  dpBusy=false;
  if(!dp.open(0xae90000,0x2000)||!phy.open(0x88ea000,0x1000)||
     !disp.open(0xaf00000,0x10000)||!gcc.open(0x100000,0x60000)||
     !dpu.open(0xae00000,0x84000)||!sel.open(0xf100000+180*0x1000,0x1000)||
     !en.open(0xf100000+183*0x1000,0x1000))return openFailure("map");
  // Original DP supplies share USB's already enabled ldoe1/ldoe3/ldof3/
  // ldob5 rails and GCC PHY GDSC. Do not become a second regulator owner.
  if(!(gcc.va[0x50018/4]&(1u<<31))||!(gcc.va[0x39004/4]&(1u<<31))||
     !(disp.va[0x9000/4]&(1u<<31)))return openFailure("gdsc");
  B5qDp::DpuResources resources;resources.inspect([&](unsigned off){return dpu.va[off/4];});
  dpBusy=resources.dpBusy;if(dpBusy)return openFailure("dpu-busy");
  // Original secdp_power_set_gpio, no aux-sel-inv/redriver on b5q:
  // first isolate active-low AUX enable, set CC polarity, then enable.
  if(!pins.begin(*this,reverse))return openFailure("aux-gpio");opened=true;return true;
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
 B5qDpPortState observed{};bool haveObserved=false;
 B5Q_DP_DMA_STATE dma{};Window pool;
 IOLock *scanLock=nullptr;IOService *display=nullptr,*provider=nullptr;
 B5qDp::Presentation presentation;uint32_t scanClosing=1;uint64_t frameCount=0;
 struct Transfer {IOMemoryDescriptor *memory;uint64_t stride;};
 struct ScanIo {
  Owner &owner;
  uint32_t read(unsigned off){return owner.io.read(Block::Dpu,off);}
  void write(unsigned off,uint32_t value){owner.io.write(Block::Dpu,off,value);}
  void barrier(){::barrier();}void delay(unsigned us){owner.io.delay(us);}
  uint64_t nowUs(){return ::nowUs();}
  bool dmaAllowed(uint64_t address,uint64_t bytes){
   return B5qDpPoolValid(&owner.dma)&&owner.pool.va&&address>=owner.dma.PoolBase&&
    address<=owner.dma.PoolBase+owner.dma.PoolBytes&&bytes<=owner.dma.PoolBase+owner.dma.PoolBytes-address;
  }
  bool fill(const B5qDp::ScanoutBuffer &b,uint64_t bytes){
   if(!dmaAllowed(b.address,bytes))return false;
   volatile uint32_t *out=owner.pool.va+(b.address-owner.dma.PoolBase)/4;
   for(uint64_t i=0;i<bytes/4;i++)out[i]=0xff000000;return true;
  }
  bool clean(const B5qDp::ScanoutBuffer &b,uint64_t bytes){
   if(!dmaAllowed(b.address,bytes))return false;
   const uintptr_t start=reinterpret_cast<uintptr_t>(owner.pool.va)+(b.address-owner.dma.PoolBase);
   for(uintptr_t at=start&~uintptr_t(63);at<start+bytes;at+=64)asm volatile("dc cvac, %0"::"r"(at):"memory");
   barrier();return true; // Explicit clean for the retained display domain.
  }
  bool copy(const B5qDp::ScanoutBuffer &b,const void *source,const B5qDp::Mode &m,unsigned stride){
   const auto &t=*static_cast<const Transfer*>(source);
   if(!t.memory||t.stride<uint64_t(m.width)*4||t.stride>UINT64_MAX/m.height||
      t.stride*m.height>t.memory->getLength()||!dmaAllowed(b.address,uint64_t(stride)*m.height))return false;
   // Descriptor readBytes may use wide/unaligned stores. Stage one normal
   // RAM row, then scalar-store pixels into the uncached scanout mapping.
   auto *row=static_cast<uint32_t*>(IOMallocData(m.width*4));if(!row)return false;
   bool ok=t.memory->prepare(kIODirectionOut)==kIOReturnSuccess;
   const bool prepared=ok;
   for(unsigned y=0;ok&&y<m.height;y++){
    ok=t.memory->readBytes(uint64_t(y)*t.stride,row,m.width*4)==m.width*4;
    if(ok){volatile uint32_t *out=owner.pool.va+(b.address-owner.dma.PoolBase+uint64_t(y)*stride)/4;
     for(unsigned x=0;x<m.width;x++)out[x]=row[x];}
   }
   if(prepared)t.memory->complete(kIODirectionOut);IOFreeData(row,m.width*4);return ok;
  }
  bool arm(B5qDp::Presentation *){return b5q_dp_irq_start(&owner,Owner::frame);}
  bool disarm(){return b5q_dp_irq_stop();}
  bool video(){return owner.session.video();}
  bool stopVideo(){if(owner.session.streaming){owner.session.controller.stop();owner.session.streaming=false;}return true;}
  void notify(uint32_t,uint64_t){}
 } scan{*this};
 Owner():session(io){}
 static void frame(void *context,uint32_t counter,uint64_t timestamp){
  auto &self=*static_cast<Owner*>(context);if(__atomic_load_n(&self.scanClosing,__ATOMIC_ACQUIRE))return;
  IOLockLock(self.scanLock);
  const uint64_t tag=self.presentation.frame(self.scan,counter,timestamp);
  IOService *target=self.display;if(target)target->retain();
  if(++self.frameCount<=3||self.frameCount%600==0)IOLog("B5qDP: vsync frame=%u total=%llu tag=%llu\n",counter,self.frameCount,tag);
  IOLockUnlock(self.scanLock);
  if(target){b5q_dp_display_frame(target,tag,counter,timestamp);target->release();}
 }
 static bool present(void *context,IOMemoryDescriptor *memory,uint64_t stride,bool blank,uint64_t tag){
  auto &self=*static_cast<Owner*>(context);if(__atomic_load_n(&self.scanClosing,__ATOMIC_ACQUIRE))return false;
  Transfer transfer{memory,stride};IOLockLock(self.scanLock);
  const bool ok=!__atomic_load_n(&self.scanClosing,__ATOMIC_ACQUIRE)&&self.presentation.offer(self.scan,tag,&transfer,blank);
  IOLockUnlock(self.scanLock);return ok;
 }
 static bool drain(void *context){
  auto &self=*static_cast<Owner*>(context);__atomic_store_n(&self.scanClosing,1u,__ATOMIC_RELEASE);
  // Never hold scanLock while waiting for the IRQ worker: it may be
  // waiting on that lock or entering the IOMFB work loop.
  if(!b5q_dp_irq_stop())return false;
  if(!self.scanLock)return true;
  IOLockLock(self.scanLock);uint64_t cancelled=0;const bool ok=self.presentation.stop(self.scan,cancelled);
  IOLockUnlock(self.scanLock);
  if(cancelled)IOLog("B5qDP: cancelled flip tag=%llu\n",cancelled);return ok;
 }
 bool poolReady(){
  if(!scanLock)scanLock=IOLockAlloc();if(!scanLock){
   IOLog("B5qDP: stage=pool-ready failed ready=0 valid=0 pe_rc=-1 pe_base=0 dma_base=0 row=0 h=0 reason=lock\n");return false;}
  auto *chosen=IORegistryEntry::fromPath("/chosen",gIODTPlane);
  auto *flag=chosen?OSDynamicCast(OSData,chosen->getProperty("b5q-dp-dma-ready")):nullptr;
  auto *state=chosen?OSDynamicCast(OSData,chosen->getProperty("b5q-dp-dma-state")):nullptr;
  uint32_t ready=0;dma={};
  if(flag&&flag->getLength()==4)memcpy(&ready,flag->getBytesNoCopy(),4);
  if(state&&state->getLength()==sizeof(dma))memcpy(&dma,state->getBytesNoCopy(),sizeof(dma));
  OSSafeReleaseNULL(chosen);
  IOLog("B5qDP: dma-ready=%u primary=%llx..%llx pool=%llx+%llx prepare=%llx retain=%llx\n",
        ready,dma.FrameBufferBase,dma.PrimaryEnd,dma.PoolBase,dma.PoolBytes,dma.PrepareStatus,dma.RetentionStatus);
  PE_Video primary{};
  const bool valid=B5qDpPoolValid(&dma);
  const int pe_rc=ready==1&&valid?PE_current_console(&primary):-1;
  const bool ok=ready==1&&valid&&!pe_rc&&
   primary.v_baseAddr==dma.FrameBufferBase&&primary.v_rowBytes&&primary.v_height&&
   uint64_t(primary.v_rowBytes)*primary.v_height<=dma.PrimaryEnd-dma.FrameBufferBase&&
   pool.open(dma.PoolBase,unsigned(dma.PoolBytes),kIOMapCopybackCache);
  if(!ok)IOLog("B5qDP: stage=pool-ready failed ready=%u valid=%u pe_rc=%d pe_base=%llx dma_base=%llx row=%lu h=%lu reason=%s\n",
   ready,valid,pe_rc,uint64_t(primary.v_baseAddr),dma.FrameBufferBase,
   (unsigned long)primary.v_rowBytes,(unsigned long)primary.v_height,
   ready!=1?"handoff":!valid?"pool-invalid":pe_rc?"console":primary.v_baseAddr!=dma.FrameBufferBase?"console-base":
   !primary.v_rowBytes||!primary.v_height?"console-size":
   uint64_t(primary.v_rowBytes)*primary.v_height>dma.PrimaryEnd-dma.FrameBufferBase?"console-range":"map");
  return ok;
 }
 bool startDisplay(){
  const auto &m=session.selected;const unsigned stride=B5qDp::Modes::scanoutStride(m);
  const uint64_t slot=B5qDp::Modes::scanoutSlot(m);
  auto failure=[&](const char *step){
   IOLog("B5qDP: stage=scanout failed step=%s width=%u height=%u slot=%llu halfPool=%llu dpuActive=%u\n",
     step,m.width,m.height,slot,dma.PoolBytes/2,presentation.dpu.active);return false;};
  static bool initialized=false;
  if(!initialized){void *handle=OSMetaClass::preModLoad(g_kernel_kmod_info.name);
   if(!handle)return failure("static-init");b5q_dp_display_static_init();if(OSMetaClass::postModLoad(handle))return failure("static-init");initialized=true;}
  B5qDp::DpuResources r;r.inspect([&](unsigned off){return io.read(Block::Dpu,off);});
  if(!r.choose(m.width))return failure("dpu-choose");
  if(slot>dma.PoolBytes/2)return failure("pool-slot");
  const B5qDp::ScanoutBuffer buffers[2]={{dma.PoolBase,slot},{dma.PoolBase+slot,slot}};
  IOLockLock(scanLock);__atomic_store_n(&scanClosing,0u,__ATOMIC_RELEASE);
  const bool started=presentation.begin(scan,r,m,buffers,stride);IOLockUnlock(scanLock);
  if(!started){failure("presentation-begin");drain(this);return false;}
  provider=new IOService;
  if(!provider||!provider->init()||!provider->attach(IOService::getPlatform()))return failure("provider");
  provider->setName("B5qDisplayPort");
  B5qDpDisplayConfig config{};config.mode=m;config.edidBytes=session.edidBytes;
  memcpy(config.edid,session.edid,config.edidBytes);config.context=this;config.present=present;config.drain=drain;
  IOService *next=b5q_dp_display_create(provider,&config);
  IOLockLock(scanLock);display=next;IOLockUnlock(scanLock);
  if(!display)return failure("iomfb-create");
  return true;
 }
 bool stop(){
  accepted=false;
  if(display&&!b5q_dp_display_disconnect(display))return false;
  if(!display&&!drain(this))return false;
  if(display){display->terminate(kIOServiceSynchronous);display->release();display=nullptr;}
  if(provider){if(provider->getProvider())provider->detach(provider->getProvider());provider->release();provider=nullptr;}
  if(!session.stop()){IOLog("B5qDP: stop=retained clock=%x mx=%u\n",session.clock.failed,io.mxOwned);return false;}
  pool.close();dma={};
  return io.close();
 }
 void update(const B5qDpPortState &p){
  if(!haveObserved||observed.attached!=p.attached||observed.configured!=p.configured||observed.hpd!=p.hpd||
     observed.hpdIrq!=p.hpdIrq||observed.lanes!=p.lanes||observed.pin!=p.pin||observed.reverse!=p.reverse||
     observed.phase!=p.phase||observed.error!=p.error||observed.generation!=p.generation){
   IOLog("B5qDP: port phase=%u err=%u att=%u cfg=%u hpd=%u irq=%u lanes=%u pin=%02x rev=%d gen=%u\n",
    p.phase,p.error,p.attached,p.configured,p.hpd,p.hpdIrq,p.lanes,p.pin,p.reverse,p.generation);
   observed=p;haveObserved=true;
  }
  if(!p.attached||!p.configured||!p.hpd||p.reverse<0||p.reverse>1||(p.lanes!=2&&p.lanes!=4)){
   stop();retryAt=0;return;
  }
  if(accepted&&generation==p.generation&&!p.hpdIrq&&io.wantedReverse==unsigned(p.reverse)){
   IOLockLock(scanLock);const bool stalled=presentation.timedOut(scan);IOLockUnlock(scanLock);
   uint8_t status[6]{};bool healthy=io.connected()&&session.aux.dpcd(true,0x202,status,6)&&(status[2]&1);
   for(unsigned lane=0;lane<session.lanes;lane++)healthy=healthy&&((status[lane/2]>>(4*(lane&1)))&7)==7;
   if(healthy&&!stalled)return;
   IOLog("B5qDP: link-status lost aux=%u\n",unsigned(session.aux.error));
  }
  if(nowUs()<retryAt)return;
  if(!stop()){retryAt=nowUs()+1000000;return;}
  if(!poolReady()){io.close();retryAt=nowUs()+1000000;return;}
  if(!io.open(p.reverse!=0)){io.close();retryAt=nowUs()+1000000;return;}
  const bool discovered=session.discover(p.lanes,p.reverse!=0);
  IOLog("B5qDP: discover ok=%u step=%u err=%u aux=%u aux_sts=%08x aux_tx=%u rev=%02x rate=%u lanes=%u enh=%u edid=%u dpcd=%02x %02x %02x %02x %02x %02x %02x %02x\n",
   discovered,session.discoverStep,unsigned(session.error),unsigned(session.aux.error),session.aux.lastStatus,session.aux.transactions,
   session.caps.revision,session.caps.rate,session.caps.lanes,session.caps.enhanced,session.edidBytes,
   session.dpcd[0],session.dpcd[1],session.dpcd[2],session.dpcd[3],session.dpcd[4],session.dpcd[5],session.dpcd[6],session.dpcd[7]);
  if(discovered){const unsigned advertised=session.modes.count;session.modes.fitPool(dma.PoolBytes);
   IOLog("B5qDP: EDID pool-filter advertised=%u fitting=%u bytes=%llu\n",advertised,session.modes.count,dma.PoolBytes);}
  const bool trained=discovered&&session.modes.count&&session.train()&&!io.fault;
  IOLog("B5qDP: stage=link discovered=%u trained=%u error=%u aux=%u phy=%u clock=%x rate=%u lanes=%u modes=%u attempts=%u train_err=%u phy_last=%08x\n",
        discovered,trained,unsigned(session.error),unsigned(session.aux.error),session.phy.failed,session.clock.failed,
        session.rate,session.lanes,session.modes.count,session.attempts,unsigned(session.trainError),session.phy.last);
  if(!trained){stop();retryAt=nowUs()+1000000;return;}
  if(!startDisplay()){IOLog("B5qDP: stage=scanout failed retained=%u\n",presentation.dpu.active);stop();retryAt=nowUs()+1000000;return;}
  generation=p.generation;accepted=true;retryAt=0;
  IOLog("B5qDP: EDID %ux%u pclk=%u refresh_mHz=%u pin=%02x reverse=%d scanout=online\n",
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
 const bool enabled=B5qFeatures::option("b5q-dp",B5qFeatures::DisplayPort);
 static uint32_t featureLogged=0;
 if(!__atomic_exchange_n(&featureLogged,1u,__ATOMIC_RELAXED))IOLog("B5qDP: feature b5q-dp=%u\n",enabled);
 if(!enabled){b5q_dp_link_stop();return;}
 if(!ensureLock()){static bool logged;if(!logged){logged=true;IOLog("B5qDP: stage=owner-lock result=no-memory\n");}return;}
 IOLockLock(lock);if(!owner)owner=new Owner;
 if(!owner){static bool logged;if(!logged){logged=true;IOLog("B5qDP: stage=owner-allocation result=no-memory\n");}}
 if(owner)owner->update(*state);IOLockUnlock(lock);
}
