/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#ifndef B5Q_WCN_POWER_H
#define B5Q_WCN_POWER_H
#ifdef __cplusplus
extern "C" {
#endif
enum { B5Q_WCN_WLAN=0, B5Q_WCN_BLUETOOTH=1 };
/* One idempotent ownership vote per radio, positive errno on failure. */
int b5q_wcn_power_get(unsigned);
int b5q_wcn_power_put(unsigned);
unsigned b5q_wcn_power_owners(void);
int b5q_wcn_pcie_vote(void);
/* Serializes XO204 and the radio's own enable pin; never resets its peer. */
int b5q_wcn_radio_enable(unsigned, int);
#ifdef __cplusplus
}
#endif
#endif
