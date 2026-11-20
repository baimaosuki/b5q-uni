// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>
// Only the generic PON wake and report suppression helpers are needed here.
static inline int sheng_sleep_power_wakes(uint8_t rt,uint32_t latched){return ((rt|latched)&0x80)!=0;}
static inline int sheng_sleep_swallow(int *pending,int pressed){if(!*pending)return pressed;if(!pressed)*pending=0;return 0;}
