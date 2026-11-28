"""Execute GPIO19 race/active-contact timeout and actual publish->tap path."""
from pathlib import Path
import subprocess,tempfile
R=Path(__file__).resolve().parents[2];s=(R/'UniXNU-b5q/package/B5qTouch.cpp').read_text()
def function(signature):
 a=s.index(signature);b=s.index('{',a)+1;depth=1
 while depth:depth+=(s[b]=='{')-(s[b]=='}');b+=1
 return s[a:b]
publish=function('void publish(bool fromReport=true)').replace('__asm__ volatile("dmb ish" ::: "memory");','').replace('__asm__ volatile("dmb ish":::"memory");','')
body=r'''
#include <cstdint>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <vector>
#include "B5qTouchReports.h"
#include "B5qTouchMouse.h"
using event_t=void*;using wait_result_t=int;
constexpr int THREAD_UNINT=0,THREAD_AWAKENED=1,THREAD_TIMED_OUT=2,THREAD_CONTINUE_NULL=0,kMillisecondScale=1000000;
B5qTouch::Reports reports;unsigned frames=0;uint32_t native_touch_seq=0,native_touch_count=0,native_touch_recovered=0,native_touch_hid_reports=0;
int native_touch_xs[12],native_touch_ys[12],native_touch_ids[12];
void (*sink)(void*)=nullptr;void *sinkContext=nullptr;
uint32_t irqEvents=0,now=0;bool attention=false;unsigned registered=0,cleared=0,blocked=0,timers=0,logs=0;
int inject=0;wait_result_t wakeResult=THREAD_TIMED_OUT;
void *current_thread(){return nullptr;}
void arm(){registered++;if(inject==1)irqEvents++;if(inject==2)attention=true;}
void assert_wait(event_t e,int flags){assert(e==&irqEvents&&flags==0);arm();}
void assert_wait_timeout(event_t e,int flags,unsigned ms,unsigned scale){assert(e==&irqEvents&&flags==0&&ms==40&&scale==1000000);timers++;arm();}
bool lowAttention(){return attention;}
void clear_wait(void *,int why){assert(why==1);cleared++;}
int thread_block(int continuation){assert(!continuation);blocked++;now+=40;if(inject==3)irqEvents++;if(inject==4)attention=true;return wakeResult;}
template<class...A>void IOLog(const char*,A...){logs++;}
static unsigned b5q_display_rotation(){return 0;} // report timeout/click behavior is independent of display policy
PUBLISH
WAIT
int main(){
 for(bool active:{false,true})for(inject=0;inject<5;inject++){
  reports={};if(active)reports.points[0]={100,200,1};attention=false;irqEvents=registered=cleared=blocked=timers=0;
  native_touch_count=active;native_touch_recovered=0;frames=0;wakeResult=THREAD_TIMED_OUT;
  waitAttention();
  assert(registered==1&&timers==unsigned(active));
  assert(cleared==unsigned(inject==1||inject==2)&&blocked==unsigned(inject!=1&&inject!=2));
  const bool lift=active&&inject==0;
  assert(activeCount()==unsigned(active&&!lift));assert(frames==unsigned(lift));
  if(lift)assert(!native_touch_count&&!native_touch_recovered);
 }
 reports.points[0]={100,200,1};attention=false;inject=0;wakeResult=THREAD_AWAKENED;waitAttention();assert(activeCount()==1); // no false release on a wake/spurious signal
 // Full sensor frames stop after finger-up. Real publish passes recovered=0
 // into the unchanged pointer and the 40ms timeout creates a normal click.
 B5qTouchMouse mouse;std::vector<std::pair<unsigned,unsigned>>buttons;
 auto send=[&](const uint8_t*p){buttons.push_back({now,p[1]});};
 struct Context{B5qTouchMouse *mouse;decltype(send)*sendFn;};Context context{&mouse,&send};sinkContext=&context;
 sink=[](void*p){auto*c=static_cast<Context*>(p);c->mouse->update(native_touch_count,native_touch_ids,native_touch_xs,native_touch_ys,now,native_touch_recovered,*c->sendFn);};
 now=10;reports={};reports.mode=0x11;reports.points[0]={1000,1000,1};publish(true);now=90;publish(true);assert(buttons.empty());
 wakeResult=THREAD_TIMED_OUT;waitAttention();assert(now==130&&!native_touch_count&&!native_touch_recovered&&mouse.clicks_left==1&&mouse.held==1);
 now=161;mouse.advance(now,send);assert(buttons.size()==1);now=162;mouse.advance(now,send);
 assert(buttons.size()==2&&buttons[0].second==1&&buttons[1].second==0&&buttons[1].first-buttons[0].first==32);
 puts("PASS productionactiveGPIOwait40ms->normalpublish->tap32ms;idleIRQonly;register/recheck,IRQduringtimeout,ATTNlow,spuriouswake allpreventfalse-lift");
}
'''.replace('PUBLISH',publish).replace('WAIT',function('unsigned activeCount()')+'\n'+function('void waitAttention(){'))
with tempfile.TemporaryDirectory(prefix='b5q-touch-wait-')as td:
 p=Path(td)/'test.cpp';p.write_text(body);exe=p.with_suffix('')
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=address,undefined','-I',str(R/'UniXNU-b5q/package'),str(p),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True)
