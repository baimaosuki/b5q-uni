// SPDX-License-Identifier: BSD-2-Clause-Patent
// Generic PMIC arbiter v7 transfer helpers; b5q DT provenance in runtime-v21.json.
#ifndef BOOT_RESET_CORE_H
#define BOOT_RESET_CORE_H
#ifndef BOOT_RESET_CORE_TYPES
#include <stdint.h>
#endif

enum {
  BR_VERSION_V7_MIN = 0x70000000u, BR_VERSION_V8_MIN = 0x80000000u,
  BR_FEATURES = 0x04, BR_FEATURES_APIDS_MASK = 0x7ffu,
  BR_APID_MAP = 0x2000,                     // core + 0x2000 + 4*apid: bits 19:8 PPID, bit 24 IRQ owner
  BR_CNFG_OWNER = 0x00,                     // cnfg + 4*apid: bits 2:0 the EE allowed to write the APID
  BR_OBS_EE_STRIDE = 0x8000, BR_OBS_APID_STRIDE = 0x20,   // observer (read) channels: 0x8000*EE + 0x20*APID
  BR_CHNL_APID_STRIDE = 0x1000,             // read/write channels: 0x1000*APID
  BR_CMD = 0x00, BR_STATUS = 0x08, BR_WDATA0 = 0x10, BR_RDATA0 = 0x18,
  BR_OP_EXT_WRITEL = 0, BR_OP_EXT_READL = 1,
  BR_STATUS_DONE = 1u << 0, BR_STATUS_ERRORS = 0xeu,      // bits 1..3: failed, denied, dropped
  BR_POLLS = 10000,

};
struct br_arbiter {
  volatile uint32_t *core;   // 0x3000 bytes
  volatile uint32_t *cnfg;   // 0x4000 bytes
  uint8_t ee;
};
struct br_found {uint32_t version, apids; int apid, owner;};

static inline uint32_t br_cmd(uint8_t op, uint8_t byte_addr, uint8_t bc) {return ((uint32_t)op << 27) | ((uint32_t)byte_addr << 4) | (bc & 7u);}

static inline int br_wait(volatile uint32_t *base) {
  for (unsigned n = 0; n < BR_POLLS; ++n) {
    uint32_t s = base[BR_STATUS / 4];
    if (s & BR_STATUS_DONE) return (s & BR_STATUS_ERRORS) ? 2 : 0;
  }
  return 1;
}
// One byte of the peripheral through the observer channel of this EE. obs/chn point at the channel bases (not the apid's channel).
static inline int br_read8(volatile uint32_t *obs, const struct br_arbiter *a, int apid, uint8_t byte_addr, uint8_t *value) {
  volatile uint32_t *ch = obs + (BR_OBS_EE_STRIDE * a->ee + BR_OBS_APID_STRIDE * (uint32_t)apid) / 4;
  ch[BR_CMD / 4] = br_cmd(BR_OP_EXT_READL, byte_addr, 0);
  int rc = br_wait(ch);
  if (rc) return rc;
  *value = (uint8_t)ch[BR_RDATA0 / 4];
  return 0;
}
static inline int br_write8(volatile uint32_t *chn, int apid, uint8_t byte_addr, uint8_t value) {
  volatile uint32_t *ch = chn + (BR_CHNL_APID_STRIDE * (uint32_t)apid) / 4;
  ch[BR_WDATA0 / 4] = value;
  ch[BR_CMD / 4] = br_cmd(BR_OP_EXT_WRITEL, byte_addr, 0);
  return br_wait(ch);
}
#endif
