#!/usr/bin/env python3
"""Execute the real Data request/lock/DMA completion path with mocked UFS MMIO."""
from pathlib import Path
import subprocess,tempfile
ROOT=Path(__file__).resolve().parents[2]
s=(ROOT/'UniXNU-b5q/package/B5qUfs/B5qDataBlock.h').read_text()
a=s.index('static IOReturn dataIo(');b=s.index('\nstatic IOReturn dataFlush(',a);body=s[a:b]
pre=r'''
#include <cassert>
#include <cstdio>
#include <cstring>
#include <cstdint>
#include <mutex>
#include <thread>
#include <vector>
#include <atomic>
#include "B5qDataFormat.h"
using namespace B5qFormat;using namespace B5qUfsProtocol;
using IOReturn=int;
constexpr int kIOReturnNotReady=1,kIOReturnIOError=2,kIOReturnBadArgument=3,kIOReturnSuccess=0;
constexpr unsigned dmaBytes=0x25000,fatalStatus=0x71880;
struct IOLock {std::mutex lock;};
void IOLockLock(IOLock *p){p->lock.lock();}void IOLockUnlock(IOLock *p){p->lock.unlock();}
struct Transport{IOLock *lock;bool poisoned=false;uint8_t lun=0;uintptr_t hc=1;uint8_t *dma;};
static IOLock shared;alignas(4096) static uint8_t rootDma[dmaBytes],privateDataDma[dmaBytes];
static Transport host={&shared,false,0,1,rootDma};static bool dataRequested=true;static unsigned dataFlushed=0;
static void *dataMemory=privateDataDma;static uint8_t *dataDma=privateDataDma;
static uint64_t dataPhysical=0x8d0000000ULL;
static B5qData::Volume dataVolume={B5qData::tailFirst+256,7864064,{},{},true};
static uint32_t doorbell,statusReg;static unsigned fault;static std::atomic<unsigned> submissions{0};
static uint32_t read32(uintptr_t,unsigned reg){return reg==0x58?doorbell:reg==0x20?statusReg:0;}
static void clean(void *,size_t){}
static void write32(uintptr_t,unsigned reg,uint32_t value){
 if(reg==0x20){statusReg&=~value;return;}assert(reg==0x58&&value==2&&doorbell==0);
 doorbell=value;++submissions;
 auto *utrd=reinterpret_cast<uint32_t*>(rootDma+32);
 uint64_t command=utrd[4]|(uint64_t(utrd[5])<<32);
 assert(command==dataPhysical+commandOffset);
 uint8_t *ucd=privateDataDma+commandOffset;
 assert(ucd[3]==1&&ucd[2]==0);
 uint8_t opcode=ucd[16];assert(opcode==0x28||opcode==0x2a||opcode==0x35);
 if(opcode!=0x35){uint64_t lba=be32(ucd+18);assert(lba>=dataVolume.first&&lba<dataVolume.first+dataVolume.blocks);}
 if(opcode==0x2a)assert(ucd[17]==8);
 if(opcode==0x28)memset(privateDataDma+dataOffset,0xa7,4096);
 uint8_t *rsp=ucd+responseOffset;rsp[0]=0x21;rsp[2]=0;rsp[3]=fault==2?0:1;rsp[7]=fault==3?2:0;
 utrd[2]=fault==4?1:0;
}
static bool waitValue(unsigned reg,uint32_t mask,uint32_t value,unsigned){assert(reg==0x58&&mask==2&&!value);if(fault==1)return false;doorbell=0;return true;}
#define IOLog(...) ((void)0)
'''
post=r'''
int main(){
 uint8_t buffer[4096]={};assert(dataIo(B5qData::Direction::Read,0,1,buffer)==0&&buffer[0]==0xa7);
 assert(dataIo(B5qData::Direction::Write,0,1,buffer)==0);
 assert(dataIo(B5qData::Direction::Sync,0,0,nullptr)==0);
 unsigned before=submissions;
 for(auto dir:{B5qData::Direction::Read,B5qData::Direction::Write}) {
  assert(dataIo(dir,UINT64_MAX,1,buffer)==kIOReturnBadArgument);
  assert(dataIo(dir,dataVolume.blocks,1,buffer)==kIOReturnBadArgument);
  assert(dataIo(dir,0,UINT32_MAX,buffer)==kIOReturnBadArgument);
 }
 assert(submissions==before);
 // Late APFS tail transactions must remain writable after driver notification.
 assert(dataFlushed==1);assert(dataIo(B5qData::Direction::Write,0,1,buffer)==0);
 assert(dataFlushed==0);assert(dataIo(B5qData::Direction::Sync,0,0,nullptr)==0);assert(dataFlushed==1);
 for(unsigned error:{1,2,3,4}){
  fault=error;host.poisoned=false;doorbell=0;
  assert(dataIo(B5qData::Direction::Write,0,1,buffer)==kIOReturnIOError);
  assert(host.poisoned==(error!=3));
 }
 fault=0;host.poisoned=false;doorbell=0;before=submissions;
 std::vector<std::thread> workers;
 for(unsigned t=0;t<8;++t)workers.emplace_back([t]{
  uint8_t own[4096]={};
  for(unsigned i=0;i<1000;++i){
   if(t%3==0){assert(dataIo(B5qData::Direction::Write,i%100,1,own)==0);}
   else if(t%3==1){assert(dataIo(B5qData::Direction::Read,i%100,1,own)==0);assert(own[0]==0xa7);}
   else { // Root/journal tag0 owns the same queue lock and never Data's page.
    IOLockLock(host.lock);assert(!doorbell);memset(rootDma,0x5a,dmaBytes);
    assert(&privateDataDma[0]!=&rootDma[0]);IOLockUnlock(host.lock);
   }
  }
 });
 for(auto &t:workers)t.join();assert(submissions==before+6000);
 puts("PASS actual production dataIo: tag1/UCD/page separation, 8000 concurrent Data/root/logger queue iterations, direction/range failures, shutdown gate/flush, timeout/OCS/wrong-tag/SCSI errors");
}
'''
with tempfile.TemporaryDirectory(prefix='b5q-dataqueue-') as td:
 p=Path(td);source=p/'queue.cpp';source.write_text(pre+body+post)
 exe=p/'queue';subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-Wno-misleading-indentation','-fsanitize=address,undefined','-pthread','-I',str(ROOT/'UniXNU-b5q/package/B5qUfs'),str(source),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True)
