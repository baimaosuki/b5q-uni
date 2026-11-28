#!/usr/bin/env python3
"""Execute selected native HAL IO/properties; SDK target build checks actual ABI."""
from pathlib import Path
import re,subprocess,sys,tempfile
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'UniXNU-b5q/scripts'))
from b5q_audio import prepare_hal,function_span
with tempfile.TemporaryDirectory(prefix='b5q-hal-host-')as td:
 t=Path(td);src,_,_=prepare_hal(R/'sources/UniXNU-sheng',t/'hal');s=src.read_text()
 def fn(signature):
  a,b=function_span(s,signature);return s[a:b]
 functions='\n'.join(fn(n)for n in ['static AudioStreamBasicDescription format(', 'static UInt32 latencyFrames(', 'static Float32 toDb(', 'static Float32 toScalar(', 'static Float32 gain(', 'static UInt32 objects(', 'static OSStatus propertyData(', 'static OSStatus StartIO(', 'static OSStatus StopIO(', 'static OSStatus GetZeroTimeStamp(', 'static OSStatus WillDoIOOperation(', 'static inline int16_t toS16(', 'static OSStatus DoIOOperation('])
 names=sorted(set(re.findall(r'\bkAudio\w+',functions))|{'kAudioServerPlugInIOOperationReadInput'})
 defines='\n'.join('#define '+n+' '+str(1000+i)for i,n in enumerate(names))
 h=r'''
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>
#include <string.h>
#include <assert.h>
#include <math.h>
#include <pthread.h>
#include "ShengAudioAbi.h"
DEFINES
typedef unsigned UInt32,AudioObjectID,AudioObjectPropertyScope,AudioObjectPropertyElement,AudioClassID,AudioObjectPropertySelector;typedef uint64_t UInt64;typedef float Float32;typedef double Float64;typedef bool Boolean;typedef int OSStatus;typedef void *AudioServerPlugInDriverRef;
typedef const char *CFStringRef;
#define CFSTR(v) (v)
#define CFStringCompare(a,b,c) strcmp(a,b)
#define kCFCompareEqualTo 0
#define kDeviceUID "B5qAudioDevice"
#define kModelUID "B5qAudioModel"
#define KERN_SUCCESS 0
static const unsigned kPlugIn=1,kDevice=2,kOutStream=3,kInStream=4,kVolume=5;
static const Float32 kMinDb=-96;
static const Float64 kRate=SHENG_AUDIO_RATE;static const UInt32 kZeroPeriod=SHENG_AUDIO_RING_FRAMES;
typedef struct {double mSampleRate;UInt32 mFormatID,mFormatFlags,mBytesPerPacket,mFramesPerPacket,mBytesPerFrame,mChannelsPerFrame,mBitsPerChannel,mReserved;} AudioStreamBasicDescription;
typedef struct {double mMinimum,mMaximum;} AudioValueRange;
typedef struct {AudioStreamBasicDescription mFormat;AudioValueRange mSampleRateRange;} AudioStreamRangedDescription;
typedef struct {UInt32 mChannelLabel,mChannelFlags;float mCoordinates[3];} AudioChannelDescription;
typedef struct {UInt32 mChannelLayoutTag,mChannelBitmap,mNumberChannelDescriptions;AudioChannelDescription mChannelDescriptions[1];} AudioChannelLayout;
typedef struct {UInt32 mSelector,mScope,mElement;} AudioObjectPropertyAddress;
typedef struct {struct {double mSampleTime;} mOutputTime,mCurrentTime;} AudioServerPlugInIOCycleInfo;
static uint8_t page[4096];static ShengAudioControl *gControl;static int16_t ring[2*SHENG_AUDIO_RING_FRAMES],*gOut=ring;
static uint64_t gZeroOrigin,gZeroSeed,clockNow;static UInt32 gIoUsers;static float gVolume=1;static double gHostTicksPerFrame=400;
static pthread_mutex_t gLock=PTHREAD_MUTEX_INITIALIZER;static unsigned calls,clocks;static int callError,connectError;
static uint64_t mach_absolute_time(void){return clockNow;}
static int connectService(void){return connectError;}
static void setHostClock(void){clocks++;}
static int call(unsigned op){assert(op==ShengAudioStartOutput||op==ShengAudioStopOutput);calls++;return callError;}
static void noteThread(ShengAudioDiag *d){assert(d);}
#define REPLY(type,value) do {if(inDataSize<sizeof(type))return kAudioHardwareBadPropertySizeError;*(type*)outData=(value);*outDataSize=sizeof(type);return 0;}while(0)
#define REPLY_STR(text) REPLY(CFStringRef,CFSTR(text))
FUNCTIONS
int main(void){gControl=(void*)page;gControl->out_anchor_host=4000;clockNow=404000;
 AudioObjectID list[3];assert(objects(kDevice,kAudioObjectPropertyScopeInput,list)==0);assert(objects(kDevice,kAudioObjectPropertyScopeOutput,list)==2&&list[0]==kOutStream&&list[1]==kVolume);
 AudioObjectPropertyAddress prop={kAudioDevicePropertyStreams,kAudioObjectPropertyScopeInput,0};UInt32 n=999;
 assert(!propertyData(kDevice,&prop,0,NULL,sizeof(list),&n,list)&&!n);
 prop.mScope=kAudioObjectPropertyScopeOutput;assert(!propertyData(kDevice,&prop,0,NULL,sizeof(list),&n,list)&&n==4&&list[0]==kOutStream);
 prop.mSelector=kAudioStreamPropertyPhysicalFormat;AudioStreamBasicDescription fmt={0};assert(!propertyData(kOutStream,&prop,0,NULL,sizeof(fmt),&n,&fmt)&&fmt.mChannelsPerFrame==2&&fmt.mSampleRate==48000&&fmt.mBitsPerChannel==32);
 assert(propertyData(kInStream,&prop,0,NULL,sizeof(fmt),&n,&fmt)==kAudioHardwareBadObjectError);
 prop.mSelector=kAudioDevicePropertyDeviceCanBeDefaultDevice;prop.mScope=kAudioObjectPropertyScopeInput;UInt32 value=1;assert(!propertyData(kDevice,&prop,0,NULL,4,&n,&value)&&!value);
 for(unsigned i=0;i<3;i++){gIoUsers=0;calls=0;connectError=i==1;callError=i==2;OSStatus status=StartIO(NULL,kDevice,0);assert((status!=0)==(i!=0));assert(gIoUsers==(i==0));}
 connectError=callError=0;gIoUsers=0;calls=0;assert(!StartIO(NULL,kDevice,0)&&!StartIO(NULL,kDevice,1)&&gIoUsers==2&&calls==1);assert(!StopIO(NULL,kDevice,0)&&calls==1);assert(!StopIO(NULL,kDevice,1)&&!gIoUsers&&calls==2);assert(!StopIO(NULL,kDevice,1)&&calls==2);
 double sample;uint64_t host,seed;gControl->out_seq=1;assert(GetZeroTimeStamp(NULL,kDevice,0,&sample,&host,&seed)==kAudioHardwareNotRunningError);gControl->out_seq=0;
 for(unsigned i=0;i<1000;i++){clockNow=404000+(uint64_t)i*400;assert(!GetZeroTimeStamp(NULL,kDevice,0,&sample,&host,&seed)&&host<=clockNow&&seed&&isfinite(sample));}
 bool will,inPlace;assert(!WillDoIOOperation(NULL,kDevice,0,kAudioServerPlugInIOOperationReadInput,&will,&inPlace)&&!will&&inPlace);assert(!WillDoIOOperation(NULL,kDevice,0,kAudioServerPlugInIOOperationWriteMix,&will,&inPlace)&&will);
 assert(toS16(NAN)==0&&toS16(INFINITY)==0&&toS16(2)==32767&&toS16(-2)==-32768);
 float frames[8]={1,-1,.5f,-.5f,0,0,0,0};AudioServerPlugInIOCycleInfo info={.mOutputTime={SHENG_AUDIO_RING_FRAMES-1},.mCurrentTime={0}};
 assert(!DoIOOperation(NULL,kDevice,kOutStream,0,kAudioServerPlugInIOOperationWriteMix,4,&info,frames,NULL));assert(ring[2*(SHENG_AUDIO_RING_FRAMES-1)]==32767&&ring[2*(SHENG_AUDIO_RING_FRAMES-1)+1]==-32767&&ring[0]>16000&&ring[1]<-16000);
 info.mOutputTime.mSampleTime=NAN;assert(DoIOOperation(NULL,kDevice,kOutStream,0,kAudioServerPlugInIOOperationWriteMix,4,&info,frames,NULL)==kAudioHardwareIllegalOperationError);
 info.mOutputTime.mSampleTime=0;assert(DoIOOperation(NULL,kDevice,kOutStream,0,kAudioServerPlugInIOOperationWriteMix,SHENG_AUDIO_RING_FRAMES+1,&info,frames,NULL)==kAudioHardwareIllegalOperationError);
 puts("PASS selected native stereo HAL:output-only properties/streams,1000timestamps,boundedseqlock,multi-clientstartstop/faults,ringwrap/saturation/nonfinite/bounds; ASanUBSan (SDK ABI verified separately)");
}
'''.replace('DEFINES',defines).replace('FUNCTIONS',functions)
 (t/'test.c').write_text(h);subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-Wno-multichar','-Wno-sign-compare','-O1','-g','-fsanitize=address,undefined','-I'+str(R/'sources/UniXNU-sheng/package'),str(t/'test.c'),'-lm','-pthread','-o',str(t/'test')],check=True);subprocess.run([str(t/'test')],check=True)
