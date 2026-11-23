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
