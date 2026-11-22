// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once

#include <stdint.h>

namespace B5qUsbDmaHandoff {
// /chosen/b5q-usb-dma-state. All fields are little endian. The loader writes
// ready only after establishing an exclusive, retained, coherent USB domain.
// HAL operations return 32-bit HAL results, while LocateProtocol returns EFI_STATUS.
struct State {
    uint32_t version;
    uint32_t sid;
    uint64_t locate;
    uint32_t create;
    uint32_t configure;
    uint32_t attach;
    uint32_t map;
    uint64_t ownedBase;
    uint64_t ownedBytes;
};
static_assert(sizeof(State) == 48, "USB DMA handoff wire layout");

constexpr bool ready(uint32_t flag, const State &state) {
    return flag == 1 && state.version == 1 && state.sid == 0x40 &&
           state.locate == 0 && state.create == 0 && state.configure == 0 &&
           state.attach == 0 && state.map == 0 && state.ownedBase &&
           state.ownedBytes && !((state.ownedBase | state.ownedBytes) & 0xfff) &&
           state.ownedBytes <= UINT64_MAX - state.ownedBase;
}
}
