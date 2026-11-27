// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>
// A ready queue may remain ready after a refused/deferred operation. Give it
// another bounded slice, then actually block for1ms; yielding alone can spin.
static inline unsigned b5q_wifi_worker_wait(int ready, unsigned next, uint64_t slice_ns) {
    if (!ready) return next ? (next > 1000 ? 1000 : next) : 1;
    return slice_ns >= 2000000ULL ? 1 : 0;
}
static inline uint64_t b5q_bt_worker_deadline(uint64_t deadline, uint64_t now) {
    return deadline == 0 || deadline <= now ? now + 1000000ULL : deadline;
}
