// SPDX-License-Identifier: BSD-2-Clause-Patent
#include <sys/types.h>
#include <sys/proc.h>
#include <IOKit/IOLib.h>
#include <kern/thread.h>
#include <kern/startup.h>
struct flock;
struct componentname;
struct knote;
struct vnode_attr;
#include <security/mac_policy.h>
#include <libkern/libkern.h>
#include "B5qProcTop.h"

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
static void reporter(void *arg, wait_result_t result) {
    (void)arg; (void)result;
    for (;;) {
        IOSleep(30000);
        struct b5q_proc_window w = b5q_proc_snapshot(&counts, rows);
        char line[1536];
        int used = snprintf(line, sizeof(line),
            "B5qProcTop: window=30s spawns=%llu exits=%llu top=",
            (unsigned long long)w.spawns, (unsigned long long)w.exits);
        for (unsigned i = 0; i < w.rows && i < B5Q_PROC_TOP && used > 0 && (unsigned)used < sizeof(line); ++i) {
            unsigned status = rows[i].status;
            used += snprintf(line + used, sizeof(line) - (unsigned)used,
                "%s%s:%u(exit=%u/sig=%u)", i ? "," : "", rows[i].name,
                rows[i].count, (status >> 8) & 255u, status & 127u);
        }
        IOLog("%s overflow=%llu\n", line, (unsigned long long)w.overflow);
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
