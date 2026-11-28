/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#include <sys/param.h>
#include <sys/systm.h>
#include <sys/proc.h>
#include <sys/vnode.h>
#include <sys/uio.h>
#include <sys/fcntl.h>
#include <sys/kauth.h>
#include <IOKit/IOLib.h>
#include "WifiFirmware.h"
// Private pinned XNU vnode.h declaration, omitted by the public SDK.
extern vfs_context_t vfs_context_kernel(void) __pure2;
extern volatile int native_gpu_addon_stage;
#include "B5qWifiFirmwareName.h"
int sheng_wifi_firmware_read(const char *name,uint8_t **data,size_t *size) {
    if(!data || !size)return EINVAL;
    *data=NULL;*size=0;
    if(!b5q_wifi_firmware_name(name))return ENOENT;
    if(native_gpu_addon_stage<1)return EAGAIN;
    char path[160];snprintf(path,sizeof(path),"%s/%s",SHENG_WIFI_FIRMWARE_ROOT,!strcmp(name,"amss.bin")?"amss20.bin":name);
    vfs_context_t ctx=vfs_context_kernel();vnode_t vp=NULL;
    int error=vnode_open(path,FREAD,0,0,&vp,ctx);uint8_t *buffer=NULL;size_t length=0;
    if(!error) {
        struct vnode_attr va;VATTR_INIT(&va);VATTR_WANTED(&va,va_data_size);
        error=vnode_getattr(vp,&va,ctx);
        if(!error && (vnode_vtype(vp)!=VREG || !va.va_data_size || va.va_data_size>32u*1024*1024))error=EINVAL;
        if(!error) {
            length=(size_t)va.va_data_size;buffer=IOMallocData(length);
            if(!buffer)error=ENOMEM;
            else {
                int resid=0;
                error=vn_rdwr(UIO_READ,vp,(caddr_t)buffer,(int)length,0,UIO_SYSSPACE,IO_NOAUTH,
                    vfs_context_ucred(ctx),&resid,vfs_context_proc(ctx));
                if(!error && resid)error=EIO;
            }
        }
    }
    if(vp)vnode_close(vp,FREAD,ctx);
    if(error){if(buffer)IOFreeData(buffer,length);return error;}
    *data=buffer;*size=length;return 0;
}
// Called only after station firmware and the real native interface exist.
int b5q_wifi_publish_ready(void) {
    vfs_context_t ctx=vfs_context_kernel();vnode_t vp=NULL;
    int error=vnode_open("/private/var/run/b5q-wifi-ready",FWRITE|O_CREAT|O_EXCL|O_NOFOLLOW,0600,0,&vp,ctx);
    if(error)return error;
    static const char content[]="station-interface-ready\n";int resid=0;
    error=vn_rdwr(UIO_WRITE,vp,(caddr_t)content,sizeof(content)-1,0,UIO_SYSSPACE,IO_NOAUTH|IO_SYNC,
        vfs_context_ucred(ctx),&resid,vfs_context_proc(ctx));
    int closed=vnode_close(vp,FWRITE,ctx);return error?error:resid?EIO:closed;
}
