#!/usr/bin/env python3
"""Actual native MX vote uses cmd-db indices and never overwrites a busy TCS."""
from pathlib import Path
import subprocess,tempfile,hashlib
R=Path(__file__).resolve().parents[2]
s=(R/'UniXNU-b5q/package/B5qDpLink.cpp').read_text()
start=s.index(' bool voteMx(');brace=s.index('{',start);depth=0
for at in range(brace,len(s)):
 depth+=(s[at]=='{')-(s[at]=='}')
 if not depth:body=s[start:at+1];break
original=(R/'artifacts/b5q-p5-work/source-extra/drivers/soc/qcom/rpmh-rsc.c').read_bytes()
assert hashlib.sha256(original).hexdigest()=='377364ae666b0d9e333a47e3083293642f65cd8c5c84e391bbd268a4a585cd5a'
assert b'RSC_DRV_STATUS,\t/* zero if tcs is busy */'in original
h=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include "QcomRpmh.h"
#define IOLog(...) ((void)0)
uint64_t ticks=0;volatile uint32_t *registers=nullptr;QcomRscLayout layout{};
bool complete=true,lockReady=true;unsigned barriers=0;
void barrier(){barriers++;}
void IODelay(unsigned us){ticks+=us;if(complete&&ticks>=100){registers[(0xd00+layout.irq_status)/4]|=4;registers[(0xd00+layout.tcs_stride*2+layout.status)/4]=1;}}
struct AppsSmmuLock {bool ready(){return lockReady;}};
struct Hardware {
 struct {volatile uint32_t *va;}rsc;
 QcomRpmhResource mx{};uint64_t nowUs(){return ticks;}
'''
test=r'''
};
int main(){unsigned cases=0;
 for(unsigned version:{2,3}){
  uint32_t regs[0x10000/4]{},before[0x10000/4]{};registers=regs;regs[0]=version<<16;layout=qcom_rsc_layout(regs[0]);
  Hardware hw{{regs},{}};hw.mx.address=0x30000;
  // No register write when hardware declares the TCS busy.
  memcpy(before,regs,sizeof regs);assert(!hw.voteMx(1)&&!memcmp(before,regs,sizeof regs));cases++;
  regs[(0xd00+layout.tcs_stride*2+layout.status)/4]=1;lockReady=false;
  memcpy(before,regs,sizeof regs);assert(!hw.voteMx(1)&&!memcmp(before,regs,sizeof regs));lockReady=true;cases++;
  ticks=0;complete=true;assert(hw.voteMx(3));
  assert(regs[(0xd00+layout.tcs_stride*2+layout.cmd_data)/4]==3);
  assert(!regs[(0xd00+layout.tcs_stride*2+layout.control)/4]&&!regs[(0xd00+layout.tcs_stride*2+layout.cmd_enable)/4]);cases++;
  regs[(0xd00+layout.irq_status)/4]=0;ticks=0;complete=false;
  assert(!hw.voteMx(5)&&ticks==20000);
  // Timeout retains the live command. Neither clearing the trigger nor
  // releasing its command-enable is allowed before completion.
  assert(regs[(0xd00+layout.tcs_stride*2+layout.control)/4]==((1u<<16)|(1u<<24)));
  assert(regs[(0xd00+layout.tcs_stride*2+layout.cmd_enable)/4]==1);cases++;
  regs[(0xd00+layout.tcs_stride*2+layout.status)/4]=0;memcpy(before,regs,sizeof regs);
  assert(!hw.voteMx(0)&&!memcmp(before,regs,sizeof regs));cases++;
  regs[(0xd00+layout.tcs_stride*2+layout.status)/4]=1;regs[(0xd00+layout.irq_status)/4]=4;
  complete=true;ticks=0;assert(hw.voteMx(0)&&!regs[(0xd00+layout.tcs_stride*2+layout.cmd_data)/4]);cases++;
 }
 for(unsigned count=1;count<=16;count++){
  QcomRpmhResource mx{};mx.level_count=count;for(unsigned i=0;i<count;i++)mx.levels[i]=i*64;
  uint32_t index=0;assert(!qcom_rpmh_level_index(&mx,384,&index));
  assert((index<mx.level_count&&mx.levels[index]>=384)==(count>=7));cases++;
 }
 printf("PASS native DP MX RPMh %u old/newlayout/busy/lock/complete/timeout/reap/ARClevel cases ASanUBSan\n",cases);
}
'''
with tempfile.TemporaryDirectory(prefix='b5q-dp-rpmh-')as td:
 t=Path(td);(t/'test.cpp').write_text(h+body+test)
 flags=['-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(R/'UniXNU-b5q/package')]
 subprocess.run(['cc','-std=c11',*flags,'-c',str(R/'UniXNU-b5q/package/QcomRpmh.c'),'-o',str(t/'core.o')],check=True)
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation',*flags,str(t/'test.cpp'),str(t/'core.o'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test')],check=True)
