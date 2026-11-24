#!/usr/bin/env python3
"""Exercise original TFA9878 optimal settings, register profiles and bounded lifecycle."""
from pathlib import Path
import subprocess,tempfile,re
R=Path(__file__).resolve().parents[2]
original=R/'artifacts/b5q-p4-work/samsung-source/full/qcom/opensource/audio-kernel/asoc/codecs/tfa9878/tfa_init.c'
s=original.read_text();begin=s.index('static enum tfa98xx_error tfa9878_specific(');end=s.index('static int tfa9878_set_swprofile',begin);s=s[begin:end]
rows=[]
for rev in ['0x0a78','0x1a78']:
 begin=s.index('case '+rev+':');end=s.index('break;',begin)
 values=[(int(reg,16),int(value,16))for reg,value in re.findall(r'reg_write\(tfa, (0x[0-9a-fA-F]+), (0x[0-9a-fA-F]+)\)',s[begin:end])]
 rows.append(','.join('{'+f'{r},{v}'+'}'for r,v in values))
code=r'''
#include <cassert>
#include <cstdio>
#include <vector>
#include <fstream>
#include <iterator>
#include "B5qTfa9878.h"
using namespace B5qTfa;
struct W{uint8_t reg;uint16_t value;};
W optimal0[]={ROW0},optimal1[]={ROW1};
struct Io {
 uint16_t regs[256]{},rev=0x0a78;unsigned calls=0,failAt=0,delays=0,clockAfter=0,stateAfter=0,clockPolls=0,statePolls=0;std::vector<W>writes;
 bool read(uint8_t a,uint8_t r,uint16_t&v){assert(a==0x34||a==0x35);calls++;if(calls==failAt)return false;
  v=r==3?rev:r==0x10?(++clockPolls>clockAfter?0x40:0):r==0x14?(++statePolls>stateAfter?9<<3:0):regs[r];return true;}
 bool write(uint8_t a,uint8_t r,uint16_t v){assert(a==0x34||a==0x35);calls++;if(calls==failAt)return false;regs[r]=v;writes.push_back({r,v});return true;}
 void delay(unsigned us){assert(us==1000);delays+=us;}
};
int main(int argc,char**argv){assert(argc==2);std::ifstream f(argv[1],std::ios::binary);std::vector<uint8_t>b((std::istreambuf_iterator<char>(f)),{});Container cnt;assert(cnt.init(b.data(),b.size()));unsigned cases=0;
 for(uint8_t addr:{0x34,0x35})for(uint16_t rev:{0x0a78,0x1a78}){
  Program p;assert(cnt.program(addr,"default",p));Io io;io.rev=rev;Amplifier<Io> amp(io,addr);assert(amp.prepare(p)&&amp.prepared()&&!amp.running());
  assert(io.writes[0].reg==0&&io.writes[0].value==2);const auto *expected=rev==0x0a78?optimal0:optimal1;unsigned n=rev==0x0a78?sizeof(optimal0)/sizeof(W):sizeof(optimal1)/sizeof(W);
  assert(io.writes[1].reg==0x0f&&io.writes[2].reg==0xa0&&io.writes[3].reg==0x0f&&io.writes[4].reg==0xa1);
  for(unsigned i=0;i<n;++i)assert(io.writes[5+i].reg==expected[i].reg&&io.writes[5+i].value==expected[i].value);
  assert((io.regs[0]&9)==1);unsigned prepCalls=io.calls;io.clockAfter=3;io.stateAfter=4;assert(amp.start()&&amp.running()&&amp.polls==9&&io.delays==7000);assert((io.regs[0]&9)==8);assert(amp.quiesce()&&!amp.running()&&(io.regs[0]&9)==1);cases++;
  for(unsigned fail=1;fail<=prepCalls;++fail){Io bad;bad.rev=rev;bad.failAt=fail;Amplifier<Io>a(bad,addr);assert(!a.prepare(p)&&!a.prepared()&&!a.running());assert(a.error!=Amplifier<Io>::Error::None);cases++;}
  for(unsigned fail=1;fail<=8;++fail){Io bad;bad.rev=rev;Amplifier<Io>a(bad,addr);assert(a.prepare(p));bad.failAt=bad.calls+fail;bool started=a.start();if(!started){assert(!a.running()&&(bad.regs[0]&9)==1);}cases++;}
  for(bool clock:{false,true}){Io slow;slow.rev=rev;Amplifier<Io>a(slow,addr);assert(a.prepare(p));if(clock)slow.stateAfter=100;else slow.clockAfter=100;assert(!a.start()&&!a.running()&&(slow.regs[0]&9)==1);assert(slow.delays==50000);cases++;}
 }
 {Program p;assert(cnt.program(0x34,"default",p));Io bad;bad.rev=0xffff;Amplifier<Io>a(bad,0x34);assert(!a.prepare(p)&&bad.writes.empty());p.updates[0].address=0x35;assert(!a.prepare(p)&&bad.writes.empty());cases+=2;}
 printf("PASS source-extractedTFA9878optimal0a78/1a78,2originalstereoprofiles,boundedclock/state,start/stop/transferfaults; %u cases ASanUBSan\n",cases);
}
'''.replace('ROW0',rows[0]).replace('ROW1',rows[1])
with tempfile.TemporaryDirectory(prefix='b5q-tfa9878-')as td:
 td=Path(td);src=td/'test.cpp';src.write_text(code)
 subprocess.run(['c++','-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=address,undefined','-I'+str(R/'UniXNU-b5q/package'),str(src),'-o',str(td/'test')],check=True)
 subprocess.run([str(td/'test'),str(R/'artifacts/firmware-b5q/F7310ZCS7EYF3/vendor/firmware/tfa98xx.cnt')],check=True)
