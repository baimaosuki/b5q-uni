#!/usr/bin/env python3
"""Stress the production DSP period ownership against foreign/stale completions."""
from pathlib import Path
import subprocess,tempfile
R=Path(__file__).resolve().parents[2]
code=r'''
#include <cassert>
#include <cstdio>
#include <cstdint>
#include <set>
#include "B5qAudioQueue.h"
int main(){using B5qAudio::Queue;Queue q;uint32_t token;
 assert(!q.reserve(0,token)&&!q.init(UINT64_MAX,4,1920)&&!q.init(4096,0,1920)&&!q.init(4096,4,65536));
 assert(q.init(0x1a0000000ULL,77,1920));
 uint32_t t[8];for(unsigned i=0;i<8;i++)assert(q.reserve(i,t[i]));assert(q.pending==8&&!q.reserve(8,token)&&!q.reserve(0,token));
 for(unsigned i=0;i<8;i++){
  assert(!q.complete(q.base+i*1920+1,77,t[i]));assert(!q.complete(q.base+i*1920,78,t[i]));assert(!q.complete(q.base+i*1920,77,t[i]+100));
  assert(q.complete(q.base+i*1920,77,t[i]));assert(!q.complete(q.base+i*1920,77,t[i]));
 }
 assert(q.pending==0);unsigned checks=0;std::set<uint32_t>seen;
 for(unsigned n=0;n<100000;n++){
  unsigned slot=(n*1664525u+1013904223u)%8;assert(q.reserve(slot,token));assert(seen.insert(token).second);
  assert(!q.cancel(slot,token-1)&&q.pending==1);assert(!q.complete(q.base-1,77,token));
  assert(q.complete(q.base+slot*1920,77,token)&&!q.pending);checks+=4;
 }
 assert(q.reserve(1,token));uint32_t old=token;assert(q.init(0x1a0000000ULL,77,1920)&&!q.pending);assert(q.reserve(1,token)&&token!=old);
 assert(!q.complete(q.base+1920,77,old)&&q.complete(q.base+1920,77,token));
 q.nextToken=UINT32_MAX;assert(q.reserve(0,token)&&token==1&&q.cancel(0,token));
 puts("PASS actual DSP8period ownership:400000stale/foreign/bounds/reuse checks,duplicate/out-of-order/restart/tokenwrap underASanUBSan");
}
'''
with tempfile.TemporaryDirectory(prefix='b5q-audio-queue-')as td:
 td=Path(td);(td/'test.cpp').write_text(code)
 subprocess.run(['c++','-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-I'+str(R/'UniXNU-b5q/package'),str(td/'test.cpp'),'-o',str(td/'test')],check=True)
 subprocess.run([str(td/'test')],check=True)
