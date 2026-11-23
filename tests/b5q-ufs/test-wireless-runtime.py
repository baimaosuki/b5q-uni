#!/usr/bin/env python3
"""Exercise the real macOS pre-launchd wireless views, not the unused iPadOS path."""
import argparse,subprocess,sys,tempfile
from pathlib import Path
R=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser();p.add_argument('--source',type=Path);a=p.parse_args()
def function(text,name):
    at=text.index(name+'(');start=text.rfind('static void\n',0,at)
    pos=text.index('{',at);end=pos+1;depth=1
    while depth:depth+=(text[end]=='{')-(text[end]=='}');end+=1
    return text[start:end]
with tempfile.TemporaryDirectory(prefix='b5q-wireless-boot-')as td:
    td=Path(td)
    if a.source:source=a.source.read_text()
    else:
        sys.path.insert(0,str(R/'UniXNU/scripts'))
        from unixnu.cli import parser
        from unixnu.config import Context
        from unixnu import feeds,patches
        ctx=Context(parser().parse_args(['tree','--device',str(R/'UniXNU-b5q'),'--os','macos-27.3-26C5035r']))
        base=R/'sources/UniXNU/out/feeds/xnu-3199e8bc';work=td/'xnu'
        subprocess.run(['git','clone','-q','--shared','--no-checkout',str(base),str(work)],check=True)
        subprocess.run(['git','-C',str(work),'checkout','-q','--detach',ctx.board['os']['xnu_revision']],check=True)
        for patch in patches.plan(ctx,feeds.resolve(ctx)):subprocess.run(['git','-C',str(work),'apply',str(patch)],check=True,stdout=subprocess.DEVNULL)
        source=(work/'bsd/kern/kern_exec.c').read_text()
    # The selected OSX path must publish after addon installation/views and
    # before loader memory is freed. Its error guard must match the other steps.
    start=source.index('native_owner_macos_data_prepare(proc_t p, user_addr_t scratch)')
    body=source[start:source.index('\ndone:',start)]
    expected=['native_owner_macos_gpu_addon(p, scratch)','native_owner_macos_addon_sbin(p, scratch)',
              'b5q_wireless_runtime_prepare(p, scratch)','native_gpu_addon_release()']
    positions=[body.index('if (!error) '+n+';')for n in expected]
    assert positions==sorted(positions)
    ipad=function(source,'native_gpu_addon_prepare')
    assert 'b5q_wireless_runtime'not in ipad and 'B5qWireless:'not in ipad
    functions='\n'.join(function(source,n)for n in ['native_gpu_addon_mount','b5q_wireless_runtime_prepare'])
    harness=r'''
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <assert.h>
#include <errno.h>
typedef int proc_t;typedef uintptr_t user_addr_t;typedef int vnode_t;
#define NULLVP 0
#define MNT_RDONLY 1
#define MNT_UNION 32
struct mount_args{user_addr_t type,path;int flags;user_addr_t data;};
static unsigned bt,wifi,lookupCount,putCount,mounts,copies,logs,failAt,failCopy;
static int mountError,native_bindfs_boot_mount,native_owner_addon_sbin_status;
static char sourcePath[128],pointPath[128];
static int PE_parse_boot_argn(const char *n,void *p,size_t bytes){assert(bytes==4);*(unsigned*)p=!strcmp(n,"wifi")?wifi:bt;return 1;}
static int vfs_context_current(void){return 0;}
static int vnode_lookup(const char *p,int flags,vnode_t *v,int ctx){assert(!flags&&!ctx);assert(p[0]=='/');lookupCount++;if(lookupCount==failAt)return ENOENT;*v=1;return 0;}
static void vnode_put(vnode_t v){assert(v==1);putCount++;}
static int copyout(const void *p,user_addr_t v,size_t n){copies++;if(copies==failCopy)return EFAULT;memcpy((void*)v,p,n);return 0;}
static int mount(proc_t p,struct mount_args *args,int32_t *r){assert(p==7&&native_bindfs_boot_mount);assert(!strcmp((char*)args->type,"bindfs"));assert(args->flags==(MNT_RDONLY|MNT_UNION));strcpy(sourcePath,(char*)args->data);strcpy(pointPath,(char*)args->path);*r=0;mounts++;return mountError;}
static int report(const char *format,...){assert(strstr(format,"B5qWireless:"));logs++;return 0;}
#define printf report
FUNCTIONS
#undef printf
static void reset(void){lookupCount=putCount=mounts=copies=logs=failAt=failCopy=0;mountError=0;sourcePath[0]=pointPath[0]=0;}
int main(void){uint8_t scratch[4096];
 for(bt=0;bt<3;bt++)for(wifi=0;wifi<2;wifi++){
  reset();b5q_wireless_runtime_prepare(7,(uintptr_t)scratch);
  assert(logs==(bt==1)+wifi&&mounts==wifi&&putCount==lookupCount);
  assert(!native_bindfs_boot_mount);
  if(wifi){assert(!strcmp(sourcePath,"/private/var/ngpu/Library/LaunchDaemons"));assert(!strcmp(pointPath,"/Library/LaunchDaemons"));}
 }
 bt=1;wifi=1;
 for(unsigned fail=1;fail<=5;fail++){
  reset();failAt=fail;b5q_wireless_runtime_prepare(7,(uintptr_t)scratch);
  assert(logs==2&&putCount==lookupCount-1&&!native_bindfs_boot_mount);
 }
 for(unsigned fail=1;fail<=3;fail++){
  reset();failCopy=fail;b5q_wireless_runtime_prepare(7,(uintptr_t)scratch);
  assert(mounts==0&&logs==2&&putCount==lookupCount&&!native_bindfs_boot_mount);
 }
 reset();mountError=EIO;b5q_wireless_runtime_prepare(7,(uintptr_t)scratch);
 assert(mounts==1&&logs==2&&putCount==lookupCount&&!native_bindfs_boot_mount);
 puts("PASS selected macOS prelaunch path/order and real union helper:6feature modes,5lookup faults,3copyout faults,mount failure; no duplicate BT mounts");
}
'''.replace('FUNCTIONS',functions)
    src=td/'test.c';src.write_text(harness)
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-O1','-g','-fsanitize=address,undefined',str(src),'-o',str(td/'test')],check=True)
    subprocess.run([str(td/'test')],check=True)
