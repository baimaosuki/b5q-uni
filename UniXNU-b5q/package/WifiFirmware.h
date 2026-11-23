/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#ifndef B5Q_WIFI_FIRMWARE_H
#define B5Q_WIFI_FIRMWARE_H
#include <stdint.h>
#include <stddef.h>
#define SHENG_WIFI_FIRMWARE_PREFIX "firmware/ath11k/WCN6855/hw2.0"
#define SHENG_WIFI_FIRMWARE_ROOT "/private/var/ngpu/" SHENG_WIFI_FIRMWARE_PREFIX
#ifdef __cplusplus
extern "C" {
#endif
int sheng_wifi_firmware_read(const char *,uint8_t **,size_t *);
#ifdef __cplusplus
}
#endif
#endif
