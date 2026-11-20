// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <IOKit/IOLib.h>
#include <pexpert/pexpert.h>
// Reference optional GPU latency records use the existing persistent console.
// No second binary trace transport or boot-screen overlay is required.
static inline int boot_latency_enabled() {
    unsigned value=0;return PE_parse_boot_argn("diag",&value,sizeof(value)) && value;
}
static inline void boot_latency_record(uint32_t kind,uint64_t a,uint64_t b,uint64_t c,uint64_t d,uint64_t e,uint64_t f) {
    if (boot_latency_enabled()) IOLog("B5qGpu: trace=%u %llx %llx %llx %llx %llx %llx\n",kind,a,b,c,d,e,f);
}
