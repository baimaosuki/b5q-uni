/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#pragma once
#include <stdint.h>
// Callback runs on a kernel worker, never in primary IRQ context. Its
// context remains owned by the caller until stop returns true.
using B5qDpFrameCallback=void (*)(void *,uint32_t,uint64_t);
extern "C" bool b5q_dp_irq_start(void *,B5qDpFrameCallback);
extern "C" bool b5q_dp_irq_stop(void);
