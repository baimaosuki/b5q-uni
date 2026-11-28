#!/usr/bin/env python3
"""Run the production VFS firmware reader with original stock firmware files."""
from pathlib import Path
import subprocess,tempfile
R=Path(__file__).resolve().parents[2]
s=(R/'UniXNU-b5q/package/B5qMediaFirmware.c').read_text()
s=s[s.index('struct b5q_media_file'):]
harness=r'''
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdlib.h>
#include <stdio.h>
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/types.h>
#include <openssl/sha.h>
#ifndef EAUTH
#define EAUTH 80
#endif
#ifndef EFTYPE
#define EFTYPE 79
#endif
#define FREAD 1
#define UIO_READ 1
#define UIO_SYSSPACE 1
#define IO_NOAUTH 1
#define VREG 1
typedef void *vfs_context_t;
typedef struct FakeVnode {uint8_t *data;size_t size;} *vnode_t;
static struct FakeVnode input;
static int openError,attrError,readError,residMode,wrongSize,wrongType,unsupported;
static unsigned opens,closes,allocs,active,failAlloc;
static size_t fragment;
static vfs_context_t vfs_context_kernel(void){return &input;}
static void *vfs_context_ucred(vfs_context_t c){return c;}
static void *vfs_context_proc(vfs_context_t c){return c;}
struct vnode_attr {uint64_t va_data_size;};
#define VATTR_INIT(p) memset(p,0,sizeof(*(p)))
#define VATTR_WANTED(p,f) ((void)(p))
#define VATTR_IS_SUPPORTED(p,f) (!unsupported)
static void *IOMallocData(size_t n){if(++allocs==failAlloc)return NULL;void *p=calloc(1,n);assert(p);active++;return p;}
static void IOFreeData(void *p,size_t n){assert(p&&n&&active);active--;free(p);}
#define IOMalloc IOMallocData
#define IOFree IOFreeData
static int vnode_open(const char *path,int flags,int mode,int opts,vnode_t *out,vfs_context_t c){
 assert(!mode&&!opts&&c==&input&&(flags&O_NOFOLLOW)&&strstr(path,"/private/var/ngpu/firmware/"));
 opens++;if(openError)return openError;*out=&input;return 0;
}
static void vnode_close(vnode_t v,int flags,vfs_context_t c){assert(v==&input&&flags==FREAD&&c==&input);closes++;}
static int vnode_getattr(vnode_t v,struct vnode_attr *a,vfs_context_t c){assert(v==&input&&c==&input);a->va_data_size=v->size+wrongSize;return attrError;}
static int vnode_vtype(vnode_t v){assert(v==&input);return wrongType?2:VREG;}
static int vn_rdwr(int operation,vnode_t v,char *to,int want,off_t off,int space,int flags,void *cred,int *resid,void *proc){
 assert(operation==UIO_READ&&v==&input&&space==UIO_SYSSPACE&&flags==IO_NOAUTH&&cred==&input&&proc==&input&&off>=0);
 assert((uint64_t)off<=v->size&&(size_t)want<=v->size-(size_t)off);
 if(readError)return readError;
 if(residMode){*resid=residMode==1?want:-1;return 0;}
 size_t take=(size_t)want;if(fragment&&take>fragment)take=fragment;
 memcpy(to,v->data+off,take);*resid=want-(int)take;return 0;
}
SOURCE
static void reset(void){assert(active==0);openError=attrError=readError=residMode=wrongSize=wrongType=unsupported=0;opens=closes=allocs=failAlloc=0;fragment=0;}
static void load(const char *path){FILE *f=fopen(path,"rb");assert(f);assert(!fseek(f,0,SEEK_END));long size=ftell(f);assert(size>0&&!fseek(f,0,SEEK_SET));free(input.data);input.size=(size_t)size;input.data=malloc(input.size);assert(input.data&&fread(input.data,1,input.size,f)==input.size);fclose(f);}
int main(int argc,char **argv){assert(argc==5);
 for(unsigned i=0;i<4;++i){
  load(argv[i+1]);reset();void *handle=NULL;uint64_t size=0;
  fragment=137;assert(!sheng_fw_open(b5q_media_identities[i].path,&handle,&size));
  assert(handle&&size==input.size&&opens==1&&closes==0&&active==1);
  uint8_t bytes[64];assert(!sheng_fw_read(handle,17,bytes,sizeof(bytes))&&!memcmp(bytes,input.data+17,sizeof(bytes)));
  assert(!sheng_fw_read(handle,size,NULL,0));assert(sheng_fw_read(handle,size,NULL,1)==EINVAL);
  assert(sheng_fw_read(handle,size-1,bytes,2)==EINVAL&&sheng_fw_read(handle,UINT64_MAX,bytes,1)==EINVAL);
  assert(sheng_fw_read(handle,0,NULL,1)==EINVAL);sheng_fw_close(handle);assert(active==0&&closes==1);
  reset();input.data[0]^=1;handle=(void*)1;size=99;
  assert(sheng_fw_open(b5q_media_identities[i].path,&handle,&size)==EAUTH&&!handle&&!size&&active==0&&closes==1);input.data[0]^=1;
 }
 for(unsigned failure=0;failure<11;++failure){
  reset();void *handle=(void*)1;uint64_t size=99;int expected=EIO;
  switch(failure){case 0:openError=ENOENT;expected=ENOENT;break;case 1:attrError=EIO;break;
   case 2:wrongSize=1;expected=EFTYPE;break;case 3:wrongType=1;expected=EFTYPE;break;
   case 4:unsupported=1;expected=EFTYPE;break;case 5:readError=EIO;break;
   case 6:residMode=1;break;case 7:residMode=2;break;
   case 8:failAlloc=1;expected=ENOMEM;break;case 9:failAlloc=2;expected=ENOMEM;break;
   case 10:openError=ELOOP;expected=ELOOP;break;
  }
  assert(sheng_fw_open(b5q_media_identities[3].path,&handle,&size)==expected);
  assert(!handle&&!size&&!active);
  assert(closes==(failure==0||failure==8||failure==10?0u:1u));
 }
 reset();void *h=(void*)1;uint64_t n=99;assert(sheng_fw_open("modem:/adsp.mbn",&h,&n)==EPERM&&!h&&!n&&!opens);
 assert(sheng_fw_open(NULL,&h,&n)==EINVAL&&sheng_fw_open("x",NULL,&n)==EINVAL&&sheng_fw_open("x",&h,NULL)==EINVAL);
 assert(sheng_fw_read(NULL,0,NULL,0)==EINVAL);sheng_fw_close(NULL);free(input.data);
 puts("PASS production VFS media firmware:4realSamsungSHA256files,137Bshortreads,corruption,11faults,EOF/overflow/symlink/whitelist/allocation cleanup ASanUBSan");
}
'''.replace('SOURCE',s)
files=[R/'artifacts/b5q-p4-work/stock-adsp'/n for n in ['adsp.mbn','adsp_dtb.mbn']]+[
    R/'artifacts/firmware-b5q/F7310ZCS7EYF3/vendor/firmware'/n for n in ['vpu30_4v.mbn','tfa98xx.cnt']]
assert all(p.is_file()for p in files)
with tempfile.TemporaryDirectory(prefix='b5q-media-firmware-')as td:
    td=Path(td);(td/'test.c').write_text(harness)
    subprocess.run(['/usr/lib/llvm-17/bin/clang','-std=gnu11','-O1','-g','-Wall','-Wextra','-Werror',
        '-Wno-deprecated-declarations','-Wno-misleading-indentation','-fsanitize=address,undefined',
        '-I'+str(R/'UniXNU-b5q/package'),str(td/'test.c'),'-lcrypto','-o',str(td/'test')],check=True)
    subprocess.run([str(td/'test'),*map(str,files)],check=True)
