// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "B5qProcTop.h"

// IOLog's formatter has a 255-byte limit. Emit a summary and individually
// ranked rows: even a 63-byte name and maximum counters fit below 200 bytes.
// snprintf and the emitter are supplied by the kernel/host caller.
static inline void b5q_proc_print(struct b5q_proc_window w,
                                  const struct b5q_proc_row *rows,
                                  void (*emit)(const char *,void *),void *context) {
    char line[200];
    snprintf(line, sizeof line, "B5qProcTop: window=30s spawns=%llu exits=%llu\n",
             (unsigned long long)w.spawns, (unsigned long long)w.exits);
    emit(line,context);
    for (unsigned i=0; i<w.rows && i<B5Q_PROC_TOP; ++i) {
        snprintf(line, sizeof line, "B5qProcTop: %s TOP%u %s:%u(exit=%u/sig=%u)\n",
                 i<5?"TOP1..5":"TOP6..10", i+1, rows[i].name, rows[i].count,
                 (rows[i].status>>8)&255u, rows[i].status&127u);
        emit(line,context);
    }
    snprintf(line, sizeof line, "B5qProcTop: TOP6..10 end rows=%u overflow=%llu\n",
             w.rows<B5Q_PROC_TOP?w.rows:(unsigned)B5Q_PROC_TOP, (unsigned long long)w.overflow);
    emit(line,context);
}

static inline void b5q_cpu_print(const struct b5q_cpu_window *w,void (*emit)(const char *,void *),void *context){
 char line[224];
 for(unsigned i=0;i<B5Q_CPU_TOP;i++)if(w->top[i].delta_ms){
  const struct b5q_cpu_rank *p=&w->top[i];
  snprintf(line,sizeof line,"B5qProcTop: cpu TOP%u pid=%d name=%s delta_cpu_ms=%llu permille=%llu window_ms=%llu\n",i+1,p->pid,p->name,(unsigned long long)p->delta_ms,(unsigned long long)p->permille,(unsigned long long)w->elapsed_ms);emit(line,context);
 }
 const struct b5q_cpu_rank *p=&w->kernel;
 snprintf(line,sizeof line,"B5qProcTop: cpu kernel_task pid=0 delta_cpu_ms=%llu permille=%llu sampled=%u overflow=%u\n",(unsigned long long)p->delta_ms,(unsigned long long)p->permille,w->used,w->overflow);emit(line,context);
}
