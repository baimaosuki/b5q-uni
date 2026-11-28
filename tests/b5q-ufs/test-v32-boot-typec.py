#!/usr/bin/env python3
"""Replay the production early-exit and Type-C init functions without hardware."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]

with tempfile.TemporaryDirectory(prefix="b5q-v32-") as temporary:
    work = Path(temporary)
    # The current Batch1 absentd no longer parses CFPropertyListRef jobs.
    # Run its production21-case harness, including synchronous boot tasks.
    subprocess.run(['python3',str(ROOT/'tests/b5q-ufs/test-absentd-v33.py')],check=True)

    board = (ROOT / "UniXNU-b5q/package/B5qUsbBoard.cpp").read_text()
    def function(signature):
        start=board.index(signature);at=board.index('{',start);end=at+1;depth=1
        while depth:depth+=(board[end]=='{')-(board[end]=='}');end+=1
        return board[start:end]
    init='\n'.join(function(n)for n in ['bool openMaxim()',
        'extern "C" bool b5q_usb_typec_init','bool ensureMaximReady()',
        'extern "C" bool b5q_usb_cable_state',
        'extern "C" int b5q_usb_cable_role'])
    harness = r'''
#include "B5qMax77705.h"
#include <cassert>
#include <cstdint>
static bool water=false,identityFailure=false,ioFailure=false;
static unsigned writes=0,reads=0,logs=0;
struct Bus {
 int *lock=nullptr;
 bool open(bool hub){assert(hub);return true;}
 bool read(uint8_t address,uint8_t reg,uint8_t &v){
  ++reads;if(address==0x66){v=reg?2:0x15;return !identityFailure;}
  assert(address==0x25);
  if(ioFailure)return false;
  if(reg==0x0a)v=0x81;else if(reg==0x0b)v=water?2:0;
  else if(reg==0x0d)v=0x80;else {assert(reg==8);v=0x80;}
  return true;
 }
 bool write(uint8_t,uint8_t,uint8_t){++writes;assert(false);return false;}
};
static Bus *maxim;
static bool maximReady=false;
static volatile unsigned maximBusState=0;
static void IOSleep(unsigned){}
static uint64_t mach_absolute_time(){return 1000000000;}
static void absolutetime_to_nanoseconds(uint64_t n,uint64_t *out){*out=n;}
static void IOLockLock(int*){}
static void IOLockUnlock(int*){}
template<class... Args>void IOLog(const char*,Args...){++logs;}
'''
    harness += init + r'''
static void reset(){delete maxim;maxim=nullptr;maximReady=false;maximBusState=0;writes=reads=0;water=identityFailure=ioFailure=false;}
int main(){
 assert(b5q_usb_typec_init()&&writes==0);Bus *same=maxim;assert(b5q_usb_typec_init()&&maxim==same);assert(b5q_usb_cable_role()==2);reset();
 water=true;assert(b5q_usb_typec_init()&&writes==0);assert(b5q_usb_cable_role()==0);
 water=false;assert(b5q_usb_cable_role()==2);reset();
 identityFailure=true;assert(!b5q_usb_typec_init()&&!maximReady&&!writes);reset();
 ioFailure=true;assert(!b5q_usb_typec_init()&&!maximReady&&!writes);reset();
}
'''
    cpp=work/'typec.cpp';cpp.write_text(harness);exe=work/'typec'
    subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation',
                    '-fsanitize=address,undefined','-I',str(ROOT/'UniXNU-b5q/package'),str(cpp),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
print('PASS production absentd one-shot/EndpointSecurity and Type-C native-status adoption/Sink+DFP/water recovery/identity/I2C rejection with zero vendor opcodes')
