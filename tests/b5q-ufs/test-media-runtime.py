#!/usr/bin/env python3
"""Run the actual macOS media HAL mount helper with VFS/mount failures."""
from pathlib import Path
import argparse,subprocess,sys,tempfile
R=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path);args=parser.parse_args()
if args.source:s=args.source.read_text()
else:
 with tempfile.TemporaryDirectory(prefix='b5q-media-source-')as td:
  sys.path.insert(0,str(R/'UniXNU/scripts'))
  from unixnu.cli import parser as cli_parser
  from unixnu.config import Context
  from unixnu import feeds,patches
  ctx=Context(cli_parser().parse_args(['tree','--device',str(R/'UniXNU-b5q'),'--os','macos-27.3-26C5035r']))
  work=Path(td)/'xnu';base=R/'sources/UniXNU/out/feeds/xnu-3199e8bc'
  subprocess.run(['git','clone','-q','--shared','--no-checkout',str(base),str(work)],check=True)
  subprocess.run(['git','-C',str(work),'checkout','-q','--detach',ctx.board['os']['xnu_revision']],check=True)
  for patch in patches.plan(ctx,feeds.resolve(ctx)):subprocess.run(['git','-C',str(work),'apply',str(patch)],check=True,stdout=subprocess.DEVNULL)
  s=(work/'bsd/kern/kern_exec.c').read_text()
def fn(name):
 at=s.index(name+'(');begin=s.rfind('static void\n',0,at);brace=s.index('{',at);end=brace+1;depth=1
 while depth:depth+=(s[end]=='{')-(s[end]=='}');end+=1
 return s[begin:end]
start=s.index('native_owner_macos_data_prepare(proc_t p, user_addr_t scratch)');end=s.index('\ndone:',start);body=s[start:end]
names=['native_owner_macos_gpu_addon(p, scratch)','native_owner_macos_addon_sbin(p, scratch)','b5q_wireless_runtime_prepare(p, scratch)','b5q_media_runtime_prepare(p, scratch)','native_owner_macos_boot_shims(p, scratch)','native_gpu_addon_release()'];positions=[body.index('if (!error) '+n+';')for n in names];assert positions==sorted(positions)
source=fn('native_gpu_addon_mount')+'\n'+fn('b5q_media_runtime_prepare')
h=r'''
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
static unsigned enabled,lookups,putsCount,mounts,copies,logs,failAt,failCopy,parents;
static int mountError,parentError,native_bindfs_boot_mount;
static int b5q_audio_runtime_enabled(void){return enabled;}
static int native_gpu_addon_parents(proc_t p,user_addr_t scratch,const char *path){assert(p==7&&scratch&&!strcmp(path,"/Library/Audio/Plug-Ins/HAL/.b5q"));parents++;return parentError;}
static int vfs_context_current(void){return 0;}
static int vnode_lookup(const char *p,int flags,vnode_t *v,int ctx){assert(!flags&&!ctx&&p[0]=='/');lookups++;if(lookups==failAt)return ENOENT;*v=1;return 0;}
static void vnode_put(vnode_t v){assert(v==1);putsCount++;}
static int copyout(const void *p,user_addr_t v,size_t n){copies++;if(copies==failCopy)return EFAULT;memcpy((void*)v,p,n);return 0;}
static int mount(proc_t p,struct mount_args *a,int32_t *r){assert(p==7&&native_bindfs_boot_mount&&!strcmp((char*)a->type,"bindfs")&&a->flags==(MNT_RDONLY|MNT_UNION));assert(!strcmp((char*)a->data,"/private/var/ngpu/Library/Audio/Plug-Ins/HAL")&&!strcmp((char*)a->path,"/Library/Audio/Plug-Ins/HAL"));*r=0;mounts++;return mountError;}
static int report(const char *format,...){assert(strstr(format,"B5qMedia:"));logs++;return 0;}
#define printf report
FUNCTIONS
#undef printf
static void reset(void){enabled=1;lookups=putsCount=mounts=copies=logs=failAt=failCopy=parents=0;mountError=parentError=0;}
int main(void){uint8_t scratch[4096];reset();enabled=0;b5q_media_runtime_prepare(7,(uintptr_t)scratch);assert(!parents&&!lookups&&!mounts&&!logs);
 reset();b5q_media_runtime_prepare(7,(uintptr_t)scratch);assert(parents==1&&mounts==1&&logs==1&&lookups==3&&putsCount==3&&!native_bindfs_boot_mount);
 reset();parentError=EROFS;b5q_media_runtime_prepare(7,(uintptr_t)scratch);assert(parents==1&&!mounts&&!lookups&&logs==1);
 for(unsigned n=1;n<=3;n++){reset();failAt=n;b5q_media_runtime_prepare(7,(uintptr_t)scratch);assert(logs==1&&putsCount==lookups-1&&!native_bindfs_boot_mount);}
 for(unsigned n=1;n<=3;n++){reset();failCopy=n;b5q_media_runtime_prepare(7,(uintptr_t)scratch);assert(logs==1&&!mounts&&putsCount==lookups&&!native_bindfs_boot_mount);}
 reset();mountError=EIO;b5q_media_runtime_prepare(7,(uintptr_t)scratch);assert(mounts==1&&logs==1&&putsCount==lookups&&!native_bindfs_boot_mount);
 puts("PASS selected macOS media runtime:actual stageorder,disabled,parent/VFS/copyout/mount faults; read-only HAL view and no lingering bindfs privilege; ASanUBSan");
}
'''.replace('FUNCTIONS',source)
# GCC intentionally sees a weak hook as available in this harness. The final
# Mach-O closure separately verifies it binds to actual AudioProbe.o.
h=h.replace('if (!b5q_audio_runtime_enabled || !b5q_audio_runtime_enabled())','if (!b5q_audio_runtime_enabled())')
with tempfile.TemporaryDirectory(prefix='b5q-media-runtime-')as td:
 t=Path(td);(t/'test.c').write_text(h);subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-O1','-g','-fsanitize=address,undefined',str(t/'test.c'),'-o',str(t/'test')],check=True);subprocess.run([str(t/'test')],check=True)
