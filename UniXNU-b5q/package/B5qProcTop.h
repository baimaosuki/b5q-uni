// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>
#include <stddef.h>

// Event callbacks only update fixed storage. A single reporting thread owns
// snapshot/output; it neither allocates memory nor holds a lock while logging.
enum { B5Q_PROC_BUCKETS = 1024, B5Q_PROC_NAME = 64, B5Q_PROC_TOP = 10 };
struct b5q_proc_bucket {
    uint32_t ready; // 0 empty, 1 initializing, 2 immutable name published
    char name[B5Q_PROC_NAME];
    uint64_t events; // low 32 bits exit count; bits 32..47 last wait status
};
struct b5q_proc_row { char name[B5Q_PROC_NAME]; uint32_t count; uint16_t status; };
struct b5q_proc_top {
    struct b5q_proc_bucket buckets[B5Q_PROC_BUCKETS];
    uint64_t spawns, exits, overflow;
};
struct b5q_proc_window { uint64_t spawns, exits, overflow; unsigned rows; };

static inline void b5q_proc_name(char *out, const char *in) {
    unsigned i = 0;
    if (in) for (; i + 1 < B5Q_PROC_NAME && in[i]; ++i) {
        unsigned char c = (unsigned char)in[i];
        out[i] = c >= 33 && c < 127 && c != ',' && c != ':' ? (char)c : '_';
    }
    out[i] = 0;
}
static inline int b5q_proc_equal(const char *a, const char *b) {
    for (unsigned i = 0; i < B5Q_PROC_NAME; ++i) {
        if (a[i] != b[i]) return 0;
        if (!a[i]) return 1;
    }
    return 1;
}
static inline void b5q_proc_spawn(struct b5q_proc_top *top) {
    __atomic_fetch_add(&top->spawns, 1, __ATOMIC_RELAXED);
}
static inline void b5q_proc_exit(struct b5q_proc_top *top, const char *name, unsigned status) {
    char key[B5Q_PROC_NAME];
    b5q_proc_name(key, name && *name ? name : "unknown");
    uint32_t hash = 2166136261u;
    for (unsigned i = 0; key[i]; ++i) hash = (hash ^ (unsigned char)key[i]) * 16777619u;
    __atomic_fetch_add(&top->exits, 1, __ATOMIC_RELAXED);
    for (unsigned i = 0; i < B5Q_PROC_BUCKETS; ++i) {
        struct b5q_proc_bucket *b = &top->buckets[(hash + i) % B5Q_PROC_BUCKETS];
        uint32_t ready = __atomic_load_n(&b->ready, __ATOMIC_ACQUIRE);
        if (!ready) {
            uint32_t expected = 0;
            if (__atomic_compare_exchange_n(&b->ready, &expected, 1, 0,
                                             __ATOMIC_ACQ_REL, __ATOMIC_RELAXED)) {
                b5q_proc_name(b->name, key);
                __atomic_store_n(&b->ready, 2, __ATOMIC_RELEASE);
                ready = 2;
            }
        }
        if (ready != 2 || !b5q_proc_equal(b->name, key)) continue;
        uint64_t old = __atomic_load_n(&b->events, __ATOMIC_RELAXED), next;
        do {
            next = ((uint64_t)(status & 0xffffu) << 32) | ((old + 1) & 0xffffffffu);
        } while (!__atomic_compare_exchange_n(&b->events, &old, next, 0,
                                               __ATOMIC_RELAXED, __ATOMIC_RELAXED));
        return;
    }
    __atomic_fetch_add(&top->overflow, 1, __ATOMIC_RELAXED);
}
static inline struct b5q_proc_window b5q_proc_snapshot(struct b5q_proc_top *top,
                                                       struct b5q_proc_row *rows) {
    struct b5q_proc_window w = {
        __atomic_exchange_n(&top->spawns, 0, __ATOMIC_RELAXED),
        __atomic_exchange_n(&top->exits, 0, __ATOMIC_RELAXED),
        __atomic_exchange_n(&top->overflow, 0, __ATOMIC_RELAXED), 0
    };
    for (unsigned i = 0; i < B5Q_PROC_BUCKETS; ++i) {
        struct b5q_proc_bucket *b = &top->buckets[i];
        if (__atomic_load_n(&b->ready, __ATOMIC_ACQUIRE) != 2) continue;
        uint64_t e = __atomic_exchange_n(&b->events, 0, __ATOMIC_RELAXED);
        if (!(uint32_t)e) continue;
        unsigned j = 0;
        for (; j < w.rows; ++j) if (b5q_proc_equal(rows[j].name, b->name)) break;
        if (j == w.rows) { b5q_proc_name(rows[j].name, b->name); rows[j].count = 0; ++w.rows; }
        rows[j].count += (uint32_t)e;
        rows[j].status = (uint16_t)(e >> 32);
    }
    // Only the first ten need sorting. Duplicate slots created by concurrent
    // first observations are merged above; immutable names are never recycled.
    for (unsigned i = 0; i < w.rows && i < B5Q_PROC_TOP; ++i) {
        unsigned best = i;
        for (unsigned j = i + 1; j < w.rows; ++j)
            if (rows[j].count > rows[best].count) best = j;
        if (best != i) { struct b5q_proc_row t = rows[i]; rows[i] = rows[best]; rows[best] = t; }
    }
    return w;
}
