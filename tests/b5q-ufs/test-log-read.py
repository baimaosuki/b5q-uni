#!/usr/bin/env python3
"""Execute production journal I/O and bounded read retries with UFS responses."""
import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--before', type=Path)
args = parser.parse_args()
source = (root / 'UniXNU-b5q/package/B5qUfs/B5qLogUfs.h').read_text()
if args.before:
    source = json.loads(args.before.read_text())['UniXNU-b5q/package/B5qUfs/B5qLogUfs.h']['text']
functions = '\n'.join(re.search(r'static ' + sig + r'\(.*?\n\}', source, re.S)[0]
                      for sig in ['int nabuLogIo', 'void nabuLogPause', 'int nabuLogRead'])
harness = r'''
#include "B5qLogProtocol.h"
#include <cassert>
#include <cstdio>
#include <cstring>
#include <initializer_list>
using namespace B5qUfsProtocol;
using IOReturn=int;
constexpr unsigned dmaBytes=0x25000,fatalStatus=0x71880,kMillisecondScale=1;
alignas(8) static uint8_t dma[dmaBytes];
static struct{bool selected=true,poisoned=false;int lock=1;uintptr_t hc=1;
 uint8_t*dma=::dma;uint64_t physical=0x900000000,capacity[8]={0,0,0,62275584};
 uint8_t lun=3,commandLun=3,opcode=0;uint64_t commandLba=0;
 unsigned lastOcs=0;Status status;const char*stage="";}host;
static nb_log_volume nabu_log_volume;
static const char*nabu_log_io_reason;
static IOReturn nabu_log_io_result;
static uint32_t nabu_log_io_scsi;
static unsigned calls,failures;static int condition;static bool held,contended;
static uint64_t ticks;
static unsigned read32(uintptr_t,unsigned){return 0;}
static void write32(uintptr_t,unsigned,unsigned){}
static bool IOLockTryLock(int){assert(!held);if(contended)return false;held=true;return true;}
static void IOLockUnlock(int){assert(held);held=false;
 // A concurrent legal command can replace the shared status after unlock.
 host.status={};host.status.exact=true;host.status.scsi=0;}
static uint64_t mach_absolute_time(){return ++ticks;}
static void clock_interval_to_deadline(unsigned n,unsigned,uint64_t*d){*d=ticks+n;}
static void thread_yield_internal(int n){assert(n==1&&!held);++ticks;}
static bool submit(){assert(held);++calls;auto*u=dma+commandOffset;auto*r=u+responseOffset;
 r[0]=0x21;r[2]=3;
 if(calls<=failures){
  if(condition==-1)return false;
  if(condition==-2){r[0]=0xff;return true;}
  if(condition==1){r[1]=0x20;putBe32(r+12,4096);return true;}
  if(condition>=0x100){r[7]=2;r[11]=20;r[33]=18;r[34]=0x70;
   r[36]=condition>>8;r[41]=10;r[46]=condition&255;}
  else r[7]=condition;
 }else memset(dma+dataOffset,0x5a,4096);
 return true;
}
FUNCTIONS
static void reset(int code,unsigned n){calls=0;failures=n;condition=code;host.poisoned=false;ticks=0;}
int main(){uint8_t out[4096];
 for(int code:{8,0x28,0x629,0x204}){
  reset(code,2);memset(out,0xcc,sizeof(out));int result=nabuLogRead(nullptr,1,1,out);
  assert(result==EXPECTED_SUCCESS&&calls==EXPECTED_CALLS&&!held&&!host.poisoned);
  for(auto b:out)assert(b==(EXPECTED_SUCCESS?0x5a:0xcc));
 }
 for(int code:{8,0x28,0x629,0x204}){reset(code,99);assert(!nabuLogRead(nullptr,1,1,out)&&calls==EXPECTED_CALLS&&!held);}
 for(int code:{0x520,1,-1,-2}){reset(code,99);memset(out,0xcc,sizeof(out));
  assert(!nabuLogRead(nullptr,1,1,out)&&calls==1&&!held);
  for(auto b:out)assert(b==0xcc);assert(host.poisoned==(code==-2));}
 reset(0,0);contended=true;assert(!nabuLogRead(nullptr,1,1,out)&&calls==0&&ticks<=55);contended=false;
 reset(0,0);host.selected=false;assert(!nabuLogRead(nullptr,1,1,out)&&calls==0);host.selected=true;
 nabu_log_volume.validated=1;nabu_log_volume.file_first=3163313;
 for(int code:{8,0x629}){reset(code,99);
  assert(nabuLogIo(true,3163314,1,out)==-1&&calls==1);
  assert(nabuLogIo(false,3163314,1025,nullptr,true)==-1&&calls==2);}
 reset(0,0);assert(nabuLogIo(true,3163313,1,out)==-1&&calls==0);
 assert(nabuLogIo(true,49692663,1,out)==-1&&calls==0);
 assert(nabuLogIo(false,49692663,1,out)==-1&&calls==0);
 puts("PASS production journal I/O: transient recovery/exhaustion, short/malformed/permanent failures, lock deadline, unchanged write and sync gates");
}
'''.replace('FUNCTIONS', functions).replace('EXPECTED_SUCCESS', '0' if args.before else '1').replace('EXPECTED_CALLS', '1' if args.before else '3')
with tempfile.TemporaryDirectory(prefix='b5q-log-read-') as temp:
    temp = Path(temp)
    (temp / 'test.cpp').write_text(harness)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    '-Wno-misleading-indentation', '-fsanitize=address,undefined',
                    '-I', str(root / 'UniXNU-b5q/package/B5qUfs'),
                    str(temp / 'test.cpp'), '-o', str(temp / 'test')], check=True)
    subprocess.run([str(temp / 'test')], check=True)
