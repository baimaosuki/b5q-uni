/* SPDX-License-Identifier: GPL-2.0-only */
/* Samsung msm_geni_serial FIFO transport; shared QcaBluetooth owns H4/IBS. */
#ifndef B5Q_BT_FIFO_H
#define B5Q_BT_FIFO_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
enum b5q_bt_fifo_state { B5Q_BT_FIFO_OFF, B5Q_BT_FIFO_RUN,
    B5Q_BT_FIFO_CANCEL, B5Q_BT_FIFO_ABORT, B5Q_BT_FIFO_STOPPED,
    B5Q_BT_FIFO_FAILED };
struct b5q_bt_fifo_ops {
    void *context;
    uint32_t (*read)(void *, uint32_t);
    void (*write)(void *, uint32_t, uint32_t);
    void (*barrier)(void *);
    uint64_t (*now_ns)(void *);
    void (*irq_mask)(void *, bool);
    void (*wake_worker)(void *);
    size_t (*receive)(void *, const uint8_t *, size_t);
};
struct b5q_bt_fifo_stats {
    uint64_t interrupts, tx_bytes, rx_bytes, tx_words, rx_words;
    uint64_t rx_backpressure, line_errors, cancel_timeouts;
};
struct b5q_bt_fifo {
    struct b5q_bt_fifo_ops ops;
    struct b5q_bt_fifo_stats stats;
    enum b5q_bt_fifo_state state;
    uint8_t tx[4096], rx[8192];
    unsigned tx_length, tx_offset, rx_head, rx_count, tx_depth, rx_depth;
    uint32_t baud, source_hz, fault_irq[2];
    uint64_t stop_deadline, retry_at;
    int error;
    bool tx_busy, flow, irq_pending;
};
int b5q_bt_fifo_prepare(struct b5q_bt_fifo *, const struct b5q_bt_fifo_ops *);
int b5q_bt_fifo_set_rate(struct b5q_bt_fifo *, uint32_t, uint32_t, unsigned);
int b5q_bt_fifo_start(struct b5q_bt_fifo *);
void b5q_bt_fifo_irq(struct b5q_bt_fifo *);
bool b5q_bt_fifo_service(struct b5q_bt_fifo *);
size_t b5q_bt_fifo_write(struct b5q_bt_fifo *, const uint8_t *, size_t);
bool b5q_bt_fifo_drained(struct b5q_bt_fifo *);
void b5q_bt_fifo_set_flow(struct b5q_bt_fifo *, bool);
int b5q_bt_fifo_quiesce(struct b5q_bt_fifo *);
int b5q_bt_fifo_resume(struct b5q_bt_fifo *);
uint64_t b5q_bt_fifo_deadline(const struct b5q_bt_fifo *);
#ifdef __cplusplus
}
#endif
#endif
