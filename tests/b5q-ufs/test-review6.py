#!/usr/bin/env python3
"""Execute WCN EGPIO ownership and TouchComm publication production paths."""
from pathlib import Path
import subprocess,tempfile,sys
R=Path(__file__).resolve().parents[2];P=R/'UniXNU-b5q/package'
ns={'__file__':str(R/'tests/b5q-ufs/test-v33d-review2.py')};s=(R/'tests/b5q-ufs/test-v33d-review2.py').read_text();exec(compile(s[:s.index("run('BCM-ARC'")],'<runner>','exec'),ns)
f,run,base=ns['function'],ns['run'],ns['base']
w=(P/'B5qWcnPower.cpp').read_text()
run('review6-egpio-pad-ownership',base+r'''
#include "B5qWcnPowerCore.h"
#include <cerrno>
struct Pad{uint32_t cfg=0,latch=0,written=0;bool present=false,input=false,dirty=false;unsigned settle=0,highs=0;};
Pad pads[205];unsigned waited=0;bool ignoreOwnership=false;
struct Reg{unsigned offset;operator uint32_t()const{auto &p=pads[offset/0x1000];return offset%0x1000==0?p.cfg:(p.latch&2)|unsigned(p.input);}void operator=(uint32_t v){auto &p=pads[offset/0x1000];p.dirty=true;p.settle=0;if(offset%0x1000==0){p.written=v;p.cfg=(v&~(1u<<11))|(p.present?1u<<11:0);if(ignoreOwnership)p.cfg&=~(1u<<12);}else p.latch=v&2;}};
std::vector<Reg> regs(0x100000/4);struct{Reg *va;}tlmm={regs.data()};
bool prepared=true;struct{unsigned owners=3;}power;void*lock=nullptr;
bool ensureLock(){return true;}void IOLockLock(void*){}void IOLockUnlock(void*){}void barrier(){}void IOLog(const char*,...){}
void IODelay(unsigned us){waited+=us;for(auto&p:pads)if(p.dirty){p.settle+=us;if(p.settle>=50){bool next=(p.cfg&(1u<<9))&&(p.latch&2)&&(!p.present||(p.cfg&(1u<<12)));if(!p.input&&next)p.highs++;p.input=next;p.dirty=false;}}}
void IOSleep(unsigned ms){IODelay(ms*1000);}
ENABLE
int main(){for(unsigned i=0;i<regs.size();i++)regs[i].offset=i*4;
 for(unsigned radio=0;radio<2;radio++)for(unsigned present=0;present<2;present++){
  for(auto&p:pads)p={};for(unsigned p:{204u,80u,81u}){pads[p].present=present;pads[p].cfg=present?0xa00:0x200;}
  waited=0;assert(!b5q_wcn_radio_enable(radio,1));assert(pads[204].highs==1&&pads[radio?81:80].input&&!pads[204].input);
  assert(pads[204].written==(present?0x1200u:0x200u));assert((pads[radio?81:80].written&(1u<<12))==(present?1u<<12:0));assert(waited>=50*4);
  assert(!b5q_wcn_radio_enable(radio,0)&&!pads[radio?81:80].input);
 }
 for(auto&p:pads)p={};pads[204].present=true;pads[204].cfg=0x800;ignoreOwnership=true;
 assert(b5q_wcn_radio_enable(0,1)==EIO&&!pads[80].input&&!pads[204].highs);ignoreOwnership=false;
 for(auto&p:pads)p={};pads[204].cfg=1u<<12;assert(!b5q_wcn_radio_enable(0,1));assert(pads[204].written==0x1200);
 puts("PASS actualWCNpower:ROpresentBIT11/pad50ussettle/ownershipBIT12required;GPIO204writes1200andhighs;WLAN80+BT81claim;dropownershipfailsbeforeEN;existingownershippreserved");}
'''.replace('ENABLE',f(w,'extern "C" int b5q_wcn_radio_enable(')))
t=(P/'B5qTouch.cpp').read_text()
run('review6-fullframe-kind2-rejected',base+r'''
#include "B5qTouchReports.h"
B5qTouch::Reports reports;uint32_t native_touch_seq=0,native_touch_count=0,native_touch_recovered=0,native_touch_hid_reports=0;
int native_touch_xs[12],native_touch_ys[12],native_touch_ids[12];unsigned frames=0;void(*sink)(void*)=nullptr;void*sinkContext=nullptr;
void IOLog(const char*,...){}
PUBLISH
int main(){reports.mode=0x11;reports.points[0]={2467,2330,2};reports.points[1]={100,200,1};publish();assert(native_touch_count==1&&native_touch_ids[0]==1);reports.points[1]={};publish();assert(!native_touch_count);reports.mode=0xc1;reports.points[0]={100,200,1};publish();assert(native_touch_count==1);puts("PASS actualpublish:mode11kind2ghostexcluded,kind1only;emptyframepublisheslift;nativeC1kind1retained");}
'''.replace('PUBLISH',f(t,'void publish(').replace('__asm__ volatile("dmb ish" ::: "memory");','').replace('__asm__ volatile("dmb ish":::"memory");','')))
