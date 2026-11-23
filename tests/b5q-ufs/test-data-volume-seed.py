#!/usr/bin/env python3
"""Compile actual patched volume selection and board seed policy with fake IOKit."""
import importlib.util,subprocess,sys,tempfile
from pathlib import Path
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'UniXNU-b5q/scripts'))
from b5q_ramblock import prepare_source
with tempfile.TemporaryDirectory(prefix='b5q-volume-seed-')as td:
 t=Path(td);source=prepare_source(R/'UniXNU/drivers/RamBlock/NativeRamBlock.cpp',t/'NativeRamBlock.cpp').read_text()
 selector=source[source.index('static int selectVolumeSeed('):source.index('extern "C" int native_ram_block_volume_device(')]
 seed=source[source.index('extern "C" int native_ram_block_volume_seed('):]
 block=(R/'UniXNU-b5q/package/B5qUfs/B5qDataBlock.h').read_text()
 hook=block[block.index('extern "C" int native_ram_block_provider_seed('):block.index('extern "C" int native_ram_block_volume_seed(')]
 wait=block[block.index('static bool b5qDataWaitReady() {'):block.index('static bool b5qDataStart(')]
 harness=r'''
#include <cassert>
#include <cstdio>
#include <cstring>
#include <cstdint>
#include <string>
#include <map>
#include <memory>
#include <vector>
#include <sys/types.h>
#include <sys/sysmacros.h>
#include "B5qDataSeed.h"
#define NODEV ((dev_t)-1)
#define OSDynamicCast(T,p) dynamic_cast<T *>(p)
#define OSSafeReleaseNULL(p) do{if(p){p->release();p=nullptr;}}while(0)
static const char *kIOBSDNameKey="BSD Name",*kIOBSDMajorKey="BSD Major",*kIOBSDMinorKey="BSD Minor";

struct OSObject {virtual ~OSObject()=default;virtual void release(){delete this;}};
struct OSString:OSObject {
 std::string value;explicit OSString(const char*s):value(s){}
 static OSString*withCString(const char*s){return new OSString(s);}
 const char*getCStringNoCopy(){return value.c_str();}size_t getLength(){return value.size();}
};
struct OSNumber:OSObject {uint64_t value;explicit OSNumber(uint64_t n):value(n){}uint64_t unsigned64BitValue(){return value;}uint32_t unsigned32BitValue(){return value;}};
struct OSDictionary:OSObject {
 std::string uuid;static OSDictionary*withCapacity(unsigned){return new OSDictionary;}
 bool setObject(const char*key,OSObject*o){if(!strcmp(key,"UUID"))uuid=dynamic_cast<OSString*>(o)->value;else uuid=dynamic_cast<OSDictionary*>(o)->uuid;return true;}
};
struct OSIterator:OSObject {std::vector<OSObject*> rows;size_t at=0;OSObject*getNextObject(){return at<rows.size()?rows[at++]:nullptr;}};
struct IOService:OSObject {
 IOService*provider=nullptr;std::map<std::string,std::unique_ptr<OSObject>> props;
 IOService*getProvider(){return provider;}OSObject*getProperty(const char*k){auto i=props.find(k);return i==props.end()?nullptr:i->second.get();}
 static std::vector<IOService*> registry;
 static OSDictionary*serviceMatching(const char*s){assert(!strcmp(s,"IOMedia"));return new OSDictionary;}
 static OSIterator*getMatchingServices(OSDictionary*d){auto*i=new OSIterator;for(auto*m:registry){auto*s=dynamic_cast<OSString*>(m->getProperty("UUID"));if(s&&s->value==d->uuid)i->rows.push_back(m);}return i;}
};
std::vector<IOService*>IOService::registry;
static unsigned ramAttach=0;
struct NativeRamBlock:IOService {
 void attachStore(){++ramAttach;}
 bool seedInfo(uint64_t*b,uint64_t*n,uint8_t*h){*b=0;*n=4ULL<<30;memset(h,0x77,32);return true;}
};
static B5qData::Volume volume;
static uint8_t envelopeHash[32];
struct B5qDataBlock:IOService {
 bool online=true;
 bool seedInfo(const char*u,uint64_t*b,uint64_t*n,uint8_t*h){return B5qData::seed(volume,online,u,envelopeHash,b,n,h);}
};
''' + hook + '\n' + selector + '\n' + seed + r'''
static auto &dataVolume=volume;static auto &dataSeedDigest=envelopeHash;
static bool equal(const uint8_t*a,const uint8_t*b,unsigned n){return !memcmp(a,b,n);}
static unsigned sleeps=0,appearAt=0;static IOService*delayed=nullptr;
static void IOSleep(unsigned ms){assert(ms==50);if(++sleeps==appearAt)IOService::registry={delayed};}
#define IOLog(...) std::printf(__VA_ARGS__)
''' + wait + r'''
static void media(IOService&m,IOService*p,const char*uuid,const char*name="disk1s1"){
 m.provider=p;m.props.clear();m.props["UUID"]=std::make_unique<OSString>(uuid);
 if(name)m.props[kIOBSDNameKey]=std::make_unique<OSString>(name);
 m.props[kIOBSDMajorKey]=std::make_unique<OSNumber>(14);m.props[kIOBSDMinorKey]=std::make_unique<OSNumber>(9);
}
int main(){
 const char*u=B5qData::volumeUuid;volume.valid=true;volume.blocks=44188919;memcpy(volume.uuid,B5qData::expectedVolumeUuid,16);memset(envelopeHash,0x42,32);
 B5qDataBlock disk;IOService container,m,other;container.provider=&disk;media(m,&container,u);IOService::registry={&m};
 dev_t dev;char path[64];uint64_t base,bytes;uint8_t hash[32];unsigned cases=0;
 auto select=[&](const char*id=B5qData::volumeUuid,size_t size=64){return native_ram_block_volume_seed(id,&dev,path,size,&base,&bytes,hash);};
 assert(select()&&dev==makedev(14,9)&&!strcmp(path,"/dev/disk1s1")&&base==0&&bytes==180997812224ULL&&!memcmp(hash,envelopeHash,32)&&ramAttach==0);++cases;
 assert(!select("1552CFEE-78FF-48D8-8A6C-694B867D61AD"));++cases;
 disk.online=false;assert(!select());disk.online=true;++cases;
 volume.valid=false;assert(!select());volume.valid=true;++cases;
 volume.uuid[0]^=1;assert(!select());volume.uuid[0]^=1;++cases;
 volume.blocks=0;assert(!select());volume.blocks=44188919;++cases;
 volume.blocks=(1ULL<<28)+1;assert(!select());volume.blocks=44188919;++cases;
 memset(envelopeHash,0,32);assert(!select());memset(envelopeHash,0x42,32);++cases;
 m.props.erase(kIOBSDNameKey);assert(!select());media(m,&container,u);++cases;
 m.props.erase(kIOBSDMinorKey);assert(!select());media(m,&container,u);++cases;
 m.props[kIOBSDMajorKey]=std::make_unique<OSNumber>(256);assert(!select());media(m,&container,u);++cases;
 m.props[kIOBSDMinorKey]=std::make_unique<OSNumber>(0x1000000);assert(!select());media(m,&container,u);++cases;
 media(m,&container,u,"");assert(!select());media(m,&container,u);++cases;
 assert(!select(u,8));++cases;
 IOService alien;media(other,&alien,u,"disk9s1");IOService::registry={&m,&other};assert(!select());++cases;
 IOService::registry={&other};assert(!select());++cases;
 NativeRamBlock ram;media(m,&ram,u);IOService::registry={&m};assert(select()&&bytes==(4ULL<<30)&&hash[0]==0x77&&ramAttach==1);++cases;
 media(m,&container,u);IOService::registry.clear();assert(!select());IOService::registry={&m};assert(select());++cases;
 IOService::registry.clear();sleeps=0;appearAt=3;delayed=&m;assert(b5qDataWaitReady()&&sleeps==3);++cases;
 IOService::registry={&m,&other};sleeps=appearAt=0;assert(!b5qDataWaitReady()&&sleeps==1200);++cases;
 IOService::registry={&m};m.props.erase(kIOBSDNameKey);sleeps=0;assert(!b5qDataWaitReady()&&sleeps==1200);++cases;
 std::printf("PASS %u actual selectVolumeSeed/provider-policy cases: persistent without RAM, wrong UUID/duplicate/unready/type/limits, RAM recovery\n",cases);
}
'''
 (t/'test.cpp').write_text(harness)
 subprocess.run(['c++','-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-Wno-address','-Wno-misleading-indentation','-fsanitize=address,undefined','-I',str(R/'UniXNU-b5q/package/B5qUfs'),str(t/'test.cpp'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test')],check=True)
