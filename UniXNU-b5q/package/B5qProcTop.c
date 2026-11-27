// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <sys/types.h>
#include <sys/proc.h>
#include <IOKit/IOLib.h>
#include <kern/thread.h>
#include <mach/task_info.h>
#include <mach/mach_time.h>
#include <kern/startup.h>
struct flock;
struct componentname;
struct knote;
struct vnode_attr;
#include <security/mac_policy.h>
#include <libkern/libkern.h>
#include "B5qProcTopFormat.h"

// Exact pinned XNU proc_private.h contracts: exitstatus is specifically safe
// in mpo_proc_notify_exit, after the process has left the PID lookup table.
extern int proc_exitstatus(proc_t);
static struct b5q_proc_top counts;
static struct b5q_proc_row rows[B5Q_PROC_BUCKETS];
static struct mac_policy_ops operations;
static struct mac_policy_conf policy;
static mac_policy_handle_t handle;

static void created(kauth_cred_t cred, proc_t proc) {
    (void)cred; (void)proc;
    b5q_proc_spawn(&counts);
}
static void exited(proc_t proc) {
    b5q_proc_exit(&counts, proc_best_name(proc), (unsigned)proc_exitstatus(proc));
}
static void emitLine(const char *line,void *context) {(void)context;IOLog("%s",line);}
/* Exact exported XNU contracts, proc_iterate retains each proc and waits
 * for exec transitions before its callback (kern_proc.c). task_info takes
 * its own task lock; no logging occurs while an iterator callback runs.
 * bsd_init.c inserts kernproc into allproc and binds kernel_task; PID 0
 * is included by this iterator, not synthesized from user process totals. */
extern void proc_iterate(unsigned,int (*)(proc_t,void *),void *,int (*)(proc_t,void *),void *);
extern task_t proc_task(proc_t);
extern uint64_t proc_uniqueid(proc_t);
extern kern_return_t task_info(task_t,task_flavor_t,task_info_t,mach_msg_type_number_t *);
static struct b5q_cpu_window cpu;
static int cpuSample(proc_t proc,void *unused){
 (void)unused;task_t task=proc_task(proc);if(!task)return 0;
 task_absolutetime_info_data_t info={0};mach_msg_type_number_t count=TASK_ABSOLUTETIME_INFO_COUNT;
 if(task_info(task,TASK_ABSOLUTETIME_INFO,(task_info_t)&info,&count)!=KERN_SUCCESS)return 0;
 uint64_t ns=0;absolutetime_to_nanoseconds(info.total_user+info.total_system,&ns);
 b5q_cpu_sample(&cpu,proc_pid(proc),proc_uniqueid(proc),proc_best_name(proc),ns);return 0;
}
static void reporter(void *arg, wait_result_t result) {
    (void)arg; (void)result;
    uint64_t previous=mach_absolute_time();
    b5q_cpu_begin(&cpu,0);proc_iterate(1u,cpuSample,NULL,NULL,NULL);
    for (;;) {
        IOSleep(30000);
        const uint64_t now=mach_absolute_time();uint64_t elapsed=0;absolutetime_to_nanoseconds(now-previous,&elapsed);previous=now;
        b5q_cpu_begin(&cpu,elapsed/1000000);proc_iterate(1u,cpuSample,NULL,NULL,NULL);
        b5q_cpu_print(&cpu,emitLine,NULL);
        struct b5q_proc_window w = b5q_proc_snapshot(&counts, rows);
        b5q_proc_print(w,rows,emitLine,NULL);
    }
}
static void b5q_proc_top_init(void) {
    operations.mpo_cred_label_associate_fork = created;
    operations.mpo_proc_notify_exit = exited;
    policy.mpc_name = "b5q-proc-top";
    policy.mpc_fullname = "b5q process lifecycle counters";
    policy.mpc_ops = &operations;
    int status = mac_policy_register(&policy, &handle, NULL);
    IOLog("B5qProcTop: observer status=%d spawns=fork-and-spawn exit-status=wait interval=30s\n", status);
    if (status) return;
    thread_t thread = THREAD_NULL;
    kern_return_t kr = kernel_thread_start(reporter, NULL, &thread);
    IOLog("B5qProcTop: reporter status=%d\n", kr);
    if (kr == KERN_SUCCESS) thread_deallocate(thread);
}
// mac_policy_init ran before MACH_IPC; BSD process creation is still ahead.
// The read-only MAC observer adds no access-control decisions or labels.
STARTUP(EARLY_BOOT, STARTUP_RANK_LAST, b5q_proc_top_init);
