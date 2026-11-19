#!/usr/bin/env python3
"""Prove actual ESP allocation with the production C GPT/FAT checker, without a phone."""
import argparse,hashlib,json,struct,subprocess,tempfile,zlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];BLOCK=4096;ESP_FIRST=3162880;LUN_BLOCKS=62275584
TOKEN='411839cbaebac4088c251c0ea57579a2'

def verify(esp,out=None):
 esp=Path(esp).resolve();assert esp.stat().st_size==800*2**20
 entries=bytearray(512*128);entries[:16]=bytes.fromhex('28732ac11ff8d211ba4b00a0c93ec93b');entries[16:32]=bytes(range(16));struct.pack_into('<QQ',entries,32,ESP_FIRST,3367679);entries[56:64]='esp\0'.encode('utf-16le')
 entries[128:144]=bytes([1])*16;struct.pack_into('<QQ',entries,160,49692663,62275574);entries[184:204]='macosroot\0'.encode('utf-16le')
 header=bytearray(BLOCK);header[:8]=b'EFI PART';struct.pack_into('<II',header,8,0x10000,92);struct.pack_into('<QQQQ',header,24,1,LUN_BLOCKS-1,265,LUN_BLOCKS-10);struct.pack_into('<QIII',header,72,2,512,128,zlib.crc32(entries));struct.pack_into('<I',header,16,zlib.crc32(header[:92]))
 with tempfile.TemporaryDirectory(prefix='b5q-esp-log-proof-') as tmp:
  tmp=Path(tmp);metadata=tmp/'gpt';metadata.write_bytes(bytes(BLOCK)+header+entries)
  cpp=tmp/'proof.cpp';cpp.write_text(r'''
#include <cstdio>
#include <cassert>
#include <cstdlib>
#include "B5qLogVolume.h"
static FILE *esp,*gpt;static nb_log_volume vol;
static int read(void*,uint64_t lba,uint32_t n,uint8_t*p){
 FILE*f;if(lba>=3162880&&lba+n<=3367680){f=esp;lba-=3162880;}else {assert(lba>=1&&lba+n<=18);f=gpt;}
 return !fseeko(f,lba*4096,SEEK_SET)&&fread(p,4096,n,f)==n;
}
int main(int argc,char**argv){assert(argc==3);esp=fopen(argv[1],"rb");gpt=fopen(argv[2],"rb");assert(esp&&gpt);
 uint8_t token[16]={0x41,0x18,0x39,0xcb,0xae,0xba,0xc4,0x08,0x8c,0x25,0x1c,0x0e,0xa5,0x75,0x79,0xa2};
 if(!nb_volume_open(&vol,read,nullptr,62275584,token)){fprintf(stderr,"volume proof: %s\n",nb_volume_failure_name(vol.failure));return 1;}
 assert(nb_volume_write_allowed(&vol,vol.file_first+1,2050));assert(!nb_volume_write_allowed(&vol,vol.file_first,1));assert(!nb_volume_write_allowed(&vol,vol.file_first+2050,2));
 uint8_t b[4096];for(unsigned i=1;i<2051;++i){assert(read(nullptr,vol.file_first+i,1,b));for(uint8_t c:b)assert(!c);}
 printf("%llu %u %u %u\n",(unsigned long long)vol.file_first,vol.file_cluster,vol.fat_blocks,vol.reads);
}
''')
  exe=tmp/'proof';subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=address,undefined','-I'+str(ROOT/'UniXNU-b5q/package/B5qUfs'),str(cpp),'-o',str(exe)],check=True)
  p=subprocess.run([str(exe),str(esp),str(metadata)],capture_output=True,text=True,check=True);first,cluster,fat,reads=map(int,p.stdout.split())
  with esp.open('rb') as f:
   f.seek((first-ESP_FIRST)*BLOCK);data=f.read(8400896)
  report={'scope':'Actual ESP bytes; GPT harness uses user-provided exact extents, not device evidence','result':'PASS','file_bytes':len(data),'file_sha256':hashlib.sha256(data).hexdigest(),'token':TOKEN,'file_first_lba':first,'clusters':2051,'contiguous':True,'no_aliases':True,'mirrored_FAT':True,'fat_blocks_each':fat,'config_readonly':True,'write_first_lba':first+1,'write_last_lba':first+2050,'committed_slots':0,'source_GPT_entries':512,'production_volume_checker':True,'hardware_tested':False}
  if out:Path(out).write_text(json.dumps(report,indent=2)+'\n')
  return report
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--esp',type=Path,required=True);p.add_argument('--out',type=Path);a=p.parse_args();print(json.dumps(verify(a.esp,a.out),indent=2))
