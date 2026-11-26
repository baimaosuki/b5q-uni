// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>

namespace B5qUsbHostEvent {

struct Event {
    uint64_t parameter;
    uint32_t status, control;
    unsigned completion, type, slot, endpoint, cycle;
};

// Locate ERDP in one of the bounded ERST segments and visit the most recent
// entries preceding it. Read is the loader-qualified physical RAM reader.
template <class Read, class Emit>
bool latest(uint64_t table, unsigned tableEntries, uint64_t erdp,
            unsigned limit, Read read, Emit emit)
{
    constexpr unsigned maxTableEntries = 64;
    if (!table || (table & 63) || !tableEntries ||
        tableEntries > maxTableEntries || !limit) return false;
    const uint64_t pointer = erdp & ~15ULL;
    for (unsigned segment = 0; segment < tableEntries; ++segment) {
        if (table > UINT64_MAX - uint64_t(segment) * 16 - 16) return false;
        const uint64_t descriptor = table + uint64_t(segment) * 16;
        uint64_t baseWord = 0, sizeWord = 0;
        if (!read(descriptor, baseWord) || !read(descriptor + 8, sizeWord)) return false;
        const uint64_t base = baseWord & ~63ULL;
        const unsigned entries = uint32_t(sizeWord) & 0xffffu;
        if (!base || entries < 16 || entries > 65536) continue;
        const uint64_t bytes = uint64_t(entries) * 16;
        if (base > UINT64_MAX - bytes || pointer < base || pointer >= base + bytes ||
            ((pointer - base) & 15)) continue;
        const unsigned current = unsigned((pointer - base) / 16);
        const unsigned count = limit < entries ? limit : entries;
        for (unsigned back = 1; back <= count; ++back) {
            const unsigned index = (current + entries - back) % entries;
            uint64_t parameter = 0, words = 0;
            if (!read(base + uint64_t(index) * 16, parameter) ||
                !read(base + uint64_t(index) * 16 + 8, words)) return false;
            const uint32_t status = uint32_t(words), control = uint32_t(words >> 32);
            emit(segment,index,Event{parameter,status,control,status >> 24,
                (control >> 10) & 63u,(control >> 24) & 255u,
                (control >> 16) & 31u,control & 1u});
        }
        return true;
    }
    return false;
}

} // namespace B5qUsbHostEvent
