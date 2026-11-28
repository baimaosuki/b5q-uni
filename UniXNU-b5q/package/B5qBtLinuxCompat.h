/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#ifndef B5Q_BT_LINUX_COMPAT_H
#define B5Q_BT_LINUX_COMPAT_H
/* Consume native declarations before defining the Linux compatibility name.
 * Otherwise the forced include renames XNU's later attributed strrchr
 * declaration onto the already-defined inline function (Xcode rejects it).
 */
#ifdef KERNEL
#include <sys/systm.h>
#endif
#include <string.h>
/* strrchr is a userspace libc API, not exported by every XNU kernel. Keep
 * original btqca.c byte-identical and namespace this narrow compatibility. */
static inline char *b5q_bt_strrchr(const char *p,int c) {
    const char *found=0;
    do {if((unsigned char)*p==(unsigned char)c)found=p;}while(*p++);
    return (char*)found;
}
#define strrchr b5q_bt_strrchr
#endif
