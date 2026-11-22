// SPDX-License-Identifier: BSD-2-Clause-Patent
#include "B5qUsbBoardCore.h"
#include <array>
#include <cassert>
#include <cstdio>
#include <string_view>
#include <vector>

using namespace B5qUsbBoardCore;

static void testPads()
{
    std::array<uint32_t, 2> ctl{0xa5ff, 0x53ff};
    uint32_t sda = 0, scl = 0;
    auto read = [&](unsigned pin) { return ctl.at(pin - 48); };
    auto write = [&](unsigned pin, uint32_t value) { ctl.at(pin - 48) = value; };
    assert(configureSe6Pads(read, write, sda, scl));
    assert(sda == 0xa40b && scl == 0x5007);

    ctl[0] = 0;
    auto lostSdaWrite = [&](unsigned pin, uint32_t value) {
        if (pin == 49) write(pin, value);
    };
    assert(!configureSe6Pads(read, lostSdaWrite, sda, scl));
    assert(sda == 0 && scl == 0x5007);
}

struct ResetMock {
    std::array<uint8_t, 256> registers{};
    std::vector<unsigned> trace;
    uint8_t badRead = 0, badWrite = 0, badReadback = 0;
    // Include phases in the trace to detect verification before the delays.
    enum { Read = 0x10000, Write = 0x20000, Sleep = 0x30000,
           Low = 0x40000, High = 0x40001, Identity = 0x40002 };

    ResetMock() { registers[4] = 0x10; registers[5] = 0x13; }

    bool run()
    {
        return resetTi(
            [&](uint8_t reg, uint8_t &value) {
                trace.push_back(Read | reg);
                if (reg == badRead) return false;
                value = registers[reg] ^ (reg == badReadback ? 1 : 0);
                return true;
            },
            [&](uint8_t reg, uint8_t value) {
                trace.push_back(Write | (unsigned(reg) << 8) | value);
                if (reg == badWrite) return false;
                registers[reg] = value;
                return true;
            },
            [&](unsigned ms) { trace.push_back(Sleep | ms); },
            [&](std::string_view phase, uint8_t, uint8_t,
                const ResetRegisters &r, bool readOk, bool ok) {
                if (phase == "identity") {
                    assert(!ok);
                    trace.push_back(Identity);
                    return;
                }
                if (ok) {
                    assert(readOk && r.mode == 2 && r.vin == 1 && r.pull == 5);
                    assert(r.source == (phase == "low" ? 0 : 0x80));
                    assert(r.drive == 2 && r.enable == 0x80);
                }
                trace.push_back(phase == "low" ? Low : High);
            });
    }
};

static void testReset()
{
    ResetMock good;
    using R = ResetMock;
    assert(good.run());
    const std::vector<unsigned> expected{
        R::Read | 4, R::Read | 5,
        R::Write | 0x4101, R::Write | 0x4205, R::Write | 0x4502,
        R::Write | 0x4002, R::Write | 0x4400, R::Write | 0x4680, R::Sleep | 2,
        R::Read | 0x40, R::Read | 0x41, R::Read | 0x42, R::Read | 0x44,
        R::Read | 0x45, R::Read | 0x46, R::Low,
        R::Write | 0x4480, R::Sleep | 5,
        R::Read | 0x40, R::Read | 0x41, R::Read | 0x42, R::Read | 0x44,
        R::Read | 0x45, R::Read | 0x46, R::High,
    };
    assert(good.trace == expected);

    ResetMock wrongSubtype;
    wrongSubtype.registers[5] = 0x0d;
    assert(!wrongSubtype.run());
    assert((wrongSubtype.trace == std::vector<unsigned>{R::Read | 4, R::Read | 5, R::Identity}));

    ResetMock writeError;
    writeError.badWrite = 0x42;
    assert(!writeError.run());
    assert(writeError.trace.size() == 4 && writeError.trace.back() == (R::Write | 0x4205));

    for (bool readError : {false, true}) {
        ResetMock lowUnverified;
        if (readError) lowUnverified.badRead = 0x41;
        else lowUnverified.badReadback = 0x45;
        assert(!lowUnverified.run());
        assert(lowUnverified.trace.back() == R::Low);
        assert(lowUnverified.registers[0x44] == 0);
    }
}

struct TiMock {
    struct Diagnostic { TiOperation op; uint8_t address, reg; Transfer result; unsigned attempts; };
    std::vector<Diagnostic> logs;
    std::vector<unsigned> delays;
    std::vector<unsigned> writes;
    unsigned revAttempts = 0, altAttempts = 0, diagnosticReads = 0;
    unsigned revFailures = 0, writeFailures = 0;
    uint8_t failedWriteReg = 0x70, version = 3;
    bool readbackFailure = false;
    Transfer revError{false, 0, GeniErrBus, GENI_M_CMD_FAILURE | (1u << 10), 3};

    bool run()
    {
        return configureTi(
            [&](uint8_t address, uint8_t reg) -> Transfer {
                if (address == 0x4f) {
                    assert(reg == 0xb0);
                    ++altAttempts;
                    return {true, 0x12, GeniOk, 0, 3};
                }
                assert(address == 0x3e);
                if (reg == 0xb0) {
                    if (++revAttempts <= revFailures) return revError;
                    return {true, version, GeniOk, 0, 3};
                }
                ++diagnosticReads;
                if (readbackFailure) return {false, 0, GeniErrTimeout, 0, 3};
                return {true, 0, GeniOk, 0, 3}; // All four readbacks differ.
            },
            [&](uint8_t address, uint8_t reg, uint8_t value) -> Transfer {
                assert(address == 0x3e);
                writes.push_back((unsigned(reg) << 8) | value);
                if (reg == failedWriteReg && writeFailures) {
                    --writeFailures;
                    return {false, 0, GeniErrBus, 1u << 10, 3};
                }
                return {true, value, GeniOk, 0, 3};
            },
            [&](unsigned us) { assert(us == 500); delays.push_back(us); },
            [&](TiOperation op, uint8_t address, uint8_t reg, Transfer result, unsigned attempts) {
                logs.push_back({op, address, reg, result, attempts});
            });
    }
};

static void testRepeater()
{
    TiMock recovery;
    recovery.revFailures = 3;
    recovery.writeFailures = 1;
    assert(recovery.run());
    assert(recovery.revAttempts == 4 && recovery.altAttempts == 0);
    assert((recovery.writes == std::vector<unsigned>{0x707d, 0x707d, 0x713e, 0x7376, 0x7970}));
    assert(recovery.logs[0].attempts == 4 && recovery.logs[1].attempts == 2);
    assert(recovery.delays.size() == 4 && recovery.diagnosticReads == 4);

    TiMock nack;
    nack.revFailures = 10;
    assert(!nack.run());
    assert(nack.revAttempts == 4 && nack.altAttempts == 1 && nack.delays.size() == 3);
    assert(nack.writes.empty() && nack.logs.size() == 2);
    assert(nack.logs[0].op == TiOperation::Revision && nack.logs[0].result.nack());
    assert(nack.logs[1].op == TiOperation::AlternateRevision && nack.logs[1].result.ok);

    TiMock timeout;
    timeout.revFailures = 10;
    timeout.revError.error = GeniErrTimeout; // Stale GP IRQ alone is insufficient.
    assert(!timeout.run() && timeout.altAttempts == 0 && timeout.revAttempts == 4);

    for (uint8_t invalidVersion : {0, 0xff}) {
        TiMock invalid;
        invalid.version = invalidVersion;
        assert(!invalid.run() && invalid.writes.empty() && invalid.altAttempts == 0);
    }

    TiMock writeError;
    writeError.failedWriteReg = 0x71;
    writeError.writeFailures = 10;
    assert(!writeError.run() && writeError.diagnosticReads == 0);
    assert((writeError.writes == std::vector<unsigned>{0x707d, 0x713e, 0x713e, 0x713e, 0x713e}));
    assert(writeError.logs.back().attempts == 4 && writeError.altAttempts == 0);

    TiMock diagnosticError;
    diagnosticError.readbackFailure = true;
    assert(diagnosticError.run());
    assert(diagnosticError.writes.size() == 4 && diagnosticError.diagnosticReads == 16);
    assert(diagnosticError.delays.size() == 12 && diagnosticError.logs.size() == 9);
}

int main()
{
    testPads();
    testReset();
    testRepeater();
    std::puts("PASS v27 SE6 pinctrl, subtype-0x13 reset/readback, TI retry and diagnostic bounds");
}
