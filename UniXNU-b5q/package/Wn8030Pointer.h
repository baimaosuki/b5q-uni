/* SPDX-License-Identifier: BSD-2-Clause-Patent */
/* Protocol-only extraction from UniXNU-sheng 6c42e1055ffb3b335fda991190ad221edaa7af3c
 * package/Wn8030.c/.h. No keyboard hardware, GPIO or firmware is included.
 * Function bodies below are unchanged; only linkage becomes static inline. */
#pragma once
#include <stdint.h>
#define WN8030_TOUCHPAD_REPORT 21u
#define WN8030_TOUCHPAD_FINGERS 3u
#define WN8030_POINTER_ID 0x1au
#define WN8030_POINTER_REPORT 8u
/* The bucket of a gap between two touchpad reports (wn8030_gap_bucket): under 10, 20, 30, 45, 60, 100, 250 ms, then the rest. */
#define WN8030_GAP_BUCKETS 8u
struct wn8030_pointer {
    uint8_t fingers, buttons;
    uint8_t click;                            /* the button the click held now began as (0: none held) */
    uint8_t ids[WN8030_TOUCHPAD_FINGERS];     /* the touching fingers' contact ids, ascending */
    int32_t x, y;            /* where the finger (or the fingers' centre) was */
    int32_t move_x, move_y;  /* motion not yet sent, in controller counts */
    int32_t scroll_x, scroll_y;
    uint32_t at_ms;          /* when the report before arrived (wn8030_pointer_report_at) */
    /* The timing record (wn8030_pointer_report_at): touchpad reports, pointer reports sent, touches the pause rule restarted, and
     * the gaps before reports that follow one with a finger down, by wn8030_gap_bucket. */
    uint32_t reports, sent, restarts;
    uint32_t gaps[WN8030_GAP_BUCKETS];
};
static inline unsigned wn8030_gap_bucket(uint32_t ms);
static inline unsigned wn8030_pointer_report(struct wn8030_pointer *state, const uint8_t touchpad[WN8030_TOUCHPAD_REPORT],
                               uint8_t out[WN8030_POINTER_REPORT]);
/* The same with the report's arrival time in milliseconds (any origin; the count may wrap). A report more than
 * WN8030_POINTER_GAP_MS after the one before starts from where the fingers are, like a new touch, and drops what was pending: the
 * controller can keep a finger's contact id across a lift and the next touch, and when the report of the lift is lost the touch
 * would read as one leap from where the finger lifted to where it landed. While a finger moves, reports come about every 13 ms. */
#define WN8030_POINTER_GAP_MS 60u
static inline unsigned wn8030_pointer_report_at(struct wn8030_pointer *state, const uint8_t touchpad[WN8030_TOUCHPAD_REPORT], uint32_t now_ms,
                                  uint8_t out[WN8030_POINTER_REPORT]);


static inline void put_le16(uint8_t *p, uint32_t v) {p[0] = (uint8_t)v; p[1] = (uint8_t)(v >> 8);}
/* Pointer motion keeps the controller counts. Scroll uses 48 counts (about 1.5 mm) per step. */
#define WN8030_SCROLL_COUNTS 48
static inline int32_t pointer_take(int32_t *pending, int32_t unit, int32_t limit)
{
    int32_t steps = *pending / unit;
    if (steps > limit) steps = limit;
    if (steps < -limit) steps = -limit;
    *pending -= steps * unit;
    return steps;
}
static inline unsigned wn8030_gap_bucket(uint32_t ms)
{
    static const uint32_t below[WN8030_GAP_BUCKETS - 1] = {10, 20, 30, 45, 60, 100, 250};
    unsigned bucket = 0;
    while (bucket < WN8030_GAP_BUCKETS - 1 && ms >= below[bucket]) ++bucket;
    return bucket;
}

static inline unsigned wn8030_pointer_report(struct wn8030_pointer *state, const uint8_t touchpad[WN8030_TOUCHPAD_REPORT],
                               uint8_t out[WN8030_POINTER_REPORT])
{
    return wn8030_pointer_report_at(state, touchpad, state->at_ms, out);
}

static inline unsigned wn8030_pointer_report_at(struct wn8030_pointer *state, const uint8_t touchpad[WN8030_TOUCHPAD_REPORT], uint32_t now_ms,
                                  uint8_t out[WN8030_POINTER_REPORT])
{
    /* A report this long after the one before is a new touch, whatever contact ids it carries (unsigned: the count may wrap). */
    const int paused = now_ms - state->at_ms > WN8030_POINTER_GAP_MS;
    ++state->reports;
    if (state->fingers) ++state->gaps[wn8030_gap_bucket(now_ms - state->at_ms)];
    state->at_ms = now_ms;
    uint32_t fingers = 0;
    uint8_t ids[WN8030_TOUCHPAD_FINGERS] = {0, 0, 0};
    int32_t x = 0, y = 0;
    for (uint32_t f = 0; f < WN8030_TOUCHPAD_FINGERS; ++f) {
        const uint8_t *p = touchpad + 2 + 6 * f;
        if (!(p[0] & 1u)) continue;
        /* The ids in ascending order, whatever slots the controller keeps them in. */
        uint32_t at = fingers;
        for (; at && ids[at - 1] > p[1]; --at) ids[at] = ids[at - 1];
        ids[at] = p[1];
        x += (int32_t)((uint32_t)p[2] | (uint32_t)p[3] << 8);
        y += (int32_t)((uint32_t)p[4] | (uint32_t)p[5] << 8);
        ++fingers;
    }
    if (fingers) {x /= (int32_t)fingers; y /= (int32_t)fingers;}
    int same = fingers == state->fingers;
    for (uint32_t f = 0; same && f < fingers; ++f) same = ids[f] == state->ids[f];
    /* Fingers that came, went or changed places, or come back after a pause, start from where they are: no jump. */
    if (fingers && same && paused) ++state->restarts;
    if (fingers && same && !paused) {
        /* In the report as it arrives here Y grows away from the user (seen on the tablet: with Y taken as growing downwards the
         * pointer went down when the finger went up), so the pointer's Y is its negative and moving up scrolls up. */
        const int32_t dx = x - state->x, dy = state->y - y;
        if (fingers == 1) {state->move_x += dx; state->move_y += dy;}
        else {state->scroll_x += dx; state->scroll_y -= dy;}
    }
    if (fingers != state->fingers || paused) state->move_x = state->move_y = state->scroll_x = state->scroll_y = 0;
    state->fingers = (uint8_t)fingers; state->x = x; state->y = y;
    for (uint32_t f = 0; f < WN8030_TOUCHPAD_FINGERS; ++f) state->ids[f] = ids[f];
    /* The click is the button it began as for as long as it is held: fingers that lift or land during the press do not turn a
     * right click into a left one or a drag into a right click. */
    uint8_t buttons = 0;
    if (touchpad[1] & 1u) {
        if (!state->click) state->click = fingers >= 2 ? 2u : 1u;
        buttons |= state->click;
    } else state->click = 0;
    if (touchpad[1] & 2u) buttons |= 2u;
    const int32_t mx = pointer_take(&state->move_x, 1, 32767), my = pointer_take(&state->move_y, 1, 32767);
    const int32_t sy = pointer_take(&state->scroll_y, WN8030_SCROLL_COUNTS, 127), sx = pointer_take(&state->scroll_x, WN8030_SCROLL_COUNTS, 127);
    if (!mx && !my && !sx && !sy && buttons == state->buttons) return 0;
    state->buttons = buttons;
    ++state->sent;
    out[0] = WN8030_POINTER_ID; out[1] = buttons;
    put_le16(out + 2, (uint16_t)(int16_t)mx); put_le16(out + 4, (uint16_t)(int16_t)my);
    out[6] = (uint8_t)(int8_t)sy; out[7] = (uint8_t)(int8_t)sx;
    return WN8030_POINTER_REPORT;
}
