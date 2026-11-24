#!/usr/bin/env python3
"""Actual external IOMFB validator, producer fence, tag and completion bodies."""
from pathlib import Path
import json,subprocess,tempfile
R=Path(__file__).resolve().parents[2]
s=(R/'UniXNU-b5q/package/B5qDpDisplay.cpp').read_text()
original=(R/'sources/UniXNU/drivers/GopFramebuffer/NativeLegacyDisplay.cpp').read_text()
a=original.index('    struct SwapInfo {');b=original.index('#else\n    IOReturn collectCompletionReports',a)
assert original[a:b]in s,'Reused OS notification packing must stay verbatim'
def method(name):
 start=s.index(name);brace=s.index('{',start);depth=0
 for at in range(brace,len(s)):
  depth+=(s[at]=='{')-(s[at]=='}')
  if not depth:return s[start:at+1].replace('override','')
methods='\n'.join(method(n)for n in ['bool known(', 'void forget(', 'bool remember(', 'bool producerComplete(',
 'void kickOnce(', 'bool validateSwap(', 'void kickSwapQueue(', 'bool cancelSwapsAfterTimeout(', 'void frame('])
fixture=json.loads((R/'UniXNU-b5q/scripts/legacy-display-26C5035r.json').read_text())
r=fixture['request'];constants='\n'.join(f'constexpr unsigned {name}={r[key]};'for name,key in [
 ('kRequestRect0','rect0'),('kRequestRect1','rect1'),('kRequestMasks','masks'),('kRequestOptions','options'),('kRequestDims','dims'),('kRequestSurfaces','surfaces')])
h=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <vector>
#include "B5qDpDisplay.h"
#include "NativeLegacyRequest.h"
using IOReturn=int;using OSObject=void;
constexpr int kIOReturnSuccess=0,kIOReturnNotReady=1;
struct OriginalLegacySwapRequest{uint8_t bytes[4096]{};};
struct IOMemoryDescriptor{uint64_t length=1920*1080*4;uint64_t getLength(){return length;}};
struct Surface {
 IOMemoryDescriptor memory;uint64_t width=1920,height=1080,stride=1920*4,bytes=1920*1080*4;
 unsigned format=0x42475241,planes=0;bool type=true;
 bool metaCast(const char *name){assert(!strcmp(name,"IOSurface"));return type;}
};
#undef OSObject
// Surface has precisely the source fields consumed by this adapter.
#define OSObject Surface
IOMemoryDescriptor *native_legacy_surface_descriptor(OSObject *s){return &s->memory;}
uint64_t native_legacy_surface_width(OSObject *s){return s->width;}
uint64_t native_legacy_surface_height(OSObject *s){return s->height;}
uint64_t native_legacy_surface_stride(OSObject *s){return s->stride;}
uint64_t native_legacy_surface_allocation(OSObject *s){return s->bytes;}
unsigned native_legacy_surface_format(OSObject *s){return s->format;}
unsigned native_legacy_surface_planes(OSObject *s){return s->planes;}
struct IOTimerEventSource{unsigned ticks=0,cancels=0;void setTimeoutUS(unsigned us){assert(us==200);ticks++;}void cancelTimeout(){cancels++;}};
struct IOWorkLoop {
 IOReturn runAction(IOReturn (*action)(OSObject *,void *,void *,void *,void *),void *,void *arg){return action(nullptr,arg,nullptr,nullptr,nullptr);}
};
unsigned vsyncs=0,producerSubmitted=5,producerDone=4;bool producerKnown=true;
bool native_adreno_fences(uint32_t *submitted,uint32_t *done){*submitted=producerSubmitted;*done=producerDone;return producerKnown;}
void native_legacy_vsync_notify(void *,uint64_t time,uint64_t continuous,uint64_t interval){assert(time&&continuous&&interval);vsyncs++;}
uint64_t mach_continuous_time(){return 1;}
void nanoseconds_to_absolutetime(uint64_t ns,uint64_t *time){*time=ns;}
struct IOMobileFramebufferLegacy {
 const OriginalLegacySwapRequest *head=nullptr,*current=nullptr;unsigned completions=0;
 const OriginalLegacySwapRequest *pendingSwapRequest(){return head;}
 bool activateOnlyPendingSwap(const OriginalLegacySwapRequest *r){if(!r||r!=head||current)return false;current=head;head=nullptr;return true;}
 void completeCurrentSwap(){assert(current);current=nullptr;completions++;}
};
'''
# Override exists only in the actual source; the simple host base models
# only the original family's documented queue activation/completion.
decl=r'''
struct B5qDpDisplay:IOMobileFramebufferLegacy {
 struct Config{B5qDp::Mode mode;void *context;bool (*present)(void *,IOMemoryDescriptor *,uint64_t,bool,uint64_t);}config;
 IOTimerEventSource timer,*fenceTimer=&timer;IOWorkLoop loop;
 bool live=true,closing=false,kicking=false,rekick=false,fenceCaptured=false;
 const OriginalLegacySwapRequest *validated[8]{},*offered=nullptr,*fenceFor=nullptr;
 uint64_t generation=0,offeredTag=0,frames=0,retired=0;uint32_t fenceTarget=0;
 IOWorkLoop *getWorkLoop(){return &loop;}bool isClosing(){return closing;}
'''
test=r'''
};
struct Backend {unsigned offers=0;bool accept=true;uint64_t tag=0;
 static bool present(void *context,IOMemoryDescriptor *memory,uint64_t stride,bool blank,uint64_t tag){
  auto &b=*static_cast<Backend*>(context);assert(tag);assert(blank?(!memory&&!stride):(memory&&stride>=1920*4));b.offers++;b.tag=tag;return b.accept;
 }
};
void word(OriginalLegacySwapRequest &r,unsigned off,uint32_t value){memcpy(r.bytes+off,&value,4);}
void setup(B5qDpDisplay &display,Backend &backend){display.config={{148500,1920,1080,280,45,88,44,4,5,true,true},&backend,Backend::present};}
OriginalLegacySwapRequest request(Surface *surface){
 OriginalLegacySwapRequest r;word(r,kRequestDims,1920);word(r,kRequestDims+4,1080);
 word(r,kRequestMasks,1);word(r,kRequestMasks+4,surface?0:1);
 for(unsigned off:{kRequestRect0,kRequestRect1}){word(r,off+8,1920);word(r,off+12,1080);}
 memcpy(r.bytes+kRequestSurfaces,&surface,8);return r;
}
int main(){unsigned cases=0;
 for(unsigned bad=0;bad<19;bad++){
  B5qDpDisplay d;Backend b;setup(d,b);Surface surface;auto r=request(&surface);
  if(bad==0)surface.planes=2;if(bad==1)surface.format=0x62336138;if(bad==2)surface.width=1919;
  if(bad==3)surface.height=1079;if(bad==4)surface.stride=1920*4-1;if(bad==5)surface.stride=UINT64_MAX;
  if(bad==6)surface.bytes=1;if(bad==7)surface.memory.length=1;if(bad==8)surface.type=false;
  if(bad==9)word(r,kRequestDims,640);if(bad==10)word(r,kRequestRect1+4,1);
  if(bad==11)word(r,kRequestOptions,1);if(bad==12)word(r,kRequestMasks,3);
  if(bad==13)word(r,kRequestMasks+8,1);if(bad==14)memcpy(r.bytes+kRequestSurfaces+8,&d.config.context,8);
  if(bad==15)d.live=false;if(bad==16)d.closing=true;if(bad==17)word(r,kRequestRect0+8,1919);
  if(bad==18)word(r,kRequestOptions+8,1);
  assert(!d.validateSwap(&r)&&!d.known(&r));d.head=&r;d.kickSwapQueue();assert(!b.offers&&!d.completions);cases++;
 }
 {B5qDpDisplay d;Backend b;setup(d,b);Surface surface;auto r=request(&surface);assert(d.validateSwap(&r));d.head=&r;
  producerKnown=false;d.kickSwapQueue();assert(!b.offers&&d.timer.ticks==1);
  producerKnown=true;producerSubmitted=5;producerDone=4;d.kickSwapQueue();assert(!b.offers&&d.fenceCaptured&&d.fenceTarget==5);
  producerDone=5;d.kickSwapQueue();assert(b.offers==1&&d.offered==&r&&d.offeredTag==b.tag&&!d.completions);
  auto tag=b.tag;d.frame(0,1,100);assert(!d.completions&&d.offered==&r);d.frame(tag,2,200);
  assert(d.completions==1&&d.retired==1&&!d.offered&&!d.known(&r));d.frame(tag,3,300);assert(d.completions==1);cases++;
 }
 {B5qDpDisplay d;Backend b;setup(d,b);auto r=request(nullptr);assert(d.validateSwap(&r));d.head=&r;
  d.kickSwapQueue();const auto old=b.tag;assert(!d.cancelSwapsAfterTimeout()&&!d.offered&&!d.known(&r));
  Surface surface;auto next=request(&surface);d.head=&next;assert(d.validateSwap(&next));d.kickSwapQueue();const auto current=b.tag;assert(current>old);
  d.frame(old,1,100);assert(!d.completions&&d.offeredTag==current);
  d.frame(current,2,200);assert(d.completions==1&&d.retired==1);cases++;
 }
 {B5qDpDisplay d;Backend b;setup(d,b);Surface surface;OriginalLegacySwapRequest r[9];
  for(unsigned i=0;i<9;i++){r[i]=request(&surface);assert(d.validateSwap(&r[i])==(i<8));}cases++;
 }
 {B5qDpDisplay d;Backend b;setup(d,b);auto r=request(nullptr);assert(d.validateSwap(&r));d.head=&r;b.accept=false;
  d.kickSwapQueue();assert(!d.offered&&!d.completions);b.accept=true;d.kickSwapQueue();assert(d.offered);
  d.closing=true;auto n=vsyncs;d.frame(b.tag,1,100);assert(vsyncs==n&&!d.completions);cases++;
 }
 printf("PASS external IOMFB %u production validation/fence/latch-tag/cancel/stale-callback cases ASanUBSan; original 53-line notification packing preserved\n",cases);
}
'''
with tempfile.TemporaryDirectory(prefix='b5q-dp-display-')as td:
 t=Path(td);(t/'test.cpp').write_text(h+constants+decl+methods+test)
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-Wno-address','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(R/'UniXNU-b5q/package'),'-I'+str(R/'sources/UniXNU/drivers/GopFramebuffer'),str(t/'test.cpp'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test')],check=True)
