#!/usr/bin/env python3
"""Execute production USB mux/QMP and Wi-Fi wait code under fault races."""
from pathlib import Path
import subprocess,tempfile
R=Path(__file__).resolve().parents[2]
usb=(R/'UniXNU-b5q/package/QcomDwc3.cpp').read_text()
wifi=(R/'UniXNU-b5q/package/B5qWifiBoard.cpp').read_text()
def function(source,signature):
    start=source.index(signature);at=source.index('{',start);end=at+1;depth=1
    while depth:depth+=(source[end]=='{')-(source[end]=='}');end+=1
    return source[start:end]
harness=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <vector>
#include <cstring>
#define IOLog(...) ((void)0)
static bool forceUtmi;
bool PE_parse_boot_argn(const char *name,void *p,unsigned n){assert(!strcmp(name,"usb-utmi")&&n==4);*(unsigned*)p=forceUtmi;return forceUtmi;}
#include "QcomQmpUsb3.h"
#include "B5qUsbInputs.h"
uint32_t scratch[1024],gcc[0x80000/4],phyWords[0x3000/4],native_usb_stats[54];
unsigned releases,maps,stageFailure,clockCalls,elapsed,gDpLanes;
std::vector<uint32_t> mux;
struct Mapping {void release(){releases++;}} mapping;
struct Region {Mapping *map=nullptr;volatile uint32_t *va=nullptr;}gScratch,gGcc;
bool mapRegion(Region &r,uint64_t base,unsigned bytes){assert(base==0x88e8000&&bytes==0x3000);if(stageFailure==1)return false;r={&mapping,phyWords};maps++;return true;}
bool rcg(uint32_t reg,uint32_t value){assert(reg==0x39070&&!value);return stageFailure!=2;}
bool branch(uint32_t reg){assert(reg==0x39060||reg==0x39064);return stageFailure!=(reg==0x39060?3:4);}
bool sm8550_gcc_update32(volatile uint32_t *reg,uint32_t clear,uint32_t set){if(stageFailure==5)return false;*reg=(*reg&~clear)|set;return true;}
void barrier(){mux.push_back(scratch[2]);}
void IOSleep(unsigned ms){elapsed+=ms;}
void IODelay(unsigned){clockCalls++;}
FUNCTIONS
// Extract exactly the production arm-wait/recheck/block sequence.
using thread_t=int;using wait_result_t=int;using event_t=void*;
constexpr int NSEC_PER_MSEC=1000000,THREAD_UNINT=0,THREAD_AWAKENED=1,THREAD_CONTINUE_NULL=0;
uint32_t wakeCount;unsigned observed,ms=1,clears,blocks;bool race;
int current_thread(){return 0;}
void clock_interval_to_deadline(unsigned,unsigned,uint64_t *out){*out=100;}
void assert_wait_deadline(void*,int,uint64_t){if(race)wakeCount++;}
void clear_wait(int,int){clears++;}
void thread_block(int){assert(!clears);blocks++;}
void waitTest(){WAIT}
int main(){
 gScratch.va=scratch;gGcc.va=gcc;scratch[2]=0x40000000;
 selectUtmiClock();assert((scratch[2]&9)==9&&!(scratch[2]&256));
 assert(qmpInit(false));assert(!(scratch[2]&(9|256))&&(scratch[2]&0x40000000));
 assert(maps==releases&&maps==1);
 selectUtmiClock();assert(qmpInit(true));assert(!(scratch[2]&9)&&phyWords[kQmpComTypec/4]==3);assert(maps==releases);
 for(unsigned failure=1;failure<=6;failure++) {
  stageFailure=failure;selectUtmiClock();phyWords[kQmpStatus/4]=failure==6?64:0;
  assert(!qmpInit(false));assert((scratch[2]&9)==9);assert(maps==releases);
 }
 forceUtmi=true;unsigned previous=maps;assert(!qmpInit(false)&&maps==previous&&(scratch[2]&9)==9);forceUtmi=false;
 for(bool changed:{false,true}){race=changed;clears=blocks=0;observed=wakeCount;waitTest();assert(clears==unsigned(changed)&&blocks==unsigned(!changed));}
 puts("PASS actual USB unplugged-UTMI->hotplug PIPE CC1/CC2,6faults/allmapsreleased; production Wi-Fi wait IRQ race cancels without block");
}
'''
harness=harness.replace('FUNCTIONS','\n'.join(function(usb,n)for n in ['void selectUtmiClock()','void selectPipeClock()','bool qmpInit(bool reverse)']))
start=wifi.index('                    uint64_t deadline;clock_interval_to_deadline');end=wifi.index('\n                }',start)
harness=harness.replace('WAIT',wifi[start:end])
assert '~Window(){OSSafeReleaseNULL(mapping);}'in wifi
with tempfile.TemporaryDirectory(prefix='b5q-review-fixes-')as td:
    td=Path(td);src=td/'test.cpp';src.write_text(harness)
    subprocess.run(['c++','-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
        '-I'+str(R/'UniXNU-b5q/package'),'-I'+str(R/'sources/UniXNU-sheng/drivers/QcomDwc3'),str(src),'-o',str(td/'test')],check=True)
    subprocess.run([str(td/'test')],check=True)
