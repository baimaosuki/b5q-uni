from pathlib import Path
import tempfile,subprocess
root=Path(__file__).resolve().parents[2];s=(root/'UniXNU-b5q/package/B5qTouch.cpp').read_text()
a=s.index('void waitAttention(){');b=s.index('\nbool powerTouch()',a);body=s[a:b]
stub=r'''
#include <cstdint>
#include <cassert>
#include <cstdio>
using event_t=void*;
constexpr int THREAD_UNINT=0,THREAD_AWAKENED=1,THREAD_CONTINUE_NULL=0;
uint32_t irqEvents=0;bool attention=false;unsigned registered=0,cleared=0,blocked=0;
int inject=0;
void *current_thread(){return nullptr;}
void assert_wait(event_t e,int flags){assert(e==&irqEvents&&flags==0);registered++;if(inject==1)irqEvents++;if(inject==2)attention=true;}
bool lowAttention(){return attention;}
void clear_wait(void *,int why){assert(why==1);cleared++;}
void thread_block(int continuation){assert(!continuation);blocked++;}
'''
test=r'''
int main(){
 for(inject=0;inject<3;inject++){
  attention=false;irqEvents=registered=cleared=blocked=0;waitAttention();
  assert(registered==1&&cleared==(inject?1u:0u)&&blocked==(inject?0u:1u));
 }
 puts("PASS production GPIO19wait: event registered before rechecking ATTN/eventcounter,IRQ/pin races cannot lose a wakeup;idle blocks once");
}
'''
with tempfile.TemporaryDirectory(prefix='b5q-touch-wait-')as td:
 p=Path(td)/'test.cpp';p.write_text(stub+body+test);exe=p.with_suffix('');subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(p),'-o',str(exe)],check=True);subprocess.run([str(exe)],check=True)
