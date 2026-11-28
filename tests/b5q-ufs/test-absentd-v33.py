#!/usr/bin/env python3
"""Exercise the whole patched production absentd with host XPC import stand-ins."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
TC = ROOT/'tools/llvm21/usr'
compiler = TC / 'lib/llvm-21/bin/clang'
environment = dict(os.environ, LD_LIBRARY_PATH=str(TC / 'lib/x86_64-linux-gnu'))
with tempfile.TemporaryDirectory(prefix='b5q-absent-test-') as tmp:
    work = Path(tmp)
    (work / 'absentd.c').write_bytes((ROOT / 'UniXNU/scripts/absent-service/absentd.c').read_bytes())
    subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-d', str(work)], check=True,
                   input=(ROOT / 'UniXNU-b5q/patches/tools/b5q-absentd-user-domains.patch').read_bytes())
    for folder in ['dispatch', 'xpc']:
        (work / folder).mkdir()
    (work / 'dispatch/dispatch.h').write_text('''
void *dispatch_get_main_queue(void);
void dispatch_main(void) __attribute__((noreturn));
''')
    (work / 'xpc/xpc.h').write_text('''
typedef void *xpc_object_t;
typedef void *xpc_connection_t;
#define XPC_TYPE_CONNECTION ((void *)1)
#define XPC_TYPE_ERROR ((void *)2)
#define XPC_ERROR_CONNECTION_INVALID ((void *)3)
#define XPC_CONNECTION_MACH_SERVICE_LISTENER 1
xpc_connection_t xpc_connection_create_mach_service(const char *,void *,unsigned);
void xpc_connection_set_event_handler(xpc_connection_t,void (^)(xpc_object_t));
void xpc_connection_activate(xpc_connection_t);
void xpc_connection_cancel(xpc_connection_t);
void *xpc_get_type(xpc_object_t);
void xpc_transaction_begin(void);
''')
    harness = r"""
#include <assert.h>
#include <setjmp.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdarg.h>
#include <sys/types.h>
#include <fcntl.h>
#include <unistd.h>
static char output[8192];
static int scenario, listeners, activated, cancelled, transactions, cases;
static jmp_buf resident;
void *_NSConcreteStackBlock[32];
void *_NSConcreteGlobalBlock[32];
int mock_open(const char *p,int flags,...) {(void)flags;assert(!strcmp(p,"/dev/console"));return scenario==4?-1:7;}
ssize_t mock_write(int fd,const void *data,size_t len) {assert(fd==7||fd==2);strncat(output,data,len);return (ssize_t)len;}
int mock_close(int fd){assert(fd==7);return 0;}
#define open mock_open
#define write mock_write
#define close mock_close
#define main production_main
#include "absentd.c"
#undef main
#undef open
#undef write
#undef close
void *dispatch_get_main_queue(void){return (void *)1;}
void dispatch_main(void){assert(transactions==1);longjmp(resident,1);}
void xpc_transaction_begin(void){assert(!transactions);++transactions;}
xpc_connection_t xpc_connection_create_mach_service(const char *n,void *q,unsigned f){assert(transactions==1);(void)n;(void)q;(void)f;++listeners;return scenario==3?NULL:(void *)4;}
void xpc_connection_set_event_handler(xpc_connection_t c,void(^block)(xpc_object_t)){
 if(c==(void *)4){block(XPC_ERROR_CONNECTION_INVALID);block((void *)5);}
}
void xpc_connection_activate(xpc_connection_t c){(void)c;++activated;}
void xpc_connection_cancel(xpc_connection_t c){(void)c;++cancelled;}
void *xpc_get_type(xpc_object_t o){return o==XPC_ERROR_CONNECTION_INVALID?XPC_TYPE_ERROR:XPC_TYPE_CONNECTION;}
static void reset(int mode){scenario=mode;output[0]=0;listeners=activated=cancelled=transactions=0;}
static void expect_resident(const char *label,const char *arg,int mode){
 reset(mode);
 if(label)setenv("XPC_SERVICE_NAME",label,1);else unsetenv("XPC_SERVICE_NAME");
 char *args[]={(char *)arg,NULL};
 if(!setjmp(resident)){production_main(1,args);assert(!"service unexpectedly exited");}
 assert(strstr(output,"transaction-held")&&strstr(output,"resident")&&transactions==1);
 if(mode==3)assert(listeners&&strstr(output,"listener-create-failed")&&!activated);
 else assert(listeners&&cancelled==listeners);
 ++cases;
}
int main(void){
 char *early[]={"/usr/libexec/endpointsecurityd",NULL};
 reset(0);unsetenv("XPC_SERVICE_NAME");assert(production_main(1,early)==0);assert(strstr(output,"boot-task-exit")&&!transactions);++cases;
 reset(0);setenv("XPC_SERVICE_NAME","",1);assert(production_main(1,early)==0);assert(!transactions);++cases;
 reset(0);setenv("XPC_SERVICE_NAME","../invalid",1);assert(production_main(0,NULL)==78);assert(strstr(output,"invalid-label-exit"));++cases;
 char long_label[300];memset(long_label,'x',sizeof long_label);long_label[299]=0;
 reset(0);setenv("XPC_SERVICE_NAME",long_label,1);assert(production_main(0,NULL)==78);++cases;
 for(unsigned i=0;i<sizeof jobs/sizeof jobs[0];++i){
  expect_resident(jobs[i].label,"b5q-absentd",0);
  expect_resident(NULL,jobs[i].path,0);
  expect_resident("",strrchr(jobs[i].path,'/')+1,0);
 }
 expect_resident("com.apple.security.cryptexd","b5q-absentd",3);
 expect_resident("com.apple.mobileactivationd","b5q-absentd",4);
 // All real original plists enable pressured exit. With no outstanding
 // transaction a clean process is eligible; the resident replacement keeps
 // one transaction even after cancelling every XPC peer request.
 assert(transactions==1);
 printf("PASS: %d whole-production cases; 5 source jobs, label fallback, early-task success, transaction held before listeners, cancelled peers, denied console, no plist reads\n",cases);
}
"""
    (work / 'test.c').write_text(harness)
    command = [str(compiler), '-std=gnu11', '-fblocks', '-fsanitize=address,undefined',
               '-fno-sanitize-link-runtime', '-lasan', '-lubsan',
               '-Wall', '-Wextra', '-Werror', '-I', str(work), str(work / 'test.c'), '-o', str(work / 'test')]
    subprocess.run(command, check=True, env=environment)
    subprocess.run([str(work / 'test')], check=True, env=environment)
