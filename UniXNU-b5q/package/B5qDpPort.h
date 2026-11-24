/* SPDX-License-Identifier: GPL-2.0-or-later */
#pragma once
#include <stdint.h>
struct B5qDpPortState {
 uint32_t phase,error,generation;uint8_t pin,lanes;int8_t reverse;bool attached,hpd,hpdIrq,configured;
};
extern "C" bool b5q_dp_port_poll(B5qDpPortState *);
extern "C" void b5q_dp_port_stop(void);
