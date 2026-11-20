// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>
// b5q PMK8550 RTC; no SDAM offset cells.
enum { BC_RTC_PPID=0x61,BC_RTC_CONTROL=0x46,BC_RTC_COUNTER=0x48 };
#ifdef __cplusplus
extern "C" {
void sheng_board_clock_probe(void);
unsigned sheng_board_clock_row(char *,unsigned);
}
#endif
