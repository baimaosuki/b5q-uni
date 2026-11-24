/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#pragma once
#include <stdint.h>
/* Numeric interface settings from Samsung F7310ZCS7EYF3 ACDB tagged RX
 * stereo configuration. Sources/hashes/offsets: reports/p4-audio-tdm-source.json.
 * Wire layout: Qualcomm pcm_tdm_api.h param_id_tdm_intf_cfg_t, 28 bytes. */
static const uint8_t b5q_tdm_stereo_config[28] = {0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x01,0x00,0x00,0x00,0x03,0x00,0x00,0x00,0x04,0x00,0x20,0x00,0x00,0x00,0x00,0x00,0x01,0x00,0x00,0x00};
#define B5Q_AUDIO_RATE 48000u
#define B5Q_AUDIO_CHANNELS 2u
#define B5Q_AUDIO_ENDPOINT_BITS 24u
#define B5Q_AUDIO_TDM_BITCLOCK 6144000u
