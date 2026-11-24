/* SPDX-License-Identifier: BSD-2-Clause-Patent */
/* macOS 26C5035r IOAVVideoTimingData: exact 80-byte withData/getter ABI.
 * Timings describe the actual EDID/MSA mode, not the DPU porch transform. */
#pragma once
#include "B5qDpModes.h"
namespace B5qDp {
struct IoavTiming {
 uint32_t words[20]{};
 bool make(const Mode &m){
  *this={};if(!m.valid())return false;
  words[1]=m.totalWidth();words[2]=m.width;words[3]=m.hSync;
  words[4]=m.hBlank-m.hFront-m.hSync;words[5]=m.hFront;words[7]=m.hPositive;
  words[9]=m.totalHeight();words[10]=m.height;words[11]=m.vSync;
  words[12]=m.vBlank-m.vFront-m.vSync;words[13]=m.vFront;words[15]=m.vPositive;
  const uint64_t total=uint64_t(m.totalWidth())*m.totalHeight();
  const uint64_t refresh=(uint64_t(m.pixelKHz)*1000*65536+total/2)/total;
  if(!refresh||refresh>0x7fffffff){*this={};return false;}
  words[14]=uint32_t(refresh);words[17]=m.pixelKHz*1000;return true;
 }
};
static_assert(sizeof(IoavTiming)==80,"26C5035r timing payload");
}
