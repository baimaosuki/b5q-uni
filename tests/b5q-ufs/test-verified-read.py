#!/usr/bin/env python3
"""Run actual root dispatch and batched reads with real SHA256 block checking."""
import argparse
import json
import re
import subprocess
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[2]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--before', type=Path)
a = p.parse_args()
text = (root / 'UniXNU-b5q/package/B5qUfs/B5qUfs.cpp').read_text()
if a.before:
    text = json.loads(a.before.read_text())['UniXNU-b5q/package/B5qUfs/B5qUfs.cpp']['text']
method = re.search(r' IOReturn doAsyncReadWrite\(.*?\n }', text, re.S)[0]
harness = r'''
#include "B5qVerifiedRead.h"
#include "verified_root.h"
#include <openssl/sha.h>
#include <cassert>
#include <cstring>
#include <vector>
#include <cstdio>
using UInt64=uint64_t;using IOReturn=int;
constexpr unsigned maxTransfer=131072;
constexpr int kIOReturnSuccess=0,kIOReturnBadArgument=1,kIOReturnNotWritable=2,kIOReturnIOError=3,kIODirectionIn=1;
static int sha(const void*p,size_t n,uint8_t out[32]){return SHA256((const uint8_t*)p,n,out)!=nullptr;}
static const vr_crypto vr_xnu_crypto={sha,nullptr};
struct IOStorageAttributes{};
static std::vector<uint8_t> media(2*1024*1024),hashes(media.size()/4096*32);
static unsigned reads,failRead;static int corrupt=-1;static bool locked;
static bool rootRead(uint64_t at,uint64_t n,void*out){assert(locked&&at%4096==0&&n%4096==0&&n<=maxTransfer&&at+n<=media.size());
 ++reads;if(reads==failRead)return false;memcpy(out,media.data()+at,n);
 if(corrupt>=0&&uint64_t(corrupt)*4096>=at&&uint64_t(corrupt)*4096<at+n)((uint8_t*)out)[uint64_t(corrupt)*4096-at]^=1;
 return true;}
static void IOLockLock(int){assert(!locked);locked=true;}
static void IOLockUnlock(int){assert(locked);locked=false;}
struct IOMemoryDescriptor {std::vector<uint8_t>data;int direction=kIODirectionIn;unsigned shortCopy=0;
 size_t getLength(){return data.size();}int getDirection(){return direction;}
 uint64_t writeBytes(uint64_t at,const void*p,uint64_t n){if(shortCopy)n=shortCopy;assert(at+n<=data.size());memcpy(data.data()+at,p,n);return n;}};
struct IOStorageCompletion{void(*action)(void*,void*,int,uint64_t);void*target=nullptr;void*parameter=nullptr;};
static int status;static uint64_t actual;static unsigned completions;
static void complete(void*,void*,int s,uint64_t n){assert(!locked);status=s;actual=n;++completions;}
struct Root{struct{uint64_t offset=0,bytes=media.size();}image;vr_view policy;};
struct BaseDisk{virtual ~BaseDisk()=default;
 virtual IOReturn doAsyncReadWrite(IOMemoryDescriptor*,UInt64,UInt64,IOStorageAttributes*,IOStorageCompletion*)=0;};
struct Disk:BaseDisk{Root*root;bool online=true;int readLock=1;uint8_t*bounce;
 Disk(Root*r,uint8_t*b):root(r),bounce(b){}
METHOD
};
int main(){for(size_t i=0;i<media.size();++i)media[i]=uint8_t(i*29+i/4096);
 for(size_t i=0;i<media.size()/4096;++i)assert(sha(media.data()+i*4096,4096,hashes.data()+i*32));
 Root root;root.policy={};root.policy.hashes=hashes.data();root.policy.image_bytes=media.size();root.policy.block_count=media.size()/4096;
 std::vector<uint8_t>scratch(maxTransfer);Disk d(&root,scratch.data());IOStorageCompletion c={complete};
 auto run=[&](uint64_t first,uint64_t count){IOMemoryDescriptor b;b.data.resize(count*512,0xcc);reads=0;completions=0;
 assert(d.doAsyncReadWrite(&b,first,count,nullptr,&c)==0&&completions==1);return b;};
 auto bulk=run(0,2048);assert(status==0&&actual==1048576&&!memcmp(bulk.data.data(),media.data(),1048576));
 printf("one_MiB_read_commands=%u\n",reads);assert(reads==EXPECTED_READS);
 for(unsigned first:{0U,1U,7U,8U,255U})for(unsigned n:{1U,7U,8U,9U,255U,256U,2048U}){
 auto b=run(first,n);assert(status==0&&actual==n*512&&!memcmp(b.data.data(),media.data()+first*512,n*512));}
 corrupt=2;auto damaged=run(1,2048);assert(status==kIOReturnIOError&&actual==2*4096-512);
 assert(!memcmp(damaged.data.data(),media.data()+512,actual));for(size_t i=actual;i<damaged.data.size();++i)assert(damaged.data[i]==0xcc);corrupt=-1;
 failRead=2;auto failed=run(0,2048);assert(status==kIOReturnIOError&&actual==FAIL_PREFIX);
 for(size_t i=actual;i<failed.data.size();++i)assert(failed.data[i]==0xcc);failRead=0;
 IOMemoryDescriptor shortB;shortB.data.resize(4096,0xcc);shortB.shortCopy=23;assert(d.doAsyncReadWrite(&shortB,0,8,nullptr,&c)==0&&status==kIOReturnIOError&&actual==SHORT_PREFIX);
 auto edge=run(media.size()/512-1,1);assert(status==0&&actual==512&&!memcmp(edge.data.data(),media.data()+media.size()-512,512));
 IOMemoryDescriptor b;b.data.resize(512);reads=0;assert(d.doAsyncReadWrite(&b,media.size()/512,1,nullptr,&c)==kIOReturnBadArgument&&reads==0);
 b.direction=2;assert(d.doAsyncReadWrite(&b,0,1,nullptr,&c)==kIOReturnNotWritable&&reads==0);
 puts("PASS actual root dispatch, SHA256 rejection before copy, partial completion, edge and direction bounds");}
'''.replace('METHOD', method)
for name, value in {'EXPECTED_READS':256 if a.before else 8,
                    'FAIL_PREFIX':4096 if a.before else 131072,
                    'SHORT_PREFIX':0 if a.before else 23}.items():
    harness = harness.replace(name, str(value))
with tempfile.TemporaryDirectory(prefix='b5q-verified-read-') as tmp:
    tmp = Path(tmp)
    (tmp / 'test.cpp').write_text(harness)
    flags = ['-fsanitize=address,undefined', '-I', str(root / 'sources/UniXNU/kits/VerifiedRoot/include')]
    subprocess.run(['cc', '-std=c11', *flags, '-c',
                    str(root / 'sources/UniXNU/kits/VerifiedRoot/src/verified_root.c'),
                    '-o', str(tmp / 'vroot.o')], check=True)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    '-Wno-misleading-indentation', *flags,
                    '-I', str(root / 'UniXNU-b5q/package/B5qUfs'), str(tmp / 'test.cpp'),
                    str(tmp / 'vroot.o'), '-lcrypto', '-o', str(tmp / 'test')], check=True)
    subprocess.run([str(tmp / 'test')], check=True)
