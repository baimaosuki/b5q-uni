#!/usr/bin/env python3
"""Review19: exercise the actual patch helpers and GPU logging under sanitizers."""
import argparse, hashlib, json, os, re, subprocess, tempfile, tomllib
from pathlib import Path
R=Path(__file__).resolve().parents[2]
ap=argparse.ArgumentParser(description=__doc__)
ap.add_argument('--out',type=Path,default=Path(os.environ.get('B5Q_GATE_WORK',R/'artifacts/b5q-review19-local')))
W=ap.parse_args().out.resolve();W.mkdir(parents=True,exist_ok=True);checks=[]
def run(name,cmd):
 p=subprocess.run(list(map(str,cmd)),cwd=R,capture_output=True,text=True)
 output=p.stdout+p.stderr;(W/(name+'.log')).write_text(output)
 if p.returncode:raise RuntimeError(name+'\n'+output[-6000:])
 checks.append(dict(name=name,passed=True,command=list(map(str,cmd)),log_sha256=hashlib.sha256(output.encode()).hexdigest()));print('PASS',name,flush=True)
def block(text,signature):
 start=text.index(signature);at=text.index('{',start);end=at+1;depth=1
 while depth:
  depth+=(text[end]=='{')-(text[end]=='}');end+=1
 return text[start:end]
patch=(R/'UniXNU-b5q/patches/xnu/b5q-cpu-burn-trace.patch').read_text()
added='\n'.join(line[1:] for line in patch.splitlines() if line.startswith('+') and not line.startswith('+++'))
claim=block(added,'static unsigned\nb5q_cpu_burn_claim(')
context=block(added,'__attribute__((noinline)) static void\nb5q_cpu_burn_context(')
assert '#if __arm64__ && defined(MACH_BSD)' in added
assert 'b5q_cpu_burn_context(thread, task, pid, procname);' in added
assert not any(s in added for s in ['PE_parse_boot_argn','task_terminate','exception_triage','send_resource_violation'])
assert all(s in added for s in ['<arm/thread.h>','<kern/backtrace.h>','<kdp/kdp_dyld.h>','<libkern/copyio.h>','<vm/vm_protos.h>'])
assert (R/'UniXNU-b5q/patches/xnu/series').read_text().count('b5q-cpu-burn-trace.patch')==1
# The existing monitor and EXC_RESOURCE decisions must be untouched.
assert not any(line.startswith('-') and not line.startswith('---') for line in patch.splitlines())
checks.append(dict(name='additive-arm64-current-thread-monitor-path',passed=True))
with tempfile.TemporaryDirectory(prefix='review19-',dir=W) as td:
 t=Path(td)
 source=r'''
#include <assert.h>
#include <stdint.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include <pthread.h>
#include <stdlib.h>
static char output[65536];static size_t used;
static int test_printf(const char *fmt,...) {va_list ap;va_start(ap,fmt);int n=vsnprintf(output+used,sizeof(output)-used,fmt,ap);va_end(ap);assert(n>=0 && (size_t)n<sizeof(output)-used);used+=(size_t)n;return n;}
#define printf test_printf
struct task {int unused;};struct thread {struct task *task;};
typedef struct task *task_t;typedef struct thread *thread_t;
static struct task task_storage,kernel_storage;static task_t kernel_task=&kernel_storage;
static struct thread thread_storage={&task_storage},other_thread={&task_storage};
static thread_t current_thread(void){return &thread_storage;}
static task_t current_task(void){return &task_storage;}
static task_t get_threadtask(thread_t t){return t->task;}
static int process,pid_value=287;static void *bsd=&process;
static void *current_proc(void){return &process;}
static void *get_bsdtask_info(task_t t){(void)t;return bsd;}
static int proc_selfpid(void){return pid_value;}
static unsigned long long thread_tid(thread_t t){assert(t==current_thread());return 1600;}
typedef struct {int valid;} arm_saved_state_t;static arm_saved_state_t state={1};
static arm_saved_state_t *get_user_regs(thread_t t){assert(t==current_thread());return &state;}
static int is_saved_state64(arm_saved_state_t *s){return s->valid;}
#define REG(name,n) static unsigned long long get_saved_state_##name(arm_saved_state_t *s){(void)s;return n;}
REG(pc,0x101) REG(lr,0x102) REG(sp,0x103) REG(fp,0x104)
struct backtrace_user_info {int btui_error;unsigned btui_info;};
#define BTUINFO_INIT {0,0}
static unsigned user_calls,kernel_calls;
static unsigned backtrace_user(uintptr_t *f,unsigned n,void *ctl,struct backtrace_user_info *info){assert(n==16 && !ctl);++user_calls;info->btui_error=0;info->btui_info=1;for(unsigned i=0;i<n;++i)f[i]=0x200+i;return n;}
static unsigned backtrace(uintptr_t *f,unsigned n,void *a,void *b){assert(n==8 && !a && !b);++kernel_calls;for(unsigned i=0;i<n;++i)f[i]=0x300+i;return n;}
typedef uintptr_t user_addr_t;
struct user64_dyld_all_image_infos {uint64_t sharedCacheBaseAddress,sharedCacheSlide;unsigned infoArrayCount;};
static uintptr_t task_get_all_image_info_addr(task_t t){assert(t==current_task());return 0x400;}
static int copy_error;
static int copyin(user_addr_t a,void *p,size_t n){assert(a==0x400 && n==sizeof(struct user64_dyld_all_image_infos));if(copy_error)return 14;struct user64_dyld_all_image_infos *i=p;i->sharedCacheBaseAddress=0x500;i->sharedCacheSlide=0x600;i->infoArrayCount=7;return 0;}
'''+claim+'\n'+context+r'''
static unsigned claims[32][2];
static void *race(void *arg){unsigned i=(unsigned)(uintptr_t)arg;unsigned got=0;for(unsigned n=0;n<10000 && got<2;++n){unsigned s=b5q_cpu_burn_claim(1000+(int)i);if(s)claims[i][got++]=s;}return NULL;}
int main(int argc,char **argv){assert(argc==2);
 if(!strcmp(argv[1],"race")){pthread_t threads[32];for(unsigned i=0;i<32;++i)assert(!pthread_create(&threads[i],NULL,race,(void *)(uintptr_t)i));for(unsigned i=0;i<32;++i)assert(!pthread_join(threads[i],NULL));unsigned mask=0,total=0;for(unsigned i=0;i<32;++i)for(unsigned j=0;j<2;++j)if(claims[i][j]){assert(claims[i][j]<=6 && !(mask&(1u<<claims[i][j])));mask|=1u<<claims[i][j];++total;}assert(total==6 && mask==126);return 0;}
 assert(!b5q_cpu_burn_claim(0));assert(!b5q_cpu_burn_claim(-1));
 b5q_cpu_burn_context(&other_thread,current_task(),pid_value,"audiomxd");
 b5q_cpu_burn_context(current_thread(),kernel_task,pid_value,"kernel_task");
 b5q_cpu_burn_context(current_thread(),current_task(),98,"wrong-pid");
 bsd=NULL;b5q_cpu_burn_context(current_thread(),current_task(),pid_value,"no-proc");bsd=&process;
 assert(!used && !user_calls);
 if(!strcmp(argv[1],"copy-fail")){copy_error=1;state.valid=0;}
 b5q_cpu_burn_context(current_thread(),current_task(),pid_value,"audiomxd");
 assert(strstr(output,"B5Q-CPU-BURN: capture=1/6 pid=287 tid=1600 proc=audiomxd\n"));
 assert(strstr(output,"user frame=15 pc=0x20f") && !strstr(output,"user frame=16"));
 assert(strstr(output,"kernel frame=7 pc=0x307") && !strstr(output,"kernel frame=8"));
 if(copy_error){assert(strstr(output,"dyld image-info unavailable"));assert(!strstr(output,"saved pc="));}
 else{assert(strstr(output,"saved pc=0x101 lr=0x102 sp=0x103 fp=0x104"));assert(strstr(output,"dyld cache_base=0x500 cache_slide=0x600 images=7"));}
 b5q_cpu_burn_context(current_thread(),current_task(),pid_value,"audiomxd");size_t at=used;
 for(unsigned i=0;i<10;++i)b5q_cpu_burn_context(current_thread(),current_task(),pid_value,"audiomxd");assert(used==at && user_calls==2 && kernel_calls==2);
 pid_value=97;b5q_cpu_burn_context(current_thread(),current_task(),pid_value,"configd");b5q_cpu_burn_context(current_thread(),current_task(),pid_value,"configd");
 pid_value=99;b5q_cpu_burn_context(current_thread(),current_task(),pid_value,"other");b5q_cpu_burn_context(current_thread(),current_task(),pid_value,"other");at=used;
 pid_value=101;b5q_cpu_burn_context(current_thread(),current_task(),pid_value,"over-cap");assert(used==at && user_calls==6 && kernel_calls==6);assert(strstr(output,"capture=6/6") && !strstr(output,"capture=7/6"));return 0;}
'''
 c=t/'cpu.c';c.write_text(source);binary=t/'cpu'
 run('cpu-burn-compile',['/usr/lib/llvm-17/bin/clang','-std=gnu11','-O1','-g','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=address,undefined','-fno-sanitize-recover=all','-pthread',c,'-o',binary])
 for mode in ['normal','copy-fail','race']:run('cpu-burn-'+mode,[binary,mode])
 gpu=(R/'UniXNU-b5q/package/B5qGpu.cpp').read_text()
 owned=re.search(r'\{unsigned owned = 1;[^\n]+\}',gpu).group()
 assert gpu.count('B5qGpu: coherence %s io=%u owned=%u walk=%u\\n')==2
 assert 'native_adreno_owned_coherent && native_adreno_io_coherent' in (R/'UniXNU/drivers/Adreno740/NativeAdrenoUserClient.cpp').read_text()
 logblock=block(gpu,gpu[gpu.index('    {\n        static char previous[2][64]'):].split('{',1)[0]+'{\n        static char previous[2][64]')
 # Extract only the new bounded block and the actual initial timer read.
 timer=gpu[gpu.index('    uint64_t ticks = 0;',gpu.index('void publishAndWrapperTest')):gpu.index('    {unsigned wc',gpu.index('void publishAndWrapperTest'))]
 src=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cstdarg>
#include <string>
static std::string logs;
static void IOLog(const char *fmt,...){char s[512];va_list ap;va_start(ap,fmt);vsnprintf(s,sizeof s,fmt,ap);va_end(ap);logs+=s;}
static unsigned native_adreno_owned_coherent;static int override_value=-1;
static bool PE_parse_boot_argn(const char *name,void *p,unsigned n){assert(!strcmp(name,"gpu-owned-coherent")&&n==sizeof(unsigned));if(override_value<0)return false;*static_cast<unsigned*>(p)=override_value;return true;}
struct Diag {char report[64]{},report2[64]{};} d;
static void reports()
'''+logblock+r'''
using IOReturn=unsigned;static struct Timer {IOReturn result=0;IOReturn read(uint64_t *ticks){if(result)return result;*ticks=0x1234;return 0;}} gTimer;
static void timerLog(IOReturn timer){
'''+timer+r'''
}
static void start()
'''+owned+r'''
int main(){start();assert(native_adreno_owned_coherent==1);override_value=0;start();assert(!native_adreno_owned_coherent);override_value=1;start();assert(native_adreno_owned_coherent);
 reports();assert(logs.empty());strcpy(d.report,"PUB no device: no cached coherent memory");reports();auto first=logs;reports();assert(logs==first);strcpy(d.report2,"timer fail");reports();assert(logs.find("B5qGpu: report2=timer fail\n")!=std::string::npos);
 memset(d.report,'X',sizeof d.report);reports();assert(logs.find(std::string(63,'X'))!=std::string::npos);
 for(unsigned i=0;i<40;++i){snprintf(d.report,sizeof d.report,"change %u",i);reports();}unsigned count=0;size_t pos=0;while((pos=logs.find("B5qGpu: report",pos))!=std::string::npos){++count;++pos;}assert(count==16);
 timerLog(0);assert(logs.find("timer attach=0 read=0 ticks=0x1234")!=std::string::npos);gTimer.result=0xe00002d8;timerLog(0xe00002d8);assert(logs.find("timer attach=e00002d8 read=e00002d8 ticks=0x0")!=std::string::npos);
}
'''
 cpp=t/'gpu.cpp';cpp.write_text(src);binary=t/'gpu'
 run('gpu-diagnostics-compile',['c++','-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-fno-sanitize-recover=all',cpp,'-o',binary])
 run('gpu-diagnostics-ASan-UBSan',[binary])
args=tomllib.loads((R/'UniXNU-b5q/board.toml').read_text())['payload']['kernel_args']
assert len(' '.join(args).encode())==1023
checks.append(dict(name='hardware-coherence-gate-and-unchanged-1023B-args',passed=True))
(W/'review19-tests.json').write_text(json.dumps(dict(passed=True,hardware_verified=False,checks=checks),indent=2)+'\n')
print('PASS Review19 production helpers, limits, diagnostics; hardware pending')
