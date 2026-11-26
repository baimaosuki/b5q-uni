/* SPDX-License-Identifier: GPL-2.0-only */
/* Pure host-side helpers for the MHI BHIe RDDM (ramdump) path.
 *
 * Nothing here touches PCIe, MHI doorbells, locks or the scheduler. The board
 * supplies a register-read callback and a bounded delay callback for the
 * RXVECSTATUS wait; the segment scanner only reads the already-DMA'd host
 * buffers. Keeping this header free of IOKit lets the host ASan/UBSan tests
 * include the exact production logic.
 */
#ifndef B5Q_ATH11K_RDDM_H
#define B5Q_ATH11K_RDDM_H
#include <stdint.h>
#include <stddef.h>
#include <string.h>

#define B5Q_RDDM_RXVECSTATUS_OFFS 0x78u
#define B5Q_RDDM_STATUS_RESET 0u
#define B5Q_RDDM_STATUS_XFER_COMPL 2u
#define B5Q_RDDM_STATUS_ERROR 3u
#define B5Q_RDDM_WAIT_MAX_MS 3000u
#define B5Q_RDDM_WAIT_STEP_MS 10u
#define B5Q_RDDM_TEXT_MAX 160u
#define B5Q_RDDM_HIGH_MAX 12u
#define B5Q_RDDM_LOW_MAX 12u
#define B5Q_RDDM_HIT_MAX 24u

struct B5qRddmSegment { const uint8_t *data; uint32_t len; };

typedef uint32_t (*B5qRddmReadFn)(void *ctx, uint32_t offset);
typedef void (*B5qRddmDelayFn)(void *ctx, unsigned ms);

struct B5qRddmWait {
    uint32_t rxvec;
    uint32_t state;
    uint32_t waited_ms;
    uint32_t polls;
};

/* Read RXVECSTATUS[31:30] once, then poll at most max_ms in step_ms units.
 * Returns state 2 (XFER_COMPL), 3 (ERROR/unavailable) or 0/1 on timeout.
 * The caller owns the read/delay callbacks; this helper cannot wake MHI. */
static inline struct B5qRddmWait b5q_rddm_wait_rxvec(B5qRddmReadFn read, B5qRddmDelayFn delay,
                                                      void *ctx, uint32_t max_ms, uint32_t step_ms) {
    struct B5qRddmWait result = {0, B5Q_RDDM_STATUS_RESET, 0, 0};
    if (!read) return result;
    result.rxvec = read(ctx, B5Q_RDDM_RXVECSTATUS_OFFS);
    result.state = (result.rxvec >> 30) & 3u;
    if (result.state == B5Q_RDDM_STATUS_XFER_COMPL || result.state == B5Q_RDDM_STATUS_ERROR ||
        result.rxvec == UINT32_MAX || !delay || !step_ms)
        return result;
    while (result.waited_ms < max_ms) {
        delay(ctx, step_ms);
        result.waited_ms += step_ms;
        result.polls++;
        result.rxvec = read(ctx, B5Q_RDDM_RXVECSTATUS_OFFS);
        result.state = (result.rxvec >> 30) & 3u;
        if (result.state == B5Q_RDDM_STATUS_XFER_COMPL || result.state == B5Q_RDDM_STATUS_ERROR ||
            result.rxvec == UINT32_MAX)
            break;
    }
    return result;
}

static inline int b5q_rddm_printable(uint8_t value) {
    return value >= 0x20u && value <= 0x7eu;
}

static inline uint32_t b5q_rddm_clean_ascii(char *out, uint32_t capacity,
                                             const uint8_t *src, uint32_t len) {
    uint32_t n = 0;
    if (!out || !capacity) return 0;
    for (uint32_t i = 0; i < len && n + 1u < capacity; i++)
        out[n++] = b5q_rddm_printable(src[i]) ? (char)src[i] : '.';
    out[n] = 0;
    return n;
}

static inline size_t b5q_rddm_segment_nonzero(const uint8_t *data, size_t len,
                                               size_t *nonzero) {
    size_t count = 0;
    if (nonzero) *nonzero = 0;
    if (!data) return 0;
    for (size_t i = 0; i < len; i++)
        if (data[i]) { count++; if (nonzero) (*nonzero)++; }
    return count;
}

static inline int b5q_rddm_is_elf(const uint8_t *data, uint32_t len) {
    return data && len >= 4u && data[0] == 0x7fu && data[1] == 'E' &&
           data[2] == 'L' && data[3] == 'F';
}

/* ASCII case-insensitive bounded search. */
static inline int b5q_rddm_memcaselen(const uint8_t *hay, uint32_t hay_len,
                                      const char *needle, uint32_t n) {
    if (!n || hay_len < n) return 0;
    for (uint32_t i = 0; i + n <= hay_len; i++) {
        uint32_t k = 0;
        while (k < n) {
            uint8_t a = hay[i + k], b = (uint8_t)needle[k];
            if (a >= 'A' && a <= 'Z') a = (uint8_t)(a - 'A' + 'a');
            if (b >= 'A' && b <= 'Z') b = (uint8_t)(b - 'A' + 'a');
            if (a != b) break;
            k++;
        }
        if (k == n) return 1;
    }
    return 0;
}

struct B5qRddmHit {
    uint32_t seg;
    uint32_t off;
    uint32_t length;
    uint32_t priority; /* 0 high assert/fatal, 1 low context */
    char text[B5Q_RDDM_TEXT_MAX + 1u];
};

typedef void (*B5qRddmEmitFn)(void *ctx, const struct B5qRddmHit *hit);

struct B5qRddmScan {
    B5qRddmEmitFn emit;
    void *ctx;
    uint64_t seen[32];
    uint32_t seen_count;
    uint32_t high;
    uint32_t low;
    uint32_t dropped;
};

static inline void b5q_rddm_scan_init(struct B5qRddmScan *scan, B5qRddmEmitFn emit, void *ctx) {
    if (!scan) return;
    memset(scan, 0, sizeof(*scan));
    scan->emit = emit;
    scan->ctx = ctx;
}

static inline uint64_t b5q_rddm_fingerprint(const char *text) {
    uint64_t hash = 0xcbf29ce484222325ULL;
    for (const unsigned char *p = (const unsigned char *)text; *p; p++)
        hash = (hash ^ *p) * 0x100000001b3ULL;
    return hash;
}

static inline int b5q_rddm_seen(struct B5qRddmScan *scan, const char *text) {
    const uint64_t hash = b5q_rddm_fingerprint(text);
    for (uint32_t i = 0; i < scan->seen_count; i++)
        if (scan->seen[i] == hash) return 1;
    if (scan->seen_count < sizeof(scan->seen) / sizeof(scan->seen[0]))
        scan->seen[scan->seen_count++] = hash;
    return 0;
}

/* Extract a printable run around a hit. A short non-printable gap inside the
 * text is kept and cleaned to '.', trailing control bytes are trimmed, and the
 * result never exceeds 160 characters. */
static inline uint32_t b5q_rddm_extract(const uint8_t *data, uint32_t len,
                                         uint32_t hit, uint32_t keyword,
                                         char *out, uint32_t capacity) {
    uint32_t start = hit;
    while (start > 0u && b5q_rddm_printable(data[start - 1u]) && hit - start < 48u) start--;
    uint32_t end = hit + keyword;
    uint32_t gap = 0;
    while (end < len && end - start < B5Q_RDDM_TEXT_MAX) {
        if (b5q_rddm_printable(data[end])) { gap = 0; end++; }
        else if (data[end] != 0 && gap < 4u) { gap++; end++; }
        else break;
    }
    while (end > start && !b5q_rddm_printable(data[end - 1u])) end--;
    return b5q_rddm_clean_ascii(out, capacity, data + start, end - start);
}

struct B5qRddmWord {
    const char *text;
    uint32_t len;
};

static inline int b5q_rddm_low_context(const uint8_t *data, uint32_t len,
                                        uint32_t hit, uint32_t keyword) {
    uint32_t begin = hit > 64u ? hit - 64u : 0u;
    uint32_t end = hit + keyword + 64u;
    if (end > len) end = len;
    static const struct B5qRddmWord words[] = {
        {"assert", 6u}, {"err", 3u}, {"fail", 4u}, {"fatal", 5u},
        {"panic", 5u}, {"crash", 5u}, {"excep", 5u}, {"line", 4u}
    };
    for (uint32_t i = 0; i < sizeof(words) / sizeof(words[0]); i++)
        if (b5q_rddm_memcaselen(data + begin, end - begin, words[i].text, words[i].len)) return 1;
    return 0;
}

static inline int b5q_rddm_match_high(const uint8_t *data, uint32_t len, uint32_t at,
                                       uint32_t *keyword) {
    static const struct B5qRddmWord words[] = {
        {"asserted in", 11u}, {"assert", 6u}, {"err_fatal", 9u}, {"fatal", 5u},
        {"excep", 5u}, {"crash", 5u}, {"panic", 5u}
    };
    for (uint32_t i = 0; i < sizeof(words) / sizeof(words[0]); i++) {
        const uint32_t n = words[i].len;
        if (n && at + n <= len && b5q_rddm_memcaselen(data + at, n, words[i].text, n)) {
            *keyword = n;
            return 1;
        }
    }
    return 0;
}

static inline int b5q_rddm_match_low(const uint8_t *data, uint32_t len, uint32_t at,
                                      uint32_t *keyword) {
    static const struct B5qRddmWord words[] = {
        {"wal_", 4u}, {"wmi_", 4u}, {".c:", 3u}, {"line ", 5u}
    };
    for (uint32_t i = 0; i < sizeof(words) / sizeof(words[0]); i++) {
        const uint32_t n = words[i].len;
        if (n && at + n <= len && b5q_rddm_memcaselen(data + at, n, words[i].text, n)) {
            *keyword = n;
            return 1;
        }
    }
    return 0;
}

static inline void b5q_rddm_emit(struct B5qRddmScan *scan, uint32_t seg,
                                  uint32_t off, uint32_t length, uint32_t priority,
                                  const char *text) {
    if (!scan->emit) return;
    if (priority == 0u) {
        if (scan->high >= B5Q_RDDM_HIGH_MAX || scan->high + scan->low >= B5Q_RDDM_HIT_MAX) {
            scan->dropped++;
            return;
        }
    } else {
        if (scan->low >= B5Q_RDDM_LOW_MAX || scan->high + scan->low >= B5Q_RDDM_HIT_MAX) {
            scan->dropped++;
            return;
        }
    }
    if (b5q_rddm_seen(scan, text)) return;
    if (priority == 0u) scan->high++;
    else scan->low++;
    struct B5qRddmHit hit;
    memset(&hit, 0, sizeof(hit));
    hit.seg = seg;
    hit.off = off;
    hit.length = length;
    hit.priority = priority;
    strncpy(hit.text, text, B5Q_RDDM_TEXT_MAX);
    hit.text[B5Q_RDDM_TEXT_MAX] = 0;
    scan->emit(scan->ctx, &hit);
}

/* Two passes: assert/fatal first, then low-priority stack context. Both are
 * bounded and deduplicated; no pass allocates or writes into the segments. */
static inline void b5q_rddm_scan(struct B5qRddmScan *scan,
                                  const struct B5qRddmSegment *segments, uint32_t count) {
    if (!scan || !segments || !count) return;
    scan->high = scan->low = scan->dropped = 0;
    scan->seen_count = 0;
    for (uint32_t pass = 0; pass < 2u; pass++) {
        for (uint32_t seg = 0; seg < count; seg++) {
            const uint8_t *data = segments[seg].data;
            const uint32_t len = segments[seg].len;
            if (!data || !len) continue;
            for (uint32_t at = 0; at < len; at++) {
                if (!b5q_rddm_printable(data[at])) continue;
                uint32_t keyword = 0;
                if (pass == 0u ? !b5q_rddm_match_high(data, len, at, &keyword)
                               : !b5q_rddm_match_low(data, len, at, &keyword))
                    continue;
                if (pass != 0u && !b5q_rddm_low_context(data, len, at, keyword)) continue;
                char text[B5Q_RDDM_TEXT_MAX + 1u];
                const uint32_t length = b5q_rddm_extract(data, len, at, keyword, text, sizeof(text));
                if (!length) continue;
                b5q_rddm_emit(scan, seg, at, length, pass, text);
                at += keyword - 1u;
            }
        }
    }
}

#endif
