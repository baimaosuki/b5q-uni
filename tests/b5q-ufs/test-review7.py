#!/usr/bin/env python3
"""Review7 production boot-wait deadlines and causal transport regressions."""
from pathlib import Path
import subprocess,tempfile,json,hashlib
R=Path(__file__).resolve().parents[2]
source=(R/'UniXNU-b5q/package/B5qBluetooth.cpp').read_text()
wait=source[source.index('void waitUntil('):source.index('\nuint32_t urd(',source.index('void waitUntil('))]
with tempfile.TemporaryDirectory(prefix='b5q-review7-')as td:
 t=Path(td)
 prefix=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include "B5qBtFifo.h"
using event_t=void*;
#define THREAD_UNINT 0
#define THREAD_AWAKENED 1
#define THREAD_CONTINUE_NULL nullptr
static struct {struct{void*va;}uart;bool gated;unsigned pending;b5q_bt_fifo geni;}bt;
static uint64_t observed;static unsigned blocks;
static void assert_wait(event_t,int){observed=UINT64_MAX;}
static void nanoseconds_to_absolutetime(uint64_t n,uint64_t *p){*p=n;}
static void assert_wait_deadline(event_t,int,uint64_t n){observed=n;}
static void *current_thread(){return nullptr;}
static void clear_wait(void*,int){}
static void thread_block(void*){blocks++;}
'''
 main=r'''
int main(){
 bt.uart.va=&bt;bt.geni.retry_at=1000;
 waitUntil(nullptr,1000000);assert(observed==1000&&blocks==1);
 waitUntil(nullptr,100);assert(observed==100&&blocks==2);
 bt.gated=true;waitUntil(nullptr,1000000);assert(observed==1000000);
 bt.gated=false;bt.geni.retry_at=0;waitUntil(nullptr,UINT64_MAX);assert(observed==UINT64_MAX);
 bt.pending=1;unsigned before=blocks;waitUntil(nullptr,1);assert(blocks==before&&!bt.pending);
 puts("PASS actual qbt_boot waitUntil merges FIFO progress deadlines; gated/off/pending wake retain semantics");
}
'''
 (t/'test.cpp').write_text(prefix+wait+main)
 flags=['-g','-O1','-fsanitize=address,undefined','-I'+str(R/'UniXNU-b5q/package'),'-I'+str(R/'sources/UniXNU-sheng/drivers/QcaBluetooth/src')]
 subprocess.run(['cc',*flags,'-std=c11','-c',str(R/'UniXNU-b5q/package/B5qBtFifo.c'),'-o',str(t/'fifo.o')],check=True)
 subprocess.run(['c++',*flags,'-std=c++17',str(t/'test.cpp'),str(t/'fifo.o'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test')],check=True)
for name in ['bt-fifo','bt-wcn6855','wifi-platform','pcie-firmware-dma','log-writer']:
 subprocess.run(['python3',str(R/'tests/b5q-ufs'/('test-'+name+'.py'))],check=True)
print('PASS review7 focused production causal regression suite; hardware results pending')
