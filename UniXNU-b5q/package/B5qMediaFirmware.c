/* SPDX-License-Identifier: BSD-2-Clause-Patent */
/* The shared firmware reader's VFS-only path, with exact b5q file identities.
 * No partition lookup, modem fallback, mutable page tables or hardware I/O. */
#include <sys/param.h>
#include <sys/systm.h>
#include <sys/proc.h>
#include <sys/vnode.h>
#include <sys/uio.h>
#include <sys/fcntl.h>
#include <sys/kauth.h>
#include <IOKit/IOLib.h>
#include <libkern/crypto/sha2.h>
/* Pinned XNU bsd/sys/vnode.h:2696, not exported by the SDK header. */
extern vfs_context_t vfs_context_kernel(void);

struct b5q_media_file {vnode_t vnode;uint64_t bytes;};
struct b5q_media_identity {const char *path;uint64_t bytes;uint8_t hash[32];};
#include "B5qMediaFirmwareIdentity.h"

int sheng_fw_read(void *handle,uint64_t offset,void *to,size_t length) {
    struct b5q_media_file *fw=handle;
    if(!fw||(!to&&length)||offset>fw->bytes||length>fw->bytes-offset)return EINVAL;
    vfs_context_t ctx=vfs_context_kernel();uint8_t *out=to;
    while(length) {
        int want=length>(1u<<20)?(1<<20):(int)length,resid=want;
        int error=vn_rdwr(UIO_READ,fw->vnode,(caddr_t)out,want,(off_t)offset,
            UIO_SYSSPACE,IO_NOAUTH,vfs_context_ucred(ctx),&resid,vfs_context_proc(ctx));
        if(error)return error;
        if(resid<0||resid>=want)return EIO;
        out+=want-resid;offset+=(uint64_t)(want-resid);length-=(size_t)(want-resid);
    }
    return 0;
}
void sheng_fw_close(void *handle) {
    struct b5q_media_file *fw=handle;if(!fw)return;
    if(fw->vnode)vnode_close(fw->vnode,FREAD,vfs_context_kernel());
    IOFree(fw,sizeof(*fw));
}
int sheng_fw_open(const char *path,void **handle,uint64_t *size) {
    if(!path||!handle||!size)return EINVAL;
    *handle=NULL;*size=0;
    const struct b5q_media_identity *identity=NULL;
    for(unsigned i=0;i<sizeof(b5q_media_identities)/sizeof(b5q_media_identities[0]);++i)
        if(!strcmp(path,b5q_media_identities[i].path)){identity=b5q_media_identities+i;break;}
    if(!identity)return EPERM;
    struct b5q_media_file *fw=IOMalloc(sizeof(*fw));
    if(!fw)return ENOMEM;
    bzero(fw,sizeof(*fw));vfs_context_t ctx=vfs_context_kernel();
    int error=vnode_open(path,FREAD|O_NOFOLLOW,0,0,&fw->vnode,ctx);
    if(error){IOFree(fw,sizeof(*fw));return error;}
    struct vnode_attr attr;VATTR_INIT(&attr);VATTR_WANTED(&attr,va_data_size);
    error=vnode_getattr(fw->vnode,&attr,ctx);
    if(!error&&(!VATTR_IS_SUPPORTED(&attr,va_data_size)||attr.va_data_size!=identity->bytes||
        vnode_vtype(fw->vnode)!=VREG))error=EFTYPE;
    if(error){sheng_fw_close(fw);return error;}
    fw->bytes=attr.va_data_size;
    uint8_t *buffer=IOMallocData(65536),digest[32];SHA256_CTX sha;
    if(!buffer){sheng_fw_close(fw);return ENOMEM;}
    SHA256_Init(&sha);
    for(uint64_t at=0;at<fw->bytes&&!error;) {
        size_t count=fw->bytes-at>65536?65536:(size_t)(fw->bytes-at);
        error=sheng_fw_read(fw,at,buffer,count);
        if(!error)SHA256_Update(&sha,buffer,count);
        at+=count;
    }
    SHA256_Final(digest,&sha);IOFreeData(buffer,65536);
    if(!error&&memcmp(digest,identity->hash,sizeof(digest)))error=EAUTH;
    if(error){sheng_fw_close(fw);return error;}
    *handle=fw;*size=fw->bytes;return 0;
}
