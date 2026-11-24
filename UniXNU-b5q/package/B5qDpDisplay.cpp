/* SPDX-License-Identifier: BSD-2-Clause-Patent */
/* macOS 26C5035r external IOMFB adapter. Original-family ABI/notifications
 * are shared with the accepted primary backend. This adapter neither
 * borrows the PE console nor authorizes or maps Display DMA. A concrete
 * retained scanout backend must exist before this service can be created. */
#include "OriginalLegacyFramebufferABI.h"
#include "NativeLegacyRequest.h"
#include "B5qDpDisplay.h"
#include "B5qDpIoav.h"
#include <IOKit/IOLib.h>
#include <IOKit/IOMemoryDescriptor.h>
#include <IOKit/IOWorkLoop.h>
#include <IOKit/IOUserClient.h>
#include <IOKit/IOTimerEventSource.h>
#include <libkern/c++/OSArray.h>
#include <libkern/c++/OSData.h>
#include <libkern/c++/OSDictionary.h>
#include <libkern/c++/OSNumber.h>
#include <libkern/c++/OSString.h>
#include <libkern/OSKextLib.h>
#include <mach/mach_time.h>
#include <kern/clock.h>
extern "C" IOMemoryDescriptor *native_legacy_surface_descriptor(OSObject *);
extern "C" uint64_t native_legacy_surface_width(OSObject *),native_legacy_surface_height(OSObject *);
extern "C" uint64_t native_legacy_surface_stride(OSObject *),native_legacy_surface_allocation(OSObject *);
extern "C" uint32_t native_legacy_surface_format(OSObject *),native_legacy_surface_planes(OSObject *);
extern "C" bool native_adreno_fences(uint32_t *,uint32_t *) __attribute__((weak_import));
extern "C" void native_legacy_vsync_notify(void *,uint64_t,uint64_t,uint64_t);
extern "C" uint64_t mach_continuous_time(void);
extern "C" bool native_legacy_set_refresh_properties(void *);
extern "C" void native_legacy_hotplug_notify(void *,uint64_t);
extern "C" OSObject *native_legacy_ioav_timing(const void *,uint32_t,uint32_t);
extern "C" void native_legacy_ioav_timing_colors(OSObject *,OSArray *);
extern "C" OSObject *native_legacy_ioav_color(uint32_t,uint32_t,uint32_t,uint32_t,uint32_t,uint32_t,bool,
 const OSDictionary *,const OSDictionary *,const OSDictionary *,const OSSet *);
extern "C" void native_legacy_swap_info_dispatch(void *,void *);
extern "C" IOReturn nativeSendAsyncResult(io_user_reference_t *,IOReturn,io_user_reference_t *,uint32_t,IOOptionBits)
 __asm("__ZN12IOUserClient28sendAsyncResult64WithOptionsEPyiS0_jj");
class B5qDpDisplay:public IOMobileFramebufferLegacy {
 OSDeclareDefaultStructors(B5qDpDisplay)
 B5qDpDisplayConfig config;
 IOTimerEventSource *fenceTimer;
 IOService *identity;
 bool live,kicking,rekick,fenceCaptured,teardownPinned;
 uint32_t closing;
 const OriginalLegacySwapRequest *validated[8],*offered,*fenceFor;
 uint64_t generation,offeredTag,frames,retired;
 uint32_t fenceTarget;
 static constexpr uint64_t kDisplayColorID=100,kDisplayTimingID=1000;
 static bool number(OSDictionary *d,const char *key,uint64_t v){
  auto *n=OSNumber::withNumber(v,32);bool ok=n&&d->setObject(key,n);OSSafeReleaseNULL(n);return ok;
 }
 static bool string(OSDictionary *d,const char *key,const char *text){
  auto *s=OSString::withCString(text);bool ok=s&&d->setObject(key,s);OSSafeReleaseNULL(s);return ok;
 }
 bool isClosing()const{return __atomic_load_n(&closing,__ATOMIC_ACQUIRE)!=0;}
 static void ident(OSObject *element,uint64_t id){
  uint32_t score=uint32_t(id);auto *p=reinterpret_cast<uint8_t*>(element);
  memcpy(p+16,&id,8);memcpy(p+24,&score,4); // actual 26C5035r IOAVElement
 }
 bool known(const OriginalLegacySwapRequest *r){for(auto *v:validated)if(v==r)return true;return false;}
 void forget(const OriginalLegacySwapRequest *r){for(auto &v:validated)if(v==r)v=nullptr;}
 bool remember(const OriginalLegacySwapRequest *r){
  if(known(r))return true;for(auto &v:validated)if(!v){v=r;return true;}return false;
 }
 bool publishMode(){
  B5qDp::IoavTiming raw;if(!raw.make(config.mode))return false;
  OSObject *timing=native_legacy_ioav_timing(raw.words,2,4);
  OSObject *color=native_legacy_ioav_color(2,8,0,0,0,16,false,nullptr,nullptr,nullptr,nullptr);
  OSArray *colors=OSArray::withCapacity(1),*timings=OSArray::withCapacity(1);
  OSDictionary *attributes=OSDictionary::withCapacity(8),*transport=OSDictionary::withCapacity(2),
   *layers=OSDictionary::withCapacity(1),*source=OSDictionary::withCapacity(5),*scaling=OSDictionary::withCapacity(2);
  OSData *edid=OSData::withBytes(config.edid,config.edidBytes);bool ok=false;
  do {
   if(!timing||!color||!colors||!timings||!attributes||!transport||!layers||!source||!scaling||!edid)break;
   ident(color,kDisplayColorID);ident(timing,kDisplayTimingID);
   if(!colors->setObject(color)||!timings->setObject(timing))break;
   native_legacy_ioav_timing_colors(timing,colors);
   if(!number(attributes,"NativeFormatHorizontalPixels",config.mode.width)||
      !number(attributes,"NativeFormatVerticalPixels",config.mode.height)||
      !number(attributes,"PreciseAspectRatio",(uint64_t(config.mode.width)<<16)/config.mode.height)||
      !attributes->setObject("DefaultColorSpaceIsSRGB",kOSBooleanTrue)||
      !string(transport,"Upstream","DisplayPort")||!string(transport,"Downstream","DisplayPort")||
      !number(layers,"MaxNumLayers",1))break;
   if(!number(source,"MaxSrcBufferWidth",16384)||!number(source,"MaxSrcBufferHeight",16384)||
      !number(source,"MaxSrcRectWidth",5120)||!number(source,"MaxSrcRectTotal",0)||
      !number(source,"IOMFBMaxCompressedSizeInBytes",0)||
      !number(scaling,"RGBLayer_MinScaleFraction",4)||!number(scaling,"RGBLayer_MaxScale",4))break;
   if(!setProperty("DisplayAttributes",attributes)||!setProperty("Transport",transport)||
      !setProperty("ColorElements",colors)||!setProperty("TimingElements",timings)||
      !setProperty("IOMFBNumLayers",layers)||!setProperty("NativeDisplayEDID",edid)||
      !setProperty("IOMFBMaxSrcPixels",source)||!setProperty("IOMFBScalingLimits",scaling))break;
   setProperty("built-in",false);setProperty("B5qExternalDisplay",true);
   setProperty("DisplayWidth",config.mode.width,32);setProperty("DisplayHeight",config.mode.height,32);
   ok=true;
  }while(false);
  OSSafeReleaseNULL(edid);OSSafeReleaseNULL(layers);OSSafeReleaseNULL(transport);OSSafeReleaseNULL(attributes);
  OSSafeReleaseNULL(source);OSSafeReleaseNULL(scaling);
  OSSafeReleaseNULL(timings);OSSafeReleaseNULL(colors);OSSafeReleaseNULL(color);OSSafeReleaseNULL(timing);return ok;
 }
 static void fenceFired(OSObject *owner,IOTimerEventSource *){static_cast<B5qDpDisplay*>(owner)->kickSwapQueue();}
 bool producerComplete(const OriginalLegacySwapRequest *r){
  // A failed/missing GPU query is never treated as completion. This
  // backend is for the verified hardware-GPU profile, not CPU-only mode.
  if(fenceFor!=r){fenceFor=r;fenceCaptured=false;}
  uint32_t submitted=0,done=0;
  if(&native_adreno_fences&&native_adreno_fences(&submitted,&done)){
   if(!fenceCaptured){fenceTarget=submitted;fenceCaptured=true;}
   if(int32_t(done-fenceTarget)>=0){fenceFor=nullptr;return true;}
  }
  if(fenceTimer)fenceTimer->setTimeoutUS(200);return false;
 }
 void kickOnce(){
  if(!live||isClosing()||offered)return;
  const auto *r=pendingSwapRequest();if(!r||!known(r))return;
  OSObject *surface=nullptr;memcpy(&surface,reinterpret_cast<const uint8_t*>(r)+kRequestSurfaces,8);
  IOMemoryDescriptor *memory=nullptr;uint64_t stride=0;
  if(surface){if(!producerComplete(r))return;memory=native_legacy_surface_descriptor(surface);stride=native_legacy_surface_stride(surface);}
  // Set the tag before calling the backend: its implementation must not
  // reenter this work loop synchronously, but cancellation can reenter.
  const uint64_t tag=++generation;if(!tag){generation++;return;}
  offered=r;offeredTag=tag;
  if(!config.present(config.context,memory,stride,!surface,tag)){offered=nullptr;offeredTag=0;}
 }
public:
 bool configure(const B5qDpDisplayConfig &input){
  if(!input.context||!input.present||!input.drain||!input.mode.valid()||
     input.edidBytes<128||input.edidBytes>sizeof(input.edid)||(input.edidBytes&127))return false;
  B5qDp::Modes parsed;if(!parsed.parse(input.edid,input.edidBytes))return false;
  bool found=false;for(unsigned i=0;i<parsed.count;i++){
   const auto &a=parsed.values[i],&b=input.mode;
   found=found||(a.pixelKHz==b.pixelKHz&&a.width==b.width&&a.height==b.height&&a.hBlank==b.hBlank&&a.vBlank==b.vBlank&&
    a.hFront==b.hFront&&a.hSync==b.hSync&&a.vFront==b.vFront&&a.vSync==b.vSync&&a.hPositive==b.hPositive&&a.vPositive==b.vPositive);
  }
  if(!found)return false;config=input;return true;
 }
 bool startHardware()override{
  installBootDimensions(config.mode.width,config.mode.height);
  return config.context&&installDefaultSurface(config.mode.width,config.mode.height)&&publishMode();
 }
 bool start(IOService *provider)override{
  if(!IOMobileFramebufferLegacy::start(provider))return false;
  IOWorkLoop *loop=getWorkLoop();fenceTimer=IOTimerEventSource::timerEventSource(this,fenceFired);
  if(!loop||!fenceTimer||loop->addEventSource(fenceTimer)!=kIOReturnSuccess){
   OSSafeReleaseNULL(fenceTimer);IOMobileFramebufferLegacy::stop(provider);return false;
  }
  auto *object=OSMetaClass::allocClassWithName("IODisplay");identity=OSDynamicCast(IOService,object);
  if(!identity||!identity->init()||!identity->attach(this)){
   OSSafeReleaseNULL(object);identity=nullptr;loop->removeEventSource(fenceTimer);OSSafeReleaseNULL(fenceTimer);
   IOMobileFramebufferLegacy::stop(provider);return false;
  }
  identity->setProperty("IODisplayEDID",config.edid,config.edidBytes);
  identity->setProperty("DisplayVendorID",uint64_t(config.edid[8]<<8|config.edid[9]),32);
  identity->setProperty("DisplayProductID",uint64_t(config.edid[10]|config.edid[11]<<8),32);
  identity->setName("B5qExternalDisplayIdentity");live=true;
  OriginalLegacyStateRequest state={1,0,0,1,1,{}};applyStateRequest(&state,false);
  native_legacy_set_refresh_properties(this);native_legacy_hotplug_notify(this,1);
  IOLog("B5qDP: IOMFB attached %ux%u refresh_mHz=%u\n",config.mode.width,config.mode.height,config.mode.refreshMilliHz());return true;
 }
 bool disconnect(){
  // The scanout owner calls this outside the family gate and without its
  // hardware mutex: an in-flight IRQ worker may need the family gate.
  __atomic_store_n(&closing,1u,__ATOMIC_RELEASE);if(fenceTimer)fenceTimer->cancelTimeout();
  if(config.context&&!config.drain(config.context))return false;
  struct Args{B5qDpDisplay *self;}args={this};
  auto action=[](OSObject *,void *p,void *,void *,void *)->IOReturn{
   auto *self=static_cast<Args*>(p)->self;self->live=false;self->offered=nullptr;self->offeredTag=0;
   for(auto &v:self->validated)v=nullptr;self->fenceFor=nullptr;
   native_legacy_hotplug_notify(self,0);OriginalLegacyStateRequest state={1,0,0,0,1,{}};self->applyStateRequest(&state,false);return kIOReturnSuccess;
  };
  IOWorkLoop *loop=getWorkLoop();return loop&&loop->runAction(action,this,&args)==kIOReturnSuccess;
 }
 void stop(IOService *provider)override{
  // Normal teardown is preceded by successful disconnect. Unexpected
  // stop retains the allocation/context until the DMA owner drains it.
  if(live&&!disconnect()){if(!teardownPinned){retain();teardownPinned=true;}IOLog("B5qDP: IOMFB teardown retained\n");return;}
  if(fenceTimer){fenceTimer->cancelTimeout();if(auto *loop=getWorkLoop())loop->removeEventSource(fenceTimer);OSSafeReleaseNULL(fenceTimer);}
  if(identity){identity->detach(this);OSSafeReleaseNULL(identity);}IOMobileFramebufferLegacy::stop(provider);
  if(teardownPinned){teardownPinned=false;release();}
 }
 void free()override{IOMobileFramebufferLegacy::free();}
 bool isMainDisplay()override{return false;}
 void registerService(IOOptionBits options=0)override{IOService::registerService(options);}
 bool getRefreshAttributes(uint64_t *words,bool fixed)override{
  if(!words||!IOMobileFramebufferLegacy::getRefreshAttributes(words,fixed))return false;
  uint64_t total=uint64_t(config.mode.totalWidth())*config.mode.totalHeight();
  uint64_t interval=((total<<32)+uint64_t(config.mode.pixelKHz)*500)/(uint64_t(config.mode.pixelKHz)*1000);
  uint64_t absolute=0;nanoseconds_to_absolutetime((interval*1000000000)>>32,&absolute);
  words[0]=words[2]=interval;words[1]=words[3]=absolute;return true;
 }
 IOReturn getDotPitch(uint32_t *pitch)override{if(!pitch)return kIOReturnBadArgument;*pitch=0;return kIOReturnUnsupported;}
 IOReturn supportedFrameInfo(uint32_t,uint32_t *count,char *key,uint32_t *mask)override{
  if(!count||!key||!mask)return kIOReturnBadArgument;*count=*mask=0;bzero(key,64);return kIOReturnUnsupported;
 }
 bool validateSwap(const OriginalLegacySwapRequest *r)override{
  if(!r||!live||isClosing())return false;const auto *bytes=reinterpret_cast<const uint8_t*>(r);
  auto word=[&](unsigned off){uint32_t value;memcpy(&value,bytes+off,4);return value;};
  OSObject *surfaces[4]{};memcpy(surfaces,bytes+kRequestSurfaces,sizeof surfaces);
  bool valid=!surfaces[1]&&!surfaces[2]&&!surfaces[3]&&word(kRequestDims)==config.mode.width&&word(kRequestDims+4)==config.mode.height;
  for(unsigned off=kRequestOptions;off<=kRequestOptions+8;off+=4)valid=valid&&!word(off);
  if(!surfaces[0])valid=valid&&native_legacy_blank_state(word(kRequestMasks),word(kRequestMasks+4),word(kRequestMasks+8));
  else{
   auto *surface=surfaces[0];valid=valid&&surface->metaCast("IOSurface")&&
    native_legacy_single_layer_state(word(kRequestMasks),word(kRequestMasks+4),word(kRequestMasks+8));
   const unsigned rects[]={kRequestRect0,kRequestRect1};
   for(unsigned off:rects)valid=valid&&!word(off)&&!word(off+4)&&word(off+8)==config.mode.width&&word(off+12)==config.mode.height;
   if(valid){auto *memory=native_legacy_surface_descriptor(surface);const uint64_t stride=native_legacy_surface_stride(surface);
    const uint64_t bytes=native_legacy_surface_allocation(surface),height=config.mode.height,width=config.mode.width;
    valid=memory&&native_legacy_surface_format(surface)==0x42475241&&!native_legacy_surface_planes(surface)&&
     native_legacy_surface_width(surface)>=width&&native_legacy_surface_height(surface)>=height&&stride>=width*4&&
     stride<=UINT64_MAX/height&&stride*height<=bytes&&bytes<=memory->getLength();
   }
  }
  if(valid)return remember(r);forget(r);return false;
 }
 void kickSwapQueue()override{
  if(kicking){rekick=true;return;}kicking=true;do{rekick=false;kickOnce();}while(rekick&&!offered);kicking=false;
 }
 bool cancelSwapsAfterTimeout()override{
  if(fenceTimer)fenceTimer->cancelTimeout();for(auto &v:validated)v=nullptr;offered=nullptr;offeredTag=0;fenceFor=nullptr;return false;
 }
 void frame(uint64_t tag,uint32_t counter,uint64_t timestamp){
  struct Args{B5qDpDisplay *self;uint64_t tag;uint32_t counter;uint64_t time;}args={this,tag,counter,timestamp};
  auto action=[](OSObject *,void *p,void *,void *,void *)->IOReturn{
   auto &a=*static_cast<Args*>(p);auto *self=a.self;if(!self->live||self->isClosing())return kIOReturnNotReady;
   self->frames++;uint64_t interval=0;nanoseconds_to_absolutetime(uint64_t(self->config.mode.totalWidth())*self->config.mode.totalHeight()*1000000/self->config.mode.pixelKHz,&interval);
   native_legacy_vsync_notify(self,a.time,mach_continuous_time(),interval);
   if(a.tag&&a.tag==self->offeredTag){const auto *r=self->offered;
    self->offered=nullptr;self->offeredTag=0;
    if(r&&self->known(r)&&self->pendingSwapRequest()==r&&self->activateOnlyPendingSwap(r)){
     self->forget(r);self->retired++;self->IOMobileFramebufferLegacy::completeCurrentSwap();
    }
   }
   self->kickSwapQueue();return kIOReturnSuccess;
  };
  if(auto *loop=getWorkLoop())loop->runAction(action,this,&args);
 }
 IOReturn setDigitalOutMode(uint32_t color,uint32_t timing)override{
  if(color!=kDisplayColorID||timing!=kDisplayTimingID)return kIOReturnBadArgument;
  setProperty("DPTimingModeId",timing,32);return kIOReturnSuccess;
 }
 IOReturn setDisplayDevice(uint32_t)override{return kIOReturnSuccess;}
 IOReturn setGammaTable(void *)override{return kIOReturnUnsupported;}
 IOReturn setColorRemapMode(uint32_t mode)override{return mode==6?kIOReturnSuccess:kIOReturnUnsupported;}
 IOReturn getColorRemapMode(uint32_t *mode)override{if(!mode)return kIOReturnBadArgument;*mode=6;return kIOReturnSuccess;}
 IOReturn swapSetColorMatrix(void *,uint32_t,uint32_t)override{return kIOReturnUnsupported;}
    struct SwapInfo {uint32_t swapID,pad;uint64_t words[5];};
    static_assert(sizeof(SwapInfo)==48,"IOMobileFramebufferLegacy::SwapInfoBlob");
    static constexpr unsigned kSwapInfoRing=6;
    SwapInfo swapInfo[kSwapInfoRing];   // no initializers: IOKit objects are allocated zeroed (see validatedAt)
    unsigned swapInfoRead,swapInfoWrite;
    IOReturn collectCompletionReports(uint32_t swapID,void *,uint32_t *,uint32_t) override {
        auto self=reinterpret_cast<unsigned char *>(this);
        const unsigned char *swap=nullptr;memcpy(&swap,self+kLegacyCurrentSwap,sizeof(swap));
        uint32_t dropped=0;
        if(swap)memcpy(&dropped,swap+kRequestDropReasons,4);
        if(!swap || dropped)return kIOReturnUnsupported;
        SwapInfo &info=swapInfo[swapInfoWrite];
        info={};info.swapID=swapID;
        memcpy(&info.words[0],self+kLegacySwapInfoTime,8);
        memcpy(&info.words[2],swap+kRequestSwapInfoA,8);
        uint32_t second=0;memcpy(&second,swap+kRequestSwapInfoB,4);info.words[3]=second;
        uint16_t held=0;memcpy(&held,self+kLegacySwapInfoHeld,2);
        if(held){swapInfoWrite=(swapInfoWrite+1)%kSwapInfoRing;return kIOReturnSuccess;}
        for(;swapInfoRead!=swapInfoWrite;swapInfoRead=(swapInfoRead+1)%kSwapInfoRing)native_legacy_swap_info_dispatch(this,&swapInfo[swapInfoRead]);
        native_legacy_swap_info_dispatch(this,&info);
        return kIOReturnSuccess;
    }
    // The client's async result: the mask, the swap ID and each word the mask asks for (word 1 is the time since its previous
    // notification), as 64-bit values or, with mask bit 31, 32-bit halves; at most 12 values.
    IOReturn doSwapInfoNotify(void *request,const void *blob) override {
        auto r=static_cast<unsigned char *>(request);
        auto info=static_cast<const SwapInfo *>(blob);
        uint32_t mask=0;memcpy(&mask,r+kNotifyMask,4);
        uint64_t last=0;memcpy(&last,r+kNotifyLastTime,8);
        io_user_reference_t args[12]={mask,info->swapID};
        unsigned count=2;
        for(unsigned word=0;word<5;++word) {
            if(!(mask>>word&1))continue;
            const uint64_t value=word==1?info->words[0]-last:info->words[word];
            const unsigned need=mask>>31?2:1;
            if(count+need>12){IOLog("IOMFB Packer put: ran out of space\n");continue;}
            if(need==2){args[count++]=uint32_t(value);args[count++]=value>>32;}
            else args[count++]=value;
        }
        memcpy(r+kNotifyLastTime,&info->words[0],8);
        return nativeSendAsyncResult(reinterpret_cast<io_user_reference_t *>(r+kNotifyAsyncReference),kIOReturnSuccess,args,count,
                                     kIOUserNotifyOptionCanDrop);
    }
    // Swap info notifications (type 3) keep their word mask in the request; the display has no other notification type.
    IOReturn setNotifyTagMaskGated(uint32_t type,void *request,uint32_t mask) override {
        if(type!=3)return kIOReturnBadArgument;
        memcpy(static_cast<unsigned char *>(request)+kNotifyMask,&mask,4);return kIOReturnSuccess;
    }
    // No factory calibration, frame-info trace or CRC on a GOP scanout.
    IOReturn factoryPortal(void *,task_t) override {return kIOReturnUnsupported;}
    IOReturn executeFactoryConfigurations() override {return kIOReturnUnsupported;}
    IOReturn setFrameInfoNotificationState(void *,bool) override {return kIOReturnSuccess;}
    IOReturn notifyCrcReady(uint32_t) override {return kIOReturnSuccess;}

};
OSDefineMetaClassAndStructors(B5qDpDisplay,IOMobileFramebufferLegacy)
extern "C" IOService *b5q_dp_display_create(IOService *provider,const B5qDpDisplayConfig *config){
 if(!provider||!config)return nullptr;
 const OSReturn graphics=OSKextLoadKextWithIdentifier("com.apple.iokit.IOGraphicsFamily");
 if(graphics!=kOSReturnSuccess&&graphics!=kOSKextReturnStartStopError)return nullptr;
 auto *display=new B5qDpDisplay;if(!display)return nullptr;
 if(!display->init()||!display->configure(*config)||!display->attach(provider)){display->release();return nullptr;}
 if(!display->start(provider)){display->detach(provider);display->release();return nullptr;}
 display->registerService();return display;
}
extern "C" bool b5q_dp_display_disconnect(IOService *display){
 auto *self=OSDynamicCast(B5qDpDisplay,display);return self&&self->disconnect();
}
extern "C" void b5q_dp_display_frame(IOService *display,uint64_t tag,uint32_t frame,uint64_t time){
 if(auto *self=OSDynamicCast(B5qDpDisplay,display))self->frame(tag,frame,time);
}
