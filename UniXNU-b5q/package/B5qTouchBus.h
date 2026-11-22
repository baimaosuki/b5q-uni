// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>

namespace B5qTouchBus {
constexpr unsigned sda = 44, scl = 45;
constexpr uint8_t address = 0x20;

enum class Error { None, InvalidBuffer, AddressNack, DataNack, StretchTimeout, SdaStuck };

inline const char *name(Error error) {
 switch (error) {
 case Error::None: return "none";
 case Error::InvalidBuffer: return "invalid-buffer";
 case Error::AddressNack: return "address-nack";
 case Error::DataNack: return "data-nack";
 case Error::StretchTimeout: return "stretch-timeout";
 case Error::SdaStuck: return "sda-stuck";
 }
 return "unknown";
}

// Pins can only pull low or release. The touch worker owns both lines.
template<class Pins> class Bus {
 Pins &pins;
 Error error_ = Error::None, stopError_ = Error::None;
 static constexpr unsigned phaseUs = 2; // At most 250 kHz before GPIO overhead.
 static constexpr unsigned pollUs = 2, stretchUs = 1000;

 bool clockHigh() {
  pins.low(scl, false);
  for (unsigned waited = 0; ; waited += pollUs) {
   if (pins.high(scl)) {
    pins.delay(phaseUs);
    return true;
   }
   if (waited == stretchUs) return false;
   pins.delay(pollUs);
  }
 }

 Error stop() {
  pins.low(scl, true);
  pins.low(sda, true);
  pins.delay(phaseUs);
  const bool clockReleased = clockHigh();
  pins.low(sda, false);
  pins.delay(phaseUs);
  if (!clockReleased) return Error::StretchTimeout;
  return pins.high(sda) ? Error::None : Error::SdaStuck;
 }

 Error idle() {
  pins.low(sda, false);
  if (!clockHigh()) return Error::StretchTimeout;
  if (pins.high(sda)) return Error::None;

  // The target may still be sending a byte. Leave SDA released during the
  // bus clear and terminate with STOP as soon as the target lets SDA rise.
  for (unsigned pulse = 0; pulse < 9; ++pulse) {
   pins.low(scl, true);
   pins.delay(phaseUs);
   if (!clockHigh()) return Error::StretchTimeout;
   if (pins.high(sda)) return stop();
  }
  // The last falling edge may be what releases the target's SDA.
  return stop();
 }

 bool begin(bool validBuffer) {
  if (!validBuffer) {
   error_ = Error::InvalidBuffer;
   stopError_ = Error::None;
   return false;
  }
  if (!prepare()) return false;
  pins.low(sda, true);
  pins.delay(phaseUs);
  pins.low(scl, true);
  return true;
 }

 bool finish(Error transferError) {
  stopError_ = stop();
  error_ = transferError == Error::None ? stopError_ : transferError;
  return error_ == Error::None;
 }

 Error send(uint8_t byte, Error nack) {
  for (unsigned mask = 0x80; mask; mask >>= 1) {
   pins.low(sda, !(byte & mask));
   pins.delay(phaseUs);
   if (!clockHigh()) return Error::StretchTimeout;
   pins.low(scl, true);
  }
  pins.low(sda, false);
  pins.delay(phaseUs);
  if (!clockHigh()) return Error::StretchTimeout;
  const bool ack = !pins.high(sda);
  pins.low(scl, true);
  return ack ? Error::None : nack;
 }

 Error receive(uint8_t &byte, bool ack) {
  uint8_t value = 0;
  pins.low(sda, false);
  for (unsigned bit = 0; bit < 8; ++bit) {
   pins.delay(phaseUs);
   if (!clockHigh()) return Error::StretchTimeout;
   value = uint8_t((value << 1) | pins.high(sda));
   pins.low(scl, true);
  }
  // ACK every byte except the last. Release SDA for the final NACK.
  pins.low(sda, ack);
  pins.delay(phaseUs);
  if (!clockHigh()) return Error::StretchTimeout;
  pins.low(scl, true);
  byte = value;
  return Error::None;
 }

public:
 explicit Bus(Pins &p) : pins(p) {}

 Error error() const { return error_; }
 Error stopError() const { return stopError_; }

 bool prepare() {
  stopError_ = Error::None;
  error_ = idle();
  return error_ == Error::None;
 }

 bool write(const uint8_t *bytes, unsigned count) {
  if (!begin(bytes && count)) return false;
  auto result = send(address << 1, Error::AddressNack);
  for (unsigned i = 0; i < count && result == Error::None; ++i)
   result = send(bytes[i], Error::DataNack);
  return finish(result);
 }

 bool read(uint8_t *bytes, unsigned count) {
  if (!begin(bytes && count)) return false;
  auto result = send((address << 1) | 1, Error::AddressNack);
  for (unsigned i = 0; i < count && result == Error::None; ++i)
   result = receive(bytes[i], i + 1 < count);
  return finish(result);
 }
};
}
