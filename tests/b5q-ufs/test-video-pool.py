#!/usr/bin/env python3
"""Exercise the production retained-pool allocator and Iris copy/lifetime code."""
from pathlib import Path
import subprocess,tempfile
R=Path(__file__).resolve().parents[2]
source=(R/'UniXNU-b5q/package/B5qVideoMemory.cpp').read_text()
def function(signature):
    start=source.index(signature);end=source.index('{',start)+1;depth=1
    while depth:depth+=(source[end]=='{')-(source[end]=='}');end+=1
    return source[start:end]
code=r'''
#include <cassert>
#include <cerrno>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include <random>
#include <algorithm>
#include "B5qMediaPool.h"
using Pool=B5qMedia::Pool<2048>;
Pool *pool;
constexpr int kIODirectionInOut=0,kIOReturnSuccess=0;
struct IOMemoryDescriptor {
    std::vector<uint8_t> data;
    bool failPrepare=false,failRead=false,failWrite=false;
    unsigned refs=1,prepares=0,completes=0;
    IOMemoryDescriptor(size_t n):data(n){}
    size_t getLength(){return data.size();}
    int prepare(int){if(failPrepare)return 1;++prepares;return 0;}
    void complete(int){++completes;}
    void retain(){++refs;}
    void release(){assert(refs>1);--refs;}
    size_t readBytes(size_t at,void *to,size_t n){assert(at<=data.size()&&n<=data.size()-at);if(failRead)return 0;memcpy(to,data.data()+at,n);return n;}
    size_t writeBytes(size_t at,const void *from,size_t n){assert(at<=data.size()&&n<=data.size()-at);if(failWrite)return 0;memcpy(data.data()+at,from,n);return n;}
};
struct QcomIrisBuffer {IOMemoryDescriptor *memory;uint32_t iova;uint64_t offset,bytes;void *cpu,*map;uint64_t clientBytes;};
void barrier(){}
void b5q_video_release(QcomIrisBuffer *);
FUNCTIONS
int main(){
 void *base=nullptr;assert(!posix_memalign(&base,0x200000,0x8000000));
 Pool p;pool=&p;assert(p.init(base,0x40000000,0x8000000));assert(!p.init(base,0x40000000,0x8000000));
 {Pool bad;assert(!bad.init(base,0xfffff000,0x2000));assert(!bad.init(base,0,0x8001000));assert(!bad.init(base,1,4096));}
 uint32_t bus=0;assert(!p.allocate(UINT64_MAX,4096,&bus));assert(!p.allocate(4096,4097,&bus));assert(!p.allocate(4096,4096,nullptr));
 void *small=p.allocate(4096,4096,&bus);assert(small&&bus==0x40000000);
 void *aligned=p.allocate(4096,0x100000,&bus);assert(aligned&&bus==0x40100000);
 assert(!p.release(static_cast<char*>(small)+1));assert(!p.contains(static_cast<char*>(small)+4095,2));
 assert(p.release(small)&&p.release(aligned)&&p.count==1&&p.used==0);
 std::mt19937 rng(0x8550);struct Allocation {void *p;uint32_t bytes,bus;};std::vector<Allocation> live;
 for(unsigned i=0;i<12000;++i) {
  if(!live.empty()&&(rng()%3==0)){const size_t at=rng()%live.size();assert(p.release(live[at].p));live.erase(live.begin()+at);}
  else {
   uint32_t bytes=(rng()%64+1)*4096,alignment=4096u<<(rng()%5);
   void *a=p.allocate(bytes,alignment,&bus);if(!a)continue;
   assert(!(bus&(alignment-1))&&p.contains(a,bytes));
   for(const auto &b:live)assert(uint64_t(bus)+bytes<=b.bus||uint64_t(b.bus)+b.bytes<=bus);
   live.push_back({a,bytes,bus});
  }
 }
 for(auto a:live)assert(p.release(a.p));assert(p.count==1&&p.used==0);
 void *all=p.allocate(0x8000000,4096,&bus);assert(all&&!p.allocate(1,4096,&bus));assert(p.release(all));
 IOMemoryDescriptor memory(16384);for(size_t i=0;i<memory.data.size();++i)memory.data[i]=uint8_t(i);
 QcomIrisBuffer b{};assert(!b5q_video_map(&memory,123,6000,&b));assert(memory.refs==2&&memory.prepares==1);
 assert(b.clientBytes==6000&&b.offset==123&&b.bytes==8192);
 assert(b5q_video_input(&b,6000));assert(!memcmp(static_cast<char*>(b.cpu)+123,memory.data.data()+123,6000));
 memory.data[123]=0xab;assert(b5q_video_input(&b,6000));assert(static_cast<uint8_t*>(b.cpu)[123]==0xab);
 assert(!b5q_video_input(&b,6001));assert(!b5q_video_output(&b,5999,2));assert(!b5q_video_output(&b,UINT64_MAX,1));
 memory.failRead=true;assert(!b5q_video_input(&b,1));memory.failRead=false;
 memset(static_cast<uint8_t*>(b.cpu)+123+10,0xcd,200);assert(b5q_video_output(&b,10,200));
 for(unsigned i=0;i<200;++i)assert(memory.data[123+i]==0xcd);
 memory.failWrite=true;assert(!b5q_video_output(&b,0,1));memory.failWrite=false;
 b5q_video_release(&b);assert(!b.cpu&&memory.refs==1&&memory.completes==1&&p.used==0);
 b5q_video_release(&b);assert(memory.completes==1);
 memory.failPrepare=true;assert(b5q_video_map(&memory,0,6000,&b)==-ENOMEM&&!b.cpu&&p.used==0);
 assert(b5q_video_map(&memory,16385,1,&b)==-EINVAL);assert(b5q_video_map(&memory,1,UINT64_MAX,&b)==-EINVAL);
 assert(!b5q_video_allocate(8193,4096,&b)&&b.bytes==12288&&b.clientBytes==8193);b5q_video_release(&b);
 assert(!b5q_video_input(nullptr,1)&&!b5q_video_output(nullptr,0,1));
 free(base);
 puts("PASS production128MiBpool:12000fragmentation/overlap/alignment/exhaustion operations; Iris repeated input/output-offset/bounds/wiring/fault lifetime ASanUBSan");
}
'''
code=code.replace('FUNCTIONS','\n'.join(function(n)for n in [
    'bool copyBounds(', 'int b5q_video_allocate(', 'int b5q_video_map(',
    'void b5q_video_release(', 'bool b5q_video_input(', 'bool b5q_video_output(']))
with tempfile.TemporaryDirectory(prefix='b5q-video-pool-')as td:
    td=Path(td);(td/'test.cpp').write_text(code)
    subprocess.run(['c++','-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-Wno-misleading-indentation',
        '-fsanitize=address,undefined','-fno-omit-frame-pointer','-I'+str(R/'UniXNU-b5q/package'),str(td/'test.cpp'),'-o',str(td/'test')],check=True)
    subprocess.run([str(td/'test')],check=True)
