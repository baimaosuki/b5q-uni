#!/usr/bin/env python3
"""Run the production shared SE8 initialization/snapshot under races/failures."""
from pathlib import Path
import subprocess,tempfile
R=Path(__file__).resolve().parents[2]
source=(R/'UniXNU-b5q/package/B5qUsbBoard.cpp').read_text()
def function(signature):
    start=source.index(signature);at=source.index('{',start);end=at+1;depth=1
    while depth:depth+=(source[end]=='{')-(source[end]=='}');end+=1
    return source[start:end]
code=r'''
#include <atomic>
#include <cassert>
#include <chrono>
#include <cstring>
#include <mutex>
#include <thread>
#include <vector>
#include <cstdio>
#include "B5qFuelGauge.h"
#include "B5qMax77705.h"
std::atomic<unsigned> opens{0},live{0};bool failOpen=false;
unsigned reads=0,failRead=~0u,locks=0;bool locked=false;
std::mutex mutex;
struct Bus {
 std::mutex *lock=&mutex;
 Bus(){++live;}~Bus(){--live;}
 bool open(bool hub){assert(hub);++opens;std::this_thread::sleep_for(std::chrono::milliseconds(3));return !failOpen;}
 bool readWord(uint8_t address,uint8_t,uint16_t &out){assert(locked&&address==0x36);out=1000;return reads++!=failRead;}
 bool read(uint8_t address,uint8_t reg,uint8_t &out){assert(locked);out=address==0x25?(reg==0x0a?0x41:0):3;return reads++!=failRead;}
};
Bus *maxim=nullptr;volatile unsigned maximBusState=0;
void IOSleep(unsigned ms){std::this_thread::sleep_for(std::chrono::milliseconds(ms));}
void IOLockLock(std::mutex *m){m->lock();assert(!locked);locked=true;locks++;}
void IOLockUnlock(std::mutex *m){assert(locked);locked=false;m->unlock();}
FUNCTIONS
void reset(){delete maxim;maxim=nullptr;maximBusState=0;opens=0;failOpen=false;reads=locks=0;failRead=~0u;}
int main(){
 for(bool bad:{false,true}) {
  reset();failOpen=bad;std::atomic<unsigned> successes{0};std::vector<std::thread> threads;
  for(unsigned i=0;i<16;++i)threads.emplace_back([&]{if(openMaxim())successes++;});
  for(auto &t:threads)t.join();
  if(!bad){assert(opens==1&&successes==16&&live==1);assert(openMaxim()&&opens==1);}
  else{assert(opens>=1&&opens<=16&&!successes&&!live&&maximBusState==0);unsigned before=opens;failOpen=false;assert(openMaxim()&&opens==before+1&&live==1);}
 }
 reset();assert(openMaxim());
 for(unsigned failure=0;failure<16;failure++) {
  reads=0;failRead=failure;B5qFuelGauge::Raw raw;std::memset(&raw,0x55,sizeof(raw));
  B5qMax77705::Cable cable{};cable.cc0=0x81;cable.valid=true;uint8_t detail=0xaa;
  const auto before=raw;const auto beforeCable=cable;
  assert(!b5q_battery_snapshot(&raw,&cable,&detail));
  assert(!std::memcmp(&raw,&before,sizeof(raw))&&detail==0xaa);
  assert(cable.cc0==beforeCable.cc0&&cable.valid==beforeCable.valid&&!locked);
 }
 reads=0;failRead=~0u;B5qFuelGauge::Raw raw{};B5qMax77705::Cable cable{};uint8_t detail=0;
 assert(b5q_battery_snapshot(&raw,&cable,&detail)&&cable.valid&&detail==3&&reads==16&&!locked);
 assert(!b5q_battery_snapshot(nullptr,&cable,&detail));
 assert(opens==1&&locks==17);reset();assert(live==0);
 puts("PASS production SE8 sharing:16concurrent initializers,one engine,failed init cleanup;16read-fault atomic snapshots,shared lock and null rejects");
}
'''
code=code.replace('FUNCTIONS','\n'.join(function(n)for n in ['bool openMaxim()',
    'extern "C" bool b5q_battery_snapshot']))
with tempfile.TemporaryDirectory(prefix='b5q-p4-pmic-')as td:
    td=Path(td);p=td/'test.cpp';p.write_text(code)
    subprocess.run(['c++','-std=c++17','-O1','-g','-pthread','-Wall','-Wextra','-Werror',
        '-fsanitize=address,undefined','-I'+str(R/'UniXNU-b5q/package'),str(p),'-o',str(td/'test')],check=True)
    subprocess.run([str(td/'test')],check=True)
