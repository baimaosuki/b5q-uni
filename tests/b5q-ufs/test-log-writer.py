#!/usr/bin/env python3
"""Exercise the production b5q journal worker/transport/volume proof on sparse media."""
from pathlib import Path
import importlib.util,json,struct,subprocess,sys,tempfile,zlib
ROOT=Path(__file__).resolve().parents[2];HEADERS=ROOT/'UniXNU-b5q/package/B5qUfs'
sys.path.insert(0,str(ROOT/'tools/xnu2log/scripts'))
from nabu_log_volume import make_config,decode_container
TOKEN=bytes.fromhex('411839cbaebac4088c251c0ea57579a2');BLOCK=4096;ESP=3162880;ROOT_FIRST=49692663;ROOT_LAST=62275574;CAPACITY=62275584;FILE_BYTES=8400896

def disk(path,case):
 count=512;stride=128;entries=bytearray(count*stride)
 entries[:16]=bytes.fromhex('28732ac11ff8d211ba4b00a0c93ec93b');struct.pack_into('<QQ',entries,32,ESP,ESP+204800-1);entries[56:64]='esp\0'.encode('utf-16le')
 entries[128:144]=bytes([1])*16;struct.pack_into('<QQ',entries,160,ROOT_FIRST,ROOT_LAST);entries[184:204]='macosroot\0'.encode('utf-16le')
 if case=='overlap':struct.pack_into('<QQ',entries,160,ESP,ROOT_LAST)
 if case=='rootbounds':struct.pack_into('<Q',entries,160,ROOT_FIRST+1)
 header=bytearray(BLOCK);header[:8]=b'EFI PART';struct.pack_into('<II',header,8,0x10000,92);struct.pack_into('<QQQQ',header,24,1,CAPACITY-1,265,CAPACITY-10);struct.pack_into('<QIII',header,72,2,count,stride,zlib.crc32(entries));struct.pack_into('<I',header,16,zlib.crc32(header[:92]))
 boot=bytearray(BLOCK);struct.pack_into('<H',boot,11,BLOCK);boot[13]=1;struct.pack_into('<H',boot,14,32);boot[16]=2;struct.pack_into('<II',boot,32,204800,200);struct.pack_into('<I',boot,44,2);boot[82:87]=b'FAT32';boot[510:512]=b'\x55\xaa'
 fat=bytearray(200*BLOCK);struct.pack_into('<III',fat,0,0xffffff8,0xfffffff,0xfffffff)
 for i in range(2051):struct.pack_into('<I',fat,(3+i)*4,4+i if i<2050 else 0xfffffff)
 if case=='chain':struct.pack_into('<I',fat,4*4,8)
 if case=='fatalias':struct.pack_into('<I',fat,3000*4,4)
 directory=bytearray(BLOCK);directory[:11]=b'XNU2LOG BIN';directory[11]=0x20;struct.pack_into('<H',directory,26,3);struct.pack_into('<I',directory,28,FILE_BYTES)
 if case=='diralias':directory[32:43]=b'OTHER   BIN';directory[43]=0x20;struct.pack_into('<H',directory,58,4)
 first=ESP+433;config=make_config(TOKEN if case!='token' else bytes([9])*16)
 with path.open('wb') as f:
  f.truncate(CAPACITY*BLOCK)
  for lba,value in [(1,header),(2,entries),(ESP,boot),(ESP+32,fat),(ESP+232,fat),(ESP+432,directory),(first,config)]:f.seek(lba*BLOCK);f.write(value)
  if case=='mirror':f.seek((ESP+232)*BLOCK+12);f.write(bytes(4))
  if case=='gptcrc':f.seek(2*BLOCK+32);f.write(bytes(8))
  if case=='damagedslots':
   for lba in [first+1,first+1026]:f.seek(lba*BLOCK);f.write(b'BROKEN')
 return first

HARNESS=r'''
#include <cassert>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <vector>
#include <string>
#include <cstdlib>
#define NABU_LOG_IMPLEMENTATION
#include "B5qLogCore.h"
#include "B5qLogProtocol.h"
#include "B5qLogArgs.h"
using namespace B5qUfsProtocol;
static void *IOMalloc(size_t n){return malloc(n);}
static void IOFree(void*p,size_t){free(p);}
typedef int IOReturn;typedef int wait_result_t;typedef void* thread_t;
#define KERN_SUCCESS 0
#define kMillisecondScale 1
#define IOLog(...) std::printf(__VA_ARGS__)
static constexpr uint32_t dmaBytes=0x25000,fatalStatus=0x71880;
static uint8_t dma[dmaBytes];
static struct {bool selected=true,poisoned=false;void*lock=(void*)1;uint8_t lun=3;uint64_t capacity[8]={0,0,0,62275584};uint8_t*dma=::dma;uint64_t physical=0x900000000;uintptr_t hc=1;uint8_t opcode,commandLun;uint64_t commandLba;const char*stage;uint32_t lastOcs=0;Status status;}host;
static FILE*media;static bool held,quarantine;static unsigned submissions,writes,syncs;static int fail_header;
static uint64_t ticks;
static uint32_t read32(uintptr_t,unsigned){return 0;}
static void write32(uintptr_t,unsigned,uint32_t){}
static bool IOLockTryLock(void*){if(held)return false;held=true;if(quarantine)host.poisoned=true;return true;}
static void IOLockUnlock(void*){assert(held);held=false;}
static uint64_t mach_absolute_time(){return ++ticks;}
static void clock_interval_to_deadline(unsigned n,int,uint64_t*d){*d=ticks+n;}
static void thread_yield_internal(int);
static void thread_terminate(thread_t){throw 1;}
static thread_t current_thread(){return nullptr;}
static void thread_deallocate(thread_t){}
static int kernel_thread_start(void(*f)(void*,int),void*p,thread_t*t){*t=nullptr;f(p,0);return 0;}
static std::string bootargs="b5q-log=1 b5q-log-token=411839cbaebac4088c251c0ea57579a2";
static const char* PE_boot_args(){return bootargs.c_str();}
extern "C" volatile unsigned nabu_log_writer_rounds;
static bool submit(){
 assert(held);++submissions;
 auto*u=dma+commandOffset;assert(u[0]==1&&u[2]==3);auto*c=u+16;auto*utrd=(uint32_t*)dma;
 uint64_t lba=be32(c+2);unsigned blocks=(unsigned(c[7])<<8)|c[8];unsigned bytes=be32(u+12);
 host.lastOcs=0;
 if(c[0]==0x35){assert(!bytes&&!(utrd[0]&(3U<<25))&&!u[1]&&!blocks&&!lba);for(unsigned i=1;i<16;++i)assert(!c[i]);++syncs;}
 else {
  assert(bytes==blocks*4096 && blocks<=32);assert(!fseeko(media,lba*4096,SEEK_SET));
  if(c[0]==0x2a){assert(c[1]==8 && u[1]==0x20 && (utrd[0]&(3U<<25))==(1U<<25));++writes;
   assert(lba>3163313 && lba+blocks<=3163313+2051);
   if(fail_header && nabu_log_writer_rounds==1 && blocks==1){host.poisoned=true;return false;}
   assert(fwrite(dma+dataOffset,1,bytes,media)==bytes);
  }else {assert(c[0]==0x28 && u[1]==0x40 && (utrd[0]&(3U<<25))==(2U<<25));
   assert((lba>=1&&lba+blocks<=265)||(lba>=3162880&&lba+blocks<=3367680));
   assert(fread(dma+dataOffset,1,bytes,media)==bytes);
  }
 }
 auto*r=u+responseOffset;memset(r,0,512);r[0]=0x21;r[2]=3;return true;
}
#include "B5qLogUfs.h"
static void thread_yield_internal(int){
 ticks+=1;
 if(nabu_log_writer_rounds==1){static bool appended;if(!appended){nabu_capture_append("LATE-BOOT\n",10);appended=true;}}
 if(nabu_log_writer_rounds>=2)throw 2;
}
int main(int argc,char**argv){
 assert(argc==4);media=fopen(argv[1],"r+b");assert(media);fail_header=atoi(argv[2]);bool negative=atoi(argv[3]);
 static nb_log_volume fixture;nabu_log_volume_ptr=&fixture;
 uint8_t token[16];assert(b5qLogArgs(bootargs.c_str(),token));
 for(const char*s:{"b5q-log=0 b5q-log-token=411839cbaebac4088c251c0ea57579a2","b5q-log=1 b5q-log-token=123","b5q-log=1 b5q-log-token=00000000000000000000000000000000","b5q-log=1 b5q-log=1 b5q-log-token=411839cbaebac4088c251c0ea57579a2"})assert(!b5qLogArgs(s,token));
 // Root protocol cannot ever emit journal writes or SYNC.
 uint8_t cdb[16]={0x2a};assert(!allowed(3,cdb,4096));cdb[0]=0x35;assert(!allowed(3,cdb,0));
 memset(dma,0xa5,sizeof(dma));uint8_t payload[4096]={};
 held=true;assert(nabuLogIo(false,1,1,payload)==0);held=false;assert(!submissions);
 quarantine=true;assert(nabuLogIo(false,1,1,payload)==-1);assert(!submissions&&!held);
 for(uint8_t c:dma)assert(c==0xa5);quarantine=false;host.poisoned=false;
 assert(!b5qLogRequest((uint32_t*)dma,dma+commandOffset,host.physical,3,host.capacity[3],&nabu_log_volume,true,false,3163314,1));
 std::vector<uint8_t> ring(NB_LOG_CAPACITY);
 nabu_capture_append("EARLY-BOOT\n",11);
 assert(nabu_capture_expand(ring.data()));
 uint8_t early[11];assert(nabu_capture_copy(0,11,early)&&!memcmp(early,"EARLY-BOOT\n",11));
 std::vector<char> text(NB_LOG_CAPACITY+77);for(unsigned i=0;i<text.size();++i)text[i]='a'+i%26;
 nabu_capture_append(text.data(),text.size());
 nabu_capture_lock=1;nabu_capture_append("DROP",4);nabu_capture_lock=0;
 nb_log_snapshot snap;assert(nabu_capture_snapshot(&snap)&&snap.lost==4&&snap.length==NB_LOG_CAPACITY);
 try{nabuLogStart();}catch(int){}
 if(negative){assert(!writes&&!syncs&&nabu_log_writer_failures==1);fclose(media);return 0;}
 assert(writes>0 && syncs>=2 && !held);assert(nabu_log_writer_rounds==(fail_header?1u:2u));
 assert(!nb_volume_write_allowed(&nabu_log_volume,nabu_log_volume.file_first,1));
 for(uint64_t lba:{1ULL,3162880ULL,49692663ULL,62275574ULL,static_cast<unsigned long long>(nabu_log_volume.file_first+2051)})assert(!nb_volume_write_allowed(&nabu_log_volume,lba,1));
 assert(!nb_volume_write_allowed(&nabu_log_volume,nabu_log_volume.file_first+2050,2));
 assert(nb_volume_write_allowed(&nabu_log_volume,nabu_log_volume.file_first+1,2050));
 assert(!b5qLogRequest((uint32_t*)dma,dma+commandOffset,host.physical,3,host.capacity[3],&nabu_log_volume,true,true,0,0));
 // Whole-LUN wire SYNC is still gated by the caller's proven journal extent.
 for(uint64_t lba:{0ULL,1ULL,3162880ULL,49692663ULL,static_cast<unsigned long long>(nabu_log_volume.file_first)})
  assert(!b5qLogRequest((uint32_t*)dma,dma+commandOffset,host.physical,3,host.capacity[3],&nabu_log_volume,false,true,lba,1025));
 assert(!b5qLogRequest((uint32_t*)dma,dma+commandOffset,host.physical,3,host.capacity[3],&nabu_log_volume,false,true,nabu_log_volume.file_first+1,0));
 assert(!b5qLogRequest((uint32_t*)dma,dma+commandOffset,host.physical,3,host.capacity[3],&nabu_log_volume,false,true,nabu_log_volume.file_first+2050,2));
 fclose(media);return 0;
}
'''
def main():
 results=[]
 with tempfile.TemporaryDirectory(prefix='b5q-logger-test-') as temp:
  temp=Path(temp);(temp/'kern').mkdir();(temp/'kern/clock.h').write_text('')
  cpp=temp/'writer.cpp';cpp.write_text(HARNESS);exe=temp/'writer'
  subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wno-misleading-indentation','-fsanitize=address,undefined','-I'+str(HEADERS),'-I'+str(temp),str(cpp),'-o',str(exe)],check=True)
  for case in ['ok','headerfail','mirror','chain','fatalias','diralias','token','gptcrc','overlap','rootbounds','damagedslots']:
   image=temp/'disk';first=disk(image,case)
   with image.open('rb') as f:f.seek(ESP*BLOCK);metadata=f.read(433*BLOCK)
   run=subprocess.run([str(exe),str(image),'1' if case=='headerfail' else '0','0' if case in ['ok','headerfail'] else '1'],capture_output=True,text=True,timeout=90)
   if run.returncode:raise RuntimeError(case+'\n'+run.stdout+run.stderr)
   with image.open('rb') as f:
    f.seek(ESP*BLOCK);assert f.read(len(metadata))==metadata
    f.seek(first*BLOCK);container=f.read(FILE_BYTES)
   assert container[:BLOCK]==make_config(TOKEN if case!='token' else bytes([9])*16)
   if case in ['ok','headerfail']:
    text,info=decode_container(container);assert info['sequence']==(1 if case=='headerfail' else 2);assert len(text)==4<<20
    if case=='ok':assert text.endswith(b'LATE-BOOT\n')
    saved=temp/'XNU2LOG.BIN';saved.write_bytes(container)
    subprocess.run([sys.executable,str(ROOT/'tools/xnu2log/scripts/read_xnu2log.py'),str(saved),'--out',str(temp/'console.txt')],check=True,capture_output=True)
    assert (temp/'console.txt').read_bytes()==text
   elif case!='damagedslots':assert not any(container[BLOCK:])
   assert TOKEN.hex() not in run.stdout
   results.append(case);image.unlink()
 report={'result':'PASS','production_worker_transport_volume_ring':results,'nonzero_discovered_lun':3,'gpt_entries':512,'metadata_and_config_unchanged':True,'original_decoder_compatible':True,'ASan_UBSan':True,'hardware_tested':False}
 out=ROOT/'artifacts/b5q-log-v13-work';out.mkdir(parents=True,exist_ok=True);(out/'logger-tests.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
