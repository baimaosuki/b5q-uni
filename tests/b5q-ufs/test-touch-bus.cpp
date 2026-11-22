// SPDX-License-Identifier: BSD-2-Clause-Patent
#include "B5qTouchBus.h"
#include "B5qTouchProtocol.h"
#include <cassert>
#include <cstdio>
#include <vector>

namespace {
// A target observes actual line edges. Either side can hold a line low,
// and SCL stretching delays the edge instead of just changing a read result.
struct Wire {
 struct Frame {
  std::vector<uint8_t> written;
  std::vector<bool> readAcks;
 };
 enum class Mode { Write, Read, Done };

 std::vector<Frame> frames;
 std::vector<std::vector<uint8_t>> replies;
 unsigned now = 0, stops = 0, recoveryClocks = 0;
 unsigned releaseSdaOn = 0, releaseCount = 0, stretchAt = 0, stretchFor = 0;
 bool sdaHeld = false, sclHeld = false, releaseOnFall = false;
 int nackByte = -1;

 bool high(unsigned pin) const {
  assert(pin == 44 || pin == 45);
  return pin == 44 ? !masterSda && !targetSda && !sdaHeld
                   : !masterScl && !sclHeld && now >= stretchUntil;
 }
 void low(unsigned pin, bool drive) {
  if (pin == 44) {
   const bool wasHigh = high(44);
   masterSda = drive;
   if (high(45) && wasHigh != high(44)) {
    if (wasHigh) {
     assert(!active);
     active = true;
     frames.emplace_back();
     mode = Mode::Write;
     bit = incoming = readIndex = 0;
    } else {
     ++stops;
     active = false;
    }
   }
  } else {
   assert(pin == 45);
   const bool wasHigh = high(45);
   if (masterScl && !drive && ++releaseCount == stretchAt)
    stretchUntil = now + stretchFor;
   masterScl = drive;
   clockEdge(wasHigh);
  }
 }
 void delay(unsigned us) {
  const bool wasHigh = high(45);
  now += us;
  clockEdge(wasHigh);
 }
 bool released() const { return !masterSda && !masterScl; }

private:
 bool masterSda = false, masterScl = false, targetSda = false, active = false;
 unsigned stretchUntil = 0, bit = 0, incoming = 0, readIndex = 0;
 Mode mode = Mode::Done;

 void readBit() {
  const auto &reply = replies.at(frames.size() - 1);
  targetSda = !(reply.at(readIndex) & (0x80 >> bit));
 }
 void clockEdge(bool wasHigh) {
  const bool isHigh = high(45);
  if (wasHigh == isHigh) return;
  if (!active) {
   if (isHigh && sdaHeld && !masterSda) ++recoveryClocks;
   if (sdaHeld && releaseSdaOn && recoveryClocks == releaseSdaOn && isHigh != releaseOnFall)
    sdaHeld = false;
   return;
  }
  if (mode == Mode::Done) return;

  auto &frame = frames.back();
  if (isHigh) {
   if (mode == Mode::Write && bit < 8) incoming = (incoming << 1) | high(44);
   if (mode == Mode::Read && bit == 8) frame.readAcks.push_back(!high(44));
   ++bit;
   return;
  }
  if (bit == 0) return; // First falling edge after START.
  if (mode == Mode::Write) {
   if (bit == 8) {
    targetSda = int(frame.written.size()) != nackByte;
    frame.written.push_back(uint8_t(incoming));
   } else if (bit == 9) {
    const bool ack = targetSda;
    targetSda = false;
    bit = incoming = 0;
    if (!ack) mode = Mode::Done;
    else if (frame.written.size() == 1 && (frame.written[0] & 1)) {
     mode = Mode::Read;
     readBit();
    }
   }
  } else if (bit == 8) {
   targetSda = false; // Release for the controller's ACK/NACK.
  } else if (bit == 9 && !frame.readAcks.back()) {
   mode = Mode::Done;
  } else {
   if (bit == 9) {
    bit = 0;
    ++readIndex;
   }
   readBit();
  }
 }
};

using B5qTouchBus::Error;
using Bus = B5qTouchBus::Bus<Wire>;

void assertReadAcks(const Wire::Frame &frame, unsigned count) {
 assert((frame.written == std::vector<uint8_t>{0x41}));
 assert(frame.readAcks.size() == count);
 for (unsigned i = 0; i < count; ++i)
  assert(frame.readAcks[i] == (i + 1 < count));
}

void nacks() {
 const uint8_t command[] = {5, 1, 0, 0xc1};
 for (int nack = 0; nack <= 4; ++nack) {
  Wire wire;
  wire.nackByte = nack;
  Bus bus(wire);
  assert(!bus.write(command, sizeof(command)));
  assert(bus.error() == (nack ? Error::DataNack : Error::AddressNack));
  assert(bus.stopError() == Error::None && wire.released());
  assert(wire.frames.size() == 1 && wire.stops == 1);
  const auto &sent = wire.frames[0].written;
  assert(sent.size() == unsigned(nack + 1) && sent[0] == 0x40);
  for (int i = 0; i < nack; ++i) assert(sent[i + 1] == command[i]);
 }

 Wire wire;
 wire.nackByte = 0;
 Bus bus(wire);
 uint8_t result = 0x55;
 assert(!bus.read(&result, 1) && result == 0x55);
 assert(bus.error() == Error::AddressNack && bus.stopError() == Error::None);
 assert(wire.frames.size() == 1 && wire.frames[0].written[0] == 0x41);
 assert(wire.frames[0].readAcks.empty() && wire.stops == 1 && wire.released());
}

void stretching() {
 const uint8_t bytes[] = {2, 0, 0};
 Wire baseline;
 Bus baselineBus(baseline);
 assert(baselineBus.write(bytes, sizeof(bytes)));
 // At 2 us per phase: idle + START + 36 clocks + STOP and bus free.
 assert(baseline.now == 2 + 2 + 36 * 4 + 6);
 for (unsigned stretchAt : {1u, 9u, 10u, 37u}) { // Data, address ACK, STOP.
  Wire wire;
  wire.stretchAt = stretchAt;
  wire.stretchFor = 60;
  Bus bus(wire);
  assert(bus.write(bytes, sizeof(bytes)));
  assert(wire.released() && wire.stops == 1);
  assert((wire.frames[0].written == std::vector<uint8_t>{0x40, 2, 0, 0}));
  assert(wire.now == baseline.now + 60);
 }

 for (unsigned stretchFor : {1040u, 5000u}) {
  Wire wire;
  wire.stretchAt = 1;
  wire.stretchFor = stretchFor;
  Bus bus(wire);
  assert(!bus.write(bytes, sizeof(bytes)) && bus.error() == Error::StretchTimeout);
  const bool recovered = stretchFor == 1040;
  assert(bus.stopError() == (recovered ? Error::None : Error::StretchTimeout));
  assert(wire.released() && wire.now <= 2100 && wire.stops == unsigned(recovered));
 }

 Wire wire;
 wire.sclHeld = true;
 Bus bus(wire);
 assert(!bus.prepare() && bus.error() == Error::StretchTimeout);
 assert(wire.released() && wire.now == 1000 && wire.frames.empty() && wire.stops == 0);

 Wire stopTimeout;
 stopTimeout.stretchAt = 37;
 stopTimeout.stretchFor = 5000;
 Bus stopBus(stopTimeout);
 assert(!stopBus.write(bytes, sizeof(bytes)));
 assert(stopBus.error() == Error::StretchTimeout && stopBus.stopError() == Error::StretchTimeout);
 assert(stopTimeout.released() && stopTimeout.stops == 0);
}

void recovery() {
 for (unsigned releaseOn : {1u, 9u, 0u}) {
  Wire wire;
  wire.sdaHeld = true;
  wire.releaseSdaOn = releaseOn;
  wire.releaseOnFall = releaseOn == 9;
  Bus bus(wire);
  const uint8_t byte = 0x25;
  assert(bus.write(&byte, 1) == (releaseOn != 0));
  assert(wire.released() && wire.recoveryClocks == (releaseOn ? releaseOn : 9));
  assert(bus.error() == (releaseOn ? Error::None : Error::SdaStuck));
  assert(wire.frames.size() == (releaseOn ? 1u : 0u));
  assert(wire.stops == (releaseOn ? 2u : 0u)); // Recovery STOP, then transaction STOP.
 }
}

void longTransfers() {
 std::vector<uint8_t> payload(4096);
 for (unsigned i = 0; i < payload.size(); ++i)
  payload[i] = uint8_t(i ^ (i >> 8));

 Wire tx;
 Bus writer(tx);
 assert(!writer.write(nullptr, 1) && writer.error() == Error::InvalidBuffer);
 assert(tx.frames.empty());
 assert(writer.write(payload.data(), 258));
 std::vector<uint8_t> expected = {0x40};
 expected.insert(expected.end(), payload.begin(), payload.begin() + 258);
 assert(tx.frames.size() == 1 && tx.frames[0].written == expected);
 assert(tx.stops == 1 && tx.released());

 Wire rx;
 rx.replies = {{0x5a}, {0xa5, 0x11, 0, 0x10}};
 for (unsigned offset = 0; offset < payload.size(); offset += 256) {
  rx.replies.push_back({0xa5, 3});
  auto &chunk = rx.replies.back();
  chunk.insert(chunk.end(), payload.begin() + offset, payload.begin() + offset + 256);
 }
 Bus reader(rx);
 uint8_t single = 0, header[4] = {};
 assert(reader.read(&single, 1) && single == 0x5a);
 assert(reader.read(header, sizeof(header)) && header[0] == 0xa5 && header[1] == 0x11);
 const unsigned length = header[2] | (unsigned(header[3]) << 8);
 assert(length == payload.size());
 std::vector<uint8_t> output(length);
 assert(B5qTouch::continuation([&](uint8_t *p, unsigned n) { return reader.read(p, n); },
                               output.data(), length));
 assert(output == payload);
 assert(rx.released() && rx.frames.size() == 18 && rx.stops == 18);
 assertReadAcks(rx.frames[0], 1);
 assertReadAcks(rx.frames[1], 4);
 for (unsigned i = 2; i < rx.frames.size(); ++i) assertReadAcks(rx.frames[i], 258);
}
}

int main() {
 nacks();
 stretching();
 recovery();
 longTransfers();
 puts("PASS GPIO44/45 TouchComm ACK/NACK, stretch/timeout, nine-clock recovery, and 4096-byte continuation");
}
