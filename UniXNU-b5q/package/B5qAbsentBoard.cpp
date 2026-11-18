// SPDX-License-Identifier: BSD-2-Clause-Patent
// Explicit unavailable-provider ABI for the RAM-only build, not hardware drivers.
// Every UFS operation refuses; no MMIO, DMA, firmware loading or GPT access.
#include <IOKit/IOReturn.h>
#include <IOKit/IOLib.h>
#include <mach/vm_types.h>
#include <mach/boolean.h>
#include <mach/machine.h>
#include <sys/types.h>
#include <sys/param.h>
#include <string.h>
#include <stdint.h>
extern "C" {
__attribute__((weak)) void (*arm64_platform_sleep_hook)(boolean_t)=nullptr;
__attribute__((weak)) volatile int native_owner_root_accepted=0;
__attribute__((weak)) volatile dev_t native_owner_root_mount_device=NODEV;
unsigned native_ufs_store_mode(void) { return 0; }
int native_ufs_store_open(uint64_t,uint64_t *bytes,const char **why) {
    if(bytes)*bytes=0;
    if(why)*why="b5q RAM-only build: no persistent provider";
    return -1;
}
int native_ufs_store_read(uint64_t,uint32_t,void *) { return -1; }
int native_ufs_store_write(uint64_t,uint32_t,const void *) { return -1; }
int native_ufs_store_write_cached(uint64_t,uint32_t,const void *) { return -1; }
int native_ufs_store_sync(void) { return -1; }
unsigned native_ufs_store_gpt_check(void) { return 0; }
volatile uint32_t native_ufs_dpu_state=0;
__attribute__((weak)) volatile uint32_t native_gpu_dcvs[15]={};
// Without the optional pmap observation, conservatively retain pages.
__attribute__((weak)) unsigned int native_pmap_user_mappings(ppnum_t,void **object,uint64_t *address,char *name) {
    if(object)*object=nullptr;
    if(address)*address=0;
    if(name)*name=0;
    return 1;
}
uint32_t native_ufs_dpu_map(unsigned,const uint64_t *,unsigned) { return 0; }
// No diagnostic writer owns the scanout: there is nothing to wait for or cancel.
int boot_progress_prepare_scanout(void) { return 1; }
void boot_progress_cancel_scanout(void) {}
int boot_progress_pulse_anchor(uintptr_t,uint64_t,unsigned,unsigned,unsigned) { return 0; }
void boot_progress_stage(const char *) {}
int boot_kthread_report_nth(const char *,unsigned,char *name,unsigned cap,char *out,unsigned size) {
    if(name && cap)*name=0;
    if(out && size)*out=0;
    return -1;
}
void native_exit_trace(int,const char *,int) {}
// The optional UFS diagnostic export must never report an accepted write.
int boot_log_export_put(uint32_t,uint32_t,uint32_t,const void *,uint32_t) { return -1; }
}
