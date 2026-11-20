#!/usr/bin/env python3
"""Execute the production fatal-signal selector and bounded context collector."""
import re
import subprocess
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[2]
patch = (root / 'UniXNU-b5q/patches/xnu/b5q-windowserver-signal.patch').read_text()
added = '\n'.join(line[1:] for line in patch.splitlines() if line.startswith('+') and not line.startswith('+++'))
helper = re.search(r'__attribute__\(\(noinline\)\) static void\nb5q_windowserver_signal_context.*?\n}', added, re.S)[0]
harness = r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdatomic.h>
#include <assert.h>
#include <sys/wait.h>
#include <signal.h>
struct reason {unsigned osr_namespace;uint64_t osr_code;};
struct process {char *p_name;struct reason*p_exit_reason;};typedef struct process *proc_t;
struct state {uint64_t pc,lr,sp,fp,far,esr;};typedef struct state arm_saved_state_t;
static struct process ws={"WindowServer",NULL},other={"WindowServerHelper",NULL};
static int enabled=1,foreign=0,missing_state=0,bad_dyld=0;
static unsigned user_calls,kernel_calls,copy_calls;
static struct state saved={0x1a0010000,0x1a0020000,0x123000,0x123100,0xdeadbeef,0x92000004};
static proc_t current_proc(void){return foreign?&other:&ws;}
static void*current_thread(void){return &ws;}static void*current_task(void){return &ws;}
static unsigned long long thread_tid(void*p){assert(p==&ws);return 123;}
static int proc_getpid(proc_t p){assert(p==&ws);return 109;}
static int PE_parse_boot_argn(const char*k,void*p,unsigned n){assert(!strcmp(k,"b5q-ws-signal")&&n==4);memcpy(p,&enabled,4);return 1;}
static arm_saved_state_t*get_user_regs(void*p){assert(p==&ws);return missing_state?NULL:&saved;}
static int is_saved_state64(arm_saved_state_t*p){return p!=NULL;}
#define GET(f) static unsigned long long get_saved_state_##f(arm_saved_state_t*p){return p->f;}
GET(pc) GET(lr) GET(sp) GET(fp) GET(far) GET(esr)
struct backtrace_user_info {int btui_error;unsigned btui_info;};
#define BTUINFO_INIT ((struct backtrace_user_info){0,0})
static unsigned backtrace_user(uintptr_t*p,unsigned n,void*c,struct backtrace_user_info*i){assert(n==16&&!c);++user_calls;i->btui_error=0;for(unsigned j=0;j<n;++j)p[j]=0x100000+j*4;return n;}
static unsigned backtrace(uintptr_t*p,unsigned n,void*c,void*i){assert(n==16&&!c&&!i);++kernel_calls;for(unsigned j=0;j<n;++j)p[j]=0xffff000000000000ULL+j*4;return n;}
typedef uintptr_t user_addr_t;
struct user64_dyld_all_image_infos {unsigned long long sharedCacheBaseAddress,sharedCacheSlide;unsigned infoArrayCount;};
static uintptr_t task_get_all_image_info_addr(void*p){assert(p==&ws);return 0x1000;}
static int copyin(user_addr_t a,void*p,unsigned long n){assert(a==0x1000&&n==sizeof(struct user64_dyld_all_image_infos));++copy_calls;
 struct user64_dyld_all_image_infos i={0x180000000,0x1234000,42};memcpy(p,&i,n);return bad_dyld;}
HELPER
int main(void){
 b5q_windowserver_signal_context(&other,SIGSEGV);foreign=1;b5q_windowserver_signal_context(&ws,SIGSEGV);foreign=0;
 enabled=0;b5q_windowserver_signal_context(&ws,SIGSEGV);enabled=1;
 b5q_windowserver_signal_context(&ws,SIGTERM);b5q_windowserver_signal_context(&ws,1<<8);assert(!user_calls&&!kernel_calls&&!copy_calls);
 int signals[]={SIGSEGV,SIGBUS,SIGILL,SIGABRT};
 for(unsigned i=0;i<4;++i)b5q_windowserver_signal_context(&ws,signals[i]);
 missing_state=1;bad_dyld=1;for(unsigned i=0;i<20;++i)b5q_windowserver_signal_context(&ws,SIGBUS);
 assert(user_calls==8&&kernel_calls==8&&copy_calls==8);
 puts("PASS production fatal-signal selector, saved registers/slide, 16-frame limits, copyin failure, exact name/current-task gates and 8-capture budget");
}
'''.replace('HELPER', helper)
with tempfile.TemporaryDirectory(prefix='b5q-ws-context-') as temp:
    temp = Path(temp)
    (temp / 'context.c').write_text(harness)
    subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-Wno-format',
                    '-fsanitize=address,undefined', str(temp / 'context.c'), '-o', str(temp / 'test')], check=True)
    result = subprocess.run([str(temp / 'test')], check=True, capture_output=True, text=True)
    assert result.stdout.count('B5Q-WS-SIGNAL: user frame=') == 8 * 16
    assert result.stdout.count('B5Q-WS-SIGNAL: kernel frame=') == 8 * 16
    assert result.stdout.count('cache_slide=0x1234000') == 4
    assert 'far=0xdeadbeef esr=0x92000004' in result.stdout
    print(result.stdout.splitlines()[-1])
