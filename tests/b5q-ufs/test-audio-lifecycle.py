#!/usr/bin/env python3
"""Fault-inject the selected production AudioProbe's stream lifecycle."""
from pathlib import Path
import subprocess,sys,tempfile
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'UniXNU-b5q/scripts'))
from b5q_audio import prepare_service,function_span
with tempfile.TemporaryDirectory(prefix='b5q-audio-lifecycle-')as td:
 t=Path(td);prepare_service(R/'sources/UniXNU-sheng',t/'generated');s=(t/'generated/AudioProbe.cpp').read_text()
 def fn(name):
  a,b=function_span(s,name+' {');return s[a:b]
 functions='\n'.join(fn(n)for n in ['void startOutput()','void stopOutput()','void handle(const ArAnswer &a)','void serve(uint32_t ms)','bool publishService()'])
 harness=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include "ShengGpr.h"
#include "ShengAudioAbi.h"
#include "ShengAudioReach.h"
#include "B5qAudioQueue.h"
constexpr unsigned kPeriodFrames=SHENG_AUDIO_PERIOD_FRAMES,kChannels=2,kRingFrames=SHENG_AUDIO_RING_FRAMES,kInFlight=4,kKeepMs=5000,kPeriodBytes=kPeriodFrames*kChannels*2;
struct Audio {bool running=false,tone=false,outputError=false,statusRead=false;unsigned up=1,serving=1,want=ShengAudioOutputRunning,inFlight=0,handle=9;uint64_t next=0,done=0,first=0,stopAsked=0,dspAddr=0x1a0000000;ShengAudioControl *ctl;int16_t *out;B5qAudio::Queue periods;} gAudio;
static ShengAudioControl control;static int16_t samples[kRingFrames*2];static int32_t native_audio_stats[16];
static unsigned events[100],count,fault,submits,syncs,failSubmit;static uint64_t now;static int failed;
static void event(unsigned n){assert(count<100);events[count++]=n;}
static bool graphs(uint32_t op){event(op==AR_OP_GRAPH_PREPARE?1:op==AR_OP_GRAPH_START?2:3);return fault!=(op==AR_OP_GRAPH_PREPARE?1u:op==AR_OP_GRAPH_START?2u:3u);}
static bool b5q_audio_amps_start(){event(4);return fault!=4;}
static void powerDownAmps(){event(5);}
static void fail(int n){failed=n;}
static uint64_t framesNow(){return 1000;}
static uint64_t nowMs(){return ++now;}
static bool submit(uint64_t n){if(++submits==failSubmit)return false;uint32_t token;assert(gAudio.periods.reserve(n%8,token));gAudio.inFlight++;return true;}
static void syncPlayback(){syncs++;}
static void IOLog(const char *,...){ }
static bool nextAnswer(ArAnswer &,unsigned){now+=10000;return false;}
static struct {const char *name="b5q";}g_kernel_kmod_info;
struct OSMetaClass {static void *preModLoad(const char *){event(6);return fault==6?nullptr:(void*)1;}static int postModLoad(void *p){assert(p==(void*)1);event(8);return fault==8;}};
static void native_audio_service_static_init(){event(7);}
static bool sheng_audio_service_start(){event(9);return fault!=9;}
void stopOutput();
FUNCTIONS
static void reset(unsigned f=0){gAudio=Audio{};control={};gAudio.ctl=&control;gAudio.out=samples;memset(samples,1,sizeof samples);memset(native_audio_stats,0,sizeof native_audio_stats);count=submits=syncs=failSubmit=0;fault=f;failed=0;now=0;}
int main(){
 reset();startOutput();assert(gAudio.running&&gAudio.inFlight==kInFlight&&control.state&ShengAudioOutputRunning);assert(count==3&&events[0]==1&&events[1]==2&&events[2]==4);
 startOutput();assert(count==3);stopOutput();assert(!gAudio.running&&!(control.state&ShengAudioOutputRunning)&&events[3]==3&&events[4]==5);stopOutput();assert(count==5);
 for(unsigned f:{1u,2u,4u}){reset(f);startOutput();assert(!gAudio.running&&!gAudio.want&&!(control.state&ShengAudioOutputRunning)&&events[count-1]==5&&failed);}
 reset();gAudio.handle=0;startOutput();assert(!gAudio.running&&!gAudio.want&&failed==62&&events[count-1]==5);
 for(unsigned f=1;f<=kInFlight;f++){reset();failSubmit=f;startOutput();assert(!gAudio.running&&!gAudio.want&&failed==64&&events[count-1]==5);}
 // Queue-send fault independently from graph/amp fault numbers.
 for(unsigned f=1;f<=kInFlight;f++){
  reset();fault=f==1?0:0;gAudio.running=true;gAudio.periods.init(gAudio.dspAddr,gAudio.handle,kPeriodBytes);
  uint32_t token;assert(gAudio.periods.reserve(3,token));gAudio.inFlight=1;gAudio.first=gAudio.done=0;
  ArAnswer a{};a.opcode=AR_OP_WRITE_DONE;a.address=gAudio.dspAddr+3*kPeriodBytes;a.handle=9;a.token=token;a.src_port=AR_IID_PLAY_SHMEM;
  ArAnswer bad=a;bad.src_port++;handle(bad);assert(gAudio.inFlight==1&&!gAudio.done);
  bad=a;bad.token++;handle(bad);assert(gAudio.inFlight==1&&!gAudio.done);
  a.status=f;handle(a);assert(!gAudio.inFlight&&gAudio.done==1&&gAudio.outputError&&!submits);
  handle(a);assert(gAudio.done==1);serve(1);assert(!gAudio.running&&!gAudio.want&&failed==63&&events[0]==3&&events[1]==5);
 }
 reset();control.state=ShengAudioOutputReady|ShengAudioOutputRunning;gAudio.running=true;gAudio.up=0;serve(1);assert(!gAudio.running&&!gAudio.serving&&!control.state&&failed==61&&events[0]==5);
 for(unsigned f:{0u,6u,8u,9u}){reset(f);bool ok=publishService();assert(ok==(f==0));assert(count==(f==6?1u:f==8?3u:4u));}
 puts("PASS actual generated AudioProbe lifecycle:graph/amp/map errors,ordered startup/idempotentstop,foreign/stale/DSPerror completion,disconnect,publication faults; ASanUBSan");
}
'''.replace('FUNCTIONS',functions)
 (t/'test.cpp').write_text(harness)
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-format','-O1','-g','-fsanitize=address,undefined','-I'+str(R/'UniXNU-b5q/package'),'-I'+str(R/'sources/UniXNU-sheng/package'),str(t/'test.cpp'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test')],check=True)
