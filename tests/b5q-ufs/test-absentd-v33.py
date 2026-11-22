#!/usr/bin/env python3
"""Exercise the whole patched production absentd with host CF/XPC stand-ins."""
from pathlib import Path
import os
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
TC = Path('/home/baimao/nabu_macos/out/nabu-27.3-fresh/p025-m2v/toolchain/llvm21/usr')
compiler = TC / 'lib/llvm-21/bin/clang'
environment = dict(os.environ, LD_LIBRARY_PATH=str(TC / 'lib/x86_64-linux-gnu'))
with tempfile.TemporaryDirectory(prefix='b5q-absent-test-') as tmp:
    work = Path(tmp)
    (work / 'absentd.c').write_bytes((ROOT / 'UniXNU/scripts/absent-service/absentd.c').read_bytes())
    subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-d', str(work)], check=True,
                   input=(ROOT / 'UniXNU-b5q/patches/tools/b5q-absentd-user-domains.patch').read_bytes())
    for folder in ['CoreFoundation', 'dispatch', 'xpc']:
        (work / folder).mkdir()
    (work / 'CoreFoundation/CoreFoundation.h').write_text('''
#include <stdbool.h>
#include <stddef.h>
typedef const void *CFTypeRef;
typedef const void *CFURLRef;
typedef const void *CFReadStreamRef;
typedef const void *CFPropertyListRef;
typedef unsigned char UInt8;
typedef long CFIndex;
#define CFSTR(x) ((const void *)(x))
#define kCFStringEncodingUTF8 1
#define kCFPropertyListImmutable 0
unsigned CFGetTypeID(CFTypeRef);
unsigned CFStringGetTypeID(void);
unsigned CFDictionaryGetTypeID(void);
bool CFStringGetCString(CFTypeRef,char *,long,unsigned);
CFURLRef CFURLCreateFromFileSystemRepresentation(void *,const UInt8 *,CFIndex,bool);
CFReadStreamRef CFReadStreamCreateWithFile(void *,CFURLRef);
bool CFReadStreamOpen(CFReadStreamRef);
CFPropertyListRef CFPropertyListCreateWithStream(void *,CFReadStreamRef,long,unsigned,void *,void *);
void CFReadStreamClose(CFReadStreamRef);
void CFRelease(const void *);
CFTypeRef CFDictionaryGetValue(CFTypeRef,CFTypeRef);
void CFDictionaryApplyFunction(CFTypeRef,void (*)(const void *,const void *,void *),void *);
''')
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
''')
    harness = r'''
#include <assert.h>
#include <setjmp.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdarg.h>
#include <sys/types.h>
#include <fcntl.h>
#include <unistd.h>
static char output[8192], path[512];
static int scenario, attempts, listeners, activated, cancelled;
static jmp_buf resident;
void *_NSConcreteStackBlock[32];
void *_NSConcreteGlobalBlock[32];
int mock_open(const char *p,int flags,...) {(void)flags;assert(!strcmp(p,"/dev/console"));return 7;}
ssize_t mock_write(int fd,const void *data,size_t len) {assert(fd==7);strncat(output,data,len);return (ssize_t)len;}
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
unsigned CFGetTypeID(CFTypeRef obj){return obj==(void *)10 || obj==(void *)11 ? 2 : 1;}
unsigned CFStringGetTypeID(void){return 1;}
unsigned CFDictionaryGetTypeID(void){return 2;}
bool CFStringGetCString(CFTypeRef obj,char *out,long n,unsigned enc){(void)enc;snprintf(out,(size_t)n,"%s",(const char *)obj);return true;}
CFURLRef CFURLCreateFromFileSystemRepresentation(void *a,const UInt8 *s,CFIndex n,bool dir){(void)a;(void)n;(void)dir;snprintf(path,sizeof path,"%s",s);++attempts;return (void *)1;}
CFReadStreamRef CFReadStreamCreateWithFile(void *a,CFURLRef u){(void)a;(void)u;return (void *)2;}
bool CFReadStreamOpen(CFReadStreamRef s){(void)s;return scenario!=2 && (scenario!=1 || strstr(path,"LaunchAgents"));}
CFPropertyListRef CFPropertyListCreateWithStream(void *a,CFReadStreamRef s,long b,unsigned c,void *d,void *e){(void)a;(void)s;(void)b;(void)c;(void)d;(void)e;return (void *)10;}
void CFReadStreamClose(CFReadStreamRef s){(void)s;}
void CFRelease(const void *s){(void)s;}
CFTypeRef CFDictionaryGetValue(CFTypeRef a,CFTypeRef k){(void)a;assert(!strcmp(k,"MachServices"));return (void *)11;}
void CFDictionaryApplyFunction(CFTypeRef a,void(*fn)(const void *,const void *,void *),void *ctx){(void)a;fn("com.apple.test",(void *)1,ctx);}
void *dispatch_get_main_queue(void){return (void *)1;}
void dispatch_main(void){longjmp(resident,1);}
xpc_connection_t xpc_connection_create_mach_service(const char *n,void *q,unsigned f){(void)n;(void)q;(void)f;++listeners;return scenario==3?NULL:(void *)4;}
void xpc_connection_set_event_handler(xpc_connection_t c,void(^block)(xpc_object_t)){
 if(c==(void *)4){block(XPC_ERROR_CONNECTION_INVALID);block((void *)5);}
}
void xpc_connection_activate(xpc_connection_t c){(void)c;++activated;}
void xpc_connection_cancel(xpc_connection_t c){(void)c;++cancelled;}
void *xpc_get_type(xpc_object_t o){return o==XPC_ERROR_CONNECTION_INVALID?XPC_TYPE_ERROR:XPC_TYPE_CONNECTION;}
static void reset(int mode){scenario=mode;output[0]=0;attempts=listeners=activated=cancelled=0;}
int main(void){
 reset(0);unsetenv("XPC_SERVICE_NAME");assert(production_main()==0);assert(strstr(output,"boot-task-exit")&&!attempts);
 reset(0);setenv("XPC_SERVICE_NAME","",1);assert(production_main()==0);assert(strstr(output,"boot-task-exit")&&!attempts);
 reset(0);setenv("XPC_SERVICE_NAME","../invalid",1);assert(production_main()==78);assert(strstr(output,"invalid-label-exit"));
 char long_label[300];memset(long_label,'x',sizeof long_label);long_label[299]=0;
 reset(0);setenv("XPC_SERVICE_NAME",long_label,1);assert(production_main()==78);assert(!attempts);
 for(int mode=0;mode<4;++mode){
  reset(mode);setenv("XPC_SERVICE_NAME","com.apple.security.cryptexd",1);
  if(!setjmp(resident)){production_main();assert(!"service unexpectedly exited");}
  assert(strstr(output,"label=com.apple.security.cryptexd")&&strstr(output,"resident"));
  if(mode==0)assert(attempts==1&&strstr(output,"daemon-plist")&&cancelled==1);
  if(mode==1)assert(attempts==2&&strstr(output,"agent-plist")&&cancelled==1);
  if(mode==2)assert(attempts==2&&!listeners&&strstr(output,"plist-unavailable"));
  if(mode==3)assert(listeners==1&&strstr(output,"listener-create-failed")&&activated==0);
 }
 puts("PASS: 8 whole-production absentd cases: boot-task/empty/invalid/oversize/daemon/agent/missing-plist/listener-error+cancel");
}
'''
    (work / 'test.c').write_text(harness)
    command = [str(compiler), '-std=gnu11', '-fblocks', '-fsanitize=address,undefined',
               '-fno-sanitize-link-runtime', '-lasan', '-lubsan',
               '-Wall', '-Wextra', '-Werror', '-I', str(work), str(work / 'test.c'), '-o', str(work / 'test')]
    subprocess.run(command, check=True, env=environment)
    subprocess.run([str(work / 'test')], check=True, env=environment)
