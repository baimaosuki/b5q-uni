#!/usr/bin/env python3
"""Execute production readLba/command with status changes at mutex release."""
import re
import subprocess
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[2]
source = (root / 'UniXNU-b5q/package/B5qUfs/B5qUfs.cpp').read_text()
command = re.search(r'static int command\(.*?\n\}', source, re.S)[0]
read = re.search(r'static bool readLba\(.*?\n\}', source, re.S)[0]
harness = r'''
#include "B5qUfsProtocol.h"
#include <cassert>
#include <cstring>
using namespace B5qUfsProtocol;
constexpr unsigned dmaBytes=0x25000,maxTransfer=128*1024,fatalStatus=0x71880;
static alignas(8) uint8_t dma[dmaBytes];
static struct {bool poisoned=false,selected=true;int lock=1;uintptr_t hc=1;
 uint8_t*dma=::dma;uint64_t physical=0x8c0000000;Status status;
 uint8_t commandLun=0,opcode=0,lun=3;uint64_t commandLba=0,capacity[8]={};
 unsigned lastOcs=0;const char*stage="";}host;
static bool locked;static unsigned calls,pauses,failures;static int condition=8;
static unsigned read32(uintptr_t,unsigned){return 0;}
static void write32(uintptr_t,unsigned,unsigned){}
static void IOLockLock(int){assert(!locked);locked=true;}
static void IOLockUnlock(int){assert(locked);locked=false;
 // Another legal journal request completes on this shared transport.
 host.status={};host.status.scsi=0;host.status.exact=true;}
static void transportDiagnostic(const char*){}
static bool submit(){++calls;auto*r=host.dma+commandOffset+responseOffset;r[0]=0x21;r[2]=3;
 if(calls<=failures){r[7]=uint8_t(condition);
  if(condition==2){r[11]=20;r[33]=18;r[34]=0x70;r[36]=6;r[41]=10;r[46]=0x29;}}
 else memset(host.dma+dataOffset,0x5a,4096);
 return true;}
static void pauseMs(unsigned n){assert(n==10&&!locked);++pauses;}
static bool transportHealthy(){return !host.poisoned;}
COMMAND
READ
int main(){host.capacity[3]=62275584;uint8_t out[4096];
 for(int code:{8,0x28,2}){condition=code;calls=pauses=0;failures=2;memset(out,0xcc,sizeof(out));
  assert(readLba(3,firstLba,1,out));assert(calls==3&&pauses==2&&!locked&&!host.poisoned);
  for(auto b:out)assert(b==0x5a);
 }
 calls=pauses=0;failures=99;condition=8;memset(out,0xcc,sizeof(out));
 assert(!readLba(3,firstLba,1,out));assert(calls==3&&pauses==2);
 for(auto b:out)assert(b==0xcc);
 calls=0;assert(!readLba(0,firstLba,1,out)&&!readLba(3,firstLba-1,1,out));
 assert(!readLba(3,lastLba,2,out)&&!readLba(3,1,1,out,true)&&calls==0);
 // Captured completion is the UA, not the journal's later GOOD response.
 uint8_t cdb[16];assert(readCdb(cdb,firstLba,1));calls=0;failures=1;condition=2;Status status;
 assert(command(3,cdb,4096,out,&status)==2&&status.scsi==2&&status.sense==0x062900);
 assert(host.status.scsi==0&&host.status.exact);
}
'''.replace('\nCOMMAND\n', '\n' + command + '\n').replace('\nREAD\n', '\n' + read + '\n')
harness = harness.replace('#include <cstring>', '#include <cstring>\n#include <initializer_list>')
harness = harness.replace('static alignas(8)', 'alignas(8) static')
with tempfile.TemporaryDirectory(prefix='b5q-read-status-') as tmp:
    tmp = Path(tmp)
    (tmp / 'test.cpp').write_text(harness)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    '-Wno-misleading-indentation', '-fsanitize=address,undefined',
                    '-I', str(root / 'UniXNU-b5q/package/B5qUfs'),
                    str(tmp / 'test.cpp'), '-o', str(tmp / 'test')], check=True)
    subprocess.run([str(tmp / 'test')], check=True)
print('PASS production read/command: transient retries, lock-release status race, exact data, unchanged root/LUN bounds')
