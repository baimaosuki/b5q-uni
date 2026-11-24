#!/usr/bin/env python3
"""Check real Samsung ACDB TDM settings and production GPR/AudioReach encoding."""
import importlib.util,json,struct,subprocess,sys,tempfile
from pathlib import Path
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'UniXNU-b5q/scripts'))
from b5q_audio import prepare_protocol
s=importlib.util.spec_from_file_location('acdb',R/'scripts/b5q-install/extract-b5q-audio-topology.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
stock=m.extract(m.DEFAULT);assert stock['input']['sha256']=='e243d8fc25d5afda8e7e9abfd45b6e3548b8dd2076174e52bc390ff14dbe0120'
assert len(stock['all_TDM_rows'])==12
# Deliberately truncate table/data bounds and mutate an actual chunk length.
b=m.DEFAULT.read_bytes()
for at in [0,4,11,12,19,0x3032a,0x3119a,0x143876,len(b)-1]:
 try:m.Acdb(b[:at]);raise AssertionError('truncation accepted')
 except ValueError:pass
for at in [16,0x31196,0x48aba]:
 bad=bytearray(b);struct.pack_into('<I',bad,at,0xffffffff)
 try:m.Acdb(bad);raise AssertionError('oversize chunk accepted')
 except ValueError:pass
with tempfile.TemporaryDirectory(prefix='b5q-audio-tdm-')as td:
 td=Path(td);sources,includes=prepare_protocol(R/'sources/UniXNU-sheng',td/'generated')
 code=r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <assert.h>
#include "ShengAudioReach.h"
#include "ShengGpr.h"
#include "B5qAudioTdm.h"
typedef uint32_t (*Open)(uint8_t*,uint32_t,uint32_t,uint32_t);
typedef uint32_t (*Config)(uint8_t*,uint32_t,uint32_t,uint32_t,const ArFormat*);
static uint32_t le32(const uint8_t*p){return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static uint16_t le16(const uint8_t*p){return (uint16_t)p[0]|(uint16_t)p[1]<<8;}
static unsigned checks;
static uint32_t find(uint8_t*b,uint32_t n,uint32_t iid,uint32_t pid,uint32_t*bytes){
 GprPacket p;assert(gpr_decode(b,n,&p)==GprOk&&p.opcode==AR_OP_SET_CFG&&p.token==17&&p.src_port==99);
 assert(le32(p.payload+12)==p.payload_bytes-16);
 for(uint32_t at=40;at<n;){assert(at+16<=n);uint32_t sz=le32(b+at+8);assert(sz<=n-at-16);if(le32(b+at)==iid&&le32(b+at+4)==pid){*bytes=sz;return at+16;}at+=16+((sz+7)&~7u);}
 return 0;
}
static void guards(Open open,Config config,const ArFormat*f){
 uint8_t storage[2050];uint32_t full=open?open(storage+1,2048,99,17):config(storage+1,2048,99,17,f);assert(full);
 for(unsigned cap=0;cap<=2048;cap++){
  memset(storage,0xa5,sizeof storage);uint32_t got=open?open(storage+1,cap,99,17):config(storage+1,cap,99,17,f);
  assert(got==(cap<full?0:full)&&storage[0]==0xa5&&storage[cap+1]==0xa5);checks++;
 }
}
int main(void){uint8_t b[2048];uint32_t size,at,n;
 const ArFormat stream={48000,16,2},endpoint={48000,24,2};
 guards(ar_open_speaker_device,0,0);guards(0,ar_config_speaker_device,&endpoint);guards(0,ar_config_playback_stream,&stream);
 n=ar_open_speaker_device(b,sizeof b,99,17);int module=0;
 for(unsigned i=0;i+8<=n;i++)if(le32(b+i)==0x0700100e&&le32(b+i+4)==AR_IID_SPEAKER_I2S)module++;
 assert(module==1);
 n=ar_config_speaker_device(b,sizeof b,99,17,&endpoint);
 at=find(b,n,AR_IID_SPEAKER_I2S,0x0800101b,&size);assert(at&&size==28&&!memcmp(b+at,b5q_tdm_stereo_config,28));
 assert(le32(b+at+12)==3&&le16(b+at+16)==4&&le16(b+at+18)==32&&le16(b+at+24)==1);
 at=find(b,n,AR_IID_SPEAKER_I2S,0x08001017,&size);assert(at&&le32(b+at)==48000&&le16(b+at+4)==24&&le16(b+at+6)==2);
 n=ar_config_playback_stream(b,sizeof b,99,17,&stream);
 at=find(b,n,AR_IID_PLAY_DEC,0x08001008,&size);assert(at&&le16(b+at+12)==16&&le16(b+at+16)==16&&le16(b+at+18)==15);
 at=find(b,n,AR_IID_PLAY_CNV,0x08001008,&size);assert(at&&le16(b+at+12)==24&&le16(b+at+16)==32&&le16(b+at+18)==27&&le16(b+at+22)==3);
 assert(!ar_config_speaker_device(b,sizeof b,99,17,&stream));
 assert(!ar_config_speaker_device(b,sizeof b,99,17,0));
 printf("PASS actualSamsungACDB PRIMARYTDM4x32/2ch24bits and sharedAudioReachGPR modules/configuration,PCM16->24Q27; %u capacity/guard checks ASanUBSan\n",checks);
}
'''
 src=td/'test.c';src.write_text(code)
 subprocess.run(['cc','-std=c11','-O1','-g','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
  *[v for p in [R/'UniXNU-b5q/package',*includes]for v in ['-I',str(p)]],str(src),*map(str,sources),'-o',str(td/'test')],check=True)
 subprocess.run([str(td/'test')],check=True)
