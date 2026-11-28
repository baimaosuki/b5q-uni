#!/usr/bin/env python3
"""Exercise the actual USB stage-5/bringUp code without physical MMIO."""
from pathlib import Path
import re, subprocess, tempfile

root = Path(__file__).resolve().parents[2]
source = (root / 'UniXNU-b5q/package/QcomDwc3.cpp').read_text()

def function(signature):
    start = source.index(signature)
    brace = source.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]

# Both the normal setup and optional diagnostics must lack the old register map.
code = re.sub(r'//[^\n]*|/\*.*?\*/', '', source, flags=re.S)
for forbidden in ['gSmmu', 'kSmmu', '0x15000000', 'B5qUsbSmmu', 'IOBufferMemoryDescriptor']:
    assert forbidden not in code, forbidden
identity = function('bool smmuIdentity()')
assert 'AppsSmmuLock' not in identity and 'mapRegion' not in identity
publish = function('extern "C" void qcom_dwc3_publish(void)')
assert publish.index('if (!gDmaReady)') < publish.index('controller->start')
assert 'return;' in publish[:publish.index('    do {')]
enter = function('bool enterRole(int role)')
hardware_enter = enter[:enter.index('    B5qMax77705::Cable cable;')] + '\nassert(false); return false;\n}'
assert hardware_enter.index('if (!gDmaReady)') < hardware_enter.index('b5q_usb_otg')
hardware_leave = function('void leaveRole(int role)').split('    if (role == kRoleDevice)', 1)[0] + '\n}'

harness = r'''
#include <cstdint>
#include <cassert>
#include <vector>
#include <cstdio>
#include <cstring>
#include "B5qUsbDmaHandoff.h"
const int gIODTPlane = 0;
struct OSData{unsigned getLength(){return 0;}const void*getBytesNoCopy(){return nullptr;}};
#define OSDynamicCast(T,v) static_cast<T*>(v)
struct DmaRange{uint64_t base,bytes;};DmaRange gDmaRam[17],gDmaExcluded[128];unsigned gDmaRamCount,gDmaExcludedCount;
struct IORegistryEntry {
 void *getProperty(const char*){return nullptr;}
 static IORegistryEntry *fromPath(const char *name,int){assert(!strcmp(name,"/chosen"));static IORegistryEntry entry;return &entry;}
};
#define OSSafeReleaseNULL(p) ((p)=nullptr)
uint32_t flag = 0;
B5qUsbDmaHandoff::State firmware = {};
bool flagPresent = false, statePresent = false;
B5qUsbDmaHandoff::Diagnostics diagnostics={};bool diagPresent=false;
bool readChosen(IORegistryEntry *,const char *name,B5qUsbDmaHandoff::Diagnostics &out){assert(!strcmp(name,"b5q-usb-dma-diagnostics"));out=diagnostics;return diagPresent;}
bool readChosen(IORegistryEntry *,const char *name,uint32_t &out){assert(!strcmp(name,"b5q-usb-dma-ready"));out=flag;return flagPresent;}
bool readChosen(IORegistryEntry *,const char *name,B5qUsbDmaHandoff::State &out){assert(!strcmp(name,"b5q-usb-dma-state"));out=firmware;return statePresent;}
struct Map {void release(){}};
struct Region {Map *map=nullptr;volatile uint32_t *va=nullptr;};
uint32_t regs[1024]={};Map mapping;
Region gGcc,gTcsrMap,gPhy,gScratch;
constexpr uint64_t kGcc=0x100000,kTcsr=0x1fd5000,kPhy=0x88e3000,kQscratch=0xa6f8800,kAppleWindow=0xa60c000;
uint32_t native_usb_stats[54]={};bool gDmaReady,gTypecReady,gSuperSpeed;
bool typec=true,rep=true,ss=true,power=true;unsigned utmi=0,repeaterCalls=0,otgCalls=0;
bool otgOn=false;enum {kRoleNone,kRoleDevice,kRoleHost};
std::vector<int> stages;
void stage(int n){stages.push_back(n);}
void IOLog(const char *,...){}
bool mapRegion(Region &r,uint64_t pa,uint64_t){assert(pa!=0x15000000);r.map=&mapping;r.va=regs;return true;}
bool powerRails(){return power;}bool gdsc(unsigned,unsigned){return true;}bool clocksAndResets(){return true;}
bool b5q_usb_typec_init(){return typec;}
bool repeater(bool,bool){++repeaterCalls;return rep;}
void phyInit(){}void IOSleep(unsigned){}
namespace B5qMax77705 { struct Cable{}; }
B5qMax77705::Cable gAppliedCable;
int gAppliedOrientation=-1;
bool superSpeedInit(){return ss;}void selectUtmiClock(){++utmi;}
bool b5q_usb_otg(bool on){++otgCalls;otgOn=on;return true;}
void followOrientation(){}
'''
harness += identity + '\n' + function('bool bringUp()') + '\n' + hardware_enter + '\n' + hardware_leave
harness += r'''
int main(){
 regs[0x120/4]=0x55333301;
 assert(bringUp() && !gDmaReady && native_usb_stats[7]==~0u);
 assert((stages==std::vector<int>{1,2,3,4,5,6,7,8,9}));
 flagPresent=true;flag=1;
 assert(!smmuIdentity()); // Ready alone is insufficient.
 statePresent=true;
 firmware={1,0x40,0,0,0,0,0,0x80000000,0x100000000};
 assert(!smmuIdentity());diagPresent=true;diagnostics.usedPages=1;
 assert(smmuIdentity() && native_usb_stats[7]==0x40);
 diagnostics.flush=1;assert(!smmuIdentity());diagnostics.flush=0;
 diagnostics.coverageStatus=1;assert(!smmuIdentity());diagnostics.coverageStatus=0;
 firmware.attach=22;assert(!smmuIdentity());firmware.attach=0;
 firmware.locate=1ull<<63;assert(!smmuIdentity());firmware.locate=0;
 firmware.sid=0x60;assert(!smmuIdentity());firmware.sid=0x40;
 firmware.ownedBytes=UINT64_MAX&~0xfffull;assert(!smmuIdentity());
 firmware.ownedBytes=4095;assert(!smmuIdentity());
 flag=0;
 stages.clear();ss=false;assert(bringUp() && utmi==1);
 stages.clear();typec=false;assert(bringUp()); // TI/QMP remain independently testable.
 stages.clear();rep=false;assert(!bringUp() && stages.back()==-6);
 rep=true;typec=true;assert(enterRole(kRoleHost) && !otgOn);
 leaveRole(kRoleHost);assert(!otgOn);
 assert(enterRole(kRoleDevice) && !otgOn);
 assert(enterRole(kRoleNone) && !otgOn);
 regs[0x120/4]=0;stages.clear();assert(!bringUp() && stages.back()==-9);
 puts("PASS production stage5 zero SMMU access; stages6-9, TI failure, QMP fallback, ID rejection; hardware-only OTG roles/DMA gate");
}
'''
with tempfile.TemporaryDirectory(prefix='b5q-usb-no-smmu-') as td:
    cpp = Path(td) / 'test.cpp'
    cpp.write_text(harness)
    exe = Path(td) / 'test'
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror', '-I', str(root / 'UniXNU-b5q/package'), str(cpp), '-o', str(exe)], check=True)
    subprocess.run([str(exe)], check=True)
