// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "B5qUsbInputs.h"
#include "GeniI2c.h"

namespace B5qUsbBoardCore {
constexpr uint32_t se6PadMask = 0x3ff; // GPIO OE, drive, mux, and pull
// Kalama PINGROUP puts usb_phy first on GPIO48, so qup1_se6_l0 is slot 2.
// The active DTS states select qup1_se6_l0/l1, bias-pull-up and 2 mA.
constexpr uint32_t se6Sda = (2u << 2) | 3u;
constexpr uint32_t se6Scl = (1u << 2) | 3u;
constexpr uint32_t geniIos = 0x908; // Samsung include/linux/qcom-geni-se.h
constexpr uint32_t sdaHigh = 1u << 0;
constexpr uint32_t sclHigh = 1u << 1;
constexpr uint32_t nackIrq = 1u << 10; // M_GP_IRQ_1_EN

template <class Read, class Write>
bool configureSe6Pads(Read read, Write write, uint32_t &sda, uint32_t &scl)
{
    write(48, (read(48) & ~se6PadMask) | se6Sda);
    write(49, (read(49) & ~se6PadMask) | se6Scl);
    sda = read(48);
    scl = read(49);
    return (sda & se6PadMask) == se6Sda && (scl & se6PadMask) == se6Scl;
}

struct ResetRegisters {
    uint8_t mode, vin, pull, source, drive, enable;
};

template <class Read, class Write, class Sleep, class Report>
bool resetTi(Read read, Write write, Sleep sleepMs, Report report)
{
    uint8_t type = 0, subtype = 0;
    if (!read(0x04, type) || !read(0x05, subtype) ||
        type != 0x10 || subtype != 0x13) {
        report("identity", type, subtype, ResetRegisters{}, false, false);
        return false;
    }

    // b5q eUSB2 reset pinctrl specifies normal function, VIN1, bias-disable,
    // medium drive and both input-enable and output-enable. Samsung Linux
    // pinctrl-spmi-gpio.c encodes subtype 0x13 as MV_VIN3, mode 2 as digital
    // input/output and source bit 7 as the GPIO output value. Drive type 0
    // selects CMOS push-pull. The pulse and settle times are the v27 policy.
    constexpr uint8_t mode = 2, vin = 1, pull = 5, drive = 2, enable = 0x80;
    auto verify = [&](const char *phase, uint8_t source) {
        ResetRegisters r{};
        const bool readOk = read(0x40, r.mode) && read(0x41, r.vin) &&
            read(0x42, r.pull) && read(0x44, r.source) &&
            read(0x45, r.drive) && read(0x46, r.enable);
        const bool ok = readOk && (r.mode & 0x03) == mode &&
            (r.vin & 0x07) == vin && (r.pull & 0x07) == pull &&
            (r.source & 0x8f) == source && (r.drive & 0x33) == drive &&
            (r.enable & 0x80) == enable;
        report(phase, type, subtype, r, readOk, ok);
        return ok;
    };
    if (!write(0x41, vin) || !write(0x42, pull) || !write(0x45, drive) ||
        !write(0x40, mode) || !write(0x44, 0) || !write(0x46, enable)) {
        return false;
    }
    sleepMs(2);
    if (!verify("low", 0) || !write(0x44, 0x80)) return false;
    sleepMs(5);
    return verify("high", 0x80);
}

enum class TiOperation { Revision, AlternateRevision, OverrideWrite, OverrideRead };
struct Transfer {
    bool ok;
    uint8_t value, error;
    uint32_t errorStatus, ios;

    bool nack() const { return error == GeniErrBus && (errorStatus & nackIrq); }
};

template <class Read, class Write, class Delay, class Report>
bool configureTi(Read read, Write write, Delay delayUs, Report report)
{
    constexpr uint8_t address = 0x3e, revision = 0xb0;
    // Samsung repeater-i2c-eusb2.c makes the first regmap call before
    // its three-retry loop. Use the v27 500 us delay between attempts.
    constexpr unsigned retries = 3;
    bool revisionNack = false;
    auto retry = [&](TiOperation operation, uint8_t reg, auto attempt) {
        Transfer result{};
        unsigned count = 0;
        do {
            if (count) delayUs(500);
            result = attempt();
            ++count;
            if (operation == TiOperation::Revision && !result.ok && result.nack()) {
                revisionNack = true;
            }
        } while (!result.ok && count <= retries);
        report(operation, address, reg, result, count);
        return result;
    };
    const auto version = retry(TiOperation::Revision, revision,
                               [&]{ return read(address, revision); });
    if (!version.ok) {
        // The node is named @4f in the DTS but its reg is 0x3e. Probe only
        // for diagnostics, once, with the same revision register.
        if (revisionNack) {
            constexpr uint8_t alternate = 0x4f;
            report(TiOperation::AlternateRevision, alternate, revision,
                   read(alternate, revision), 1);
        }
        return false;
    }
    if (version.value == 0 || version.value == 0xff) return false;

    // Both role sequences in the b5q runtime DTS contain these four pairs.
    for (const auto &pair : B5qUsbInputs::tiHost) {
        if (!retry(TiOperation::OverrideWrite, pair.reg, [&]{
                return write(address, pair.reg, pair.value);
            }).ok) return false;
    }
    // Readbacks are diagnostic. A register may mask or modify written bits.
    for (const auto &pair : B5qUsbInputs::tiHost) {
        retry(TiOperation::OverrideRead, pair.reg,
              [&]{ return read(address, pair.reg); });
    }
    return true;
}
}
