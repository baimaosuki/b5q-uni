// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include <stdint.h>

namespace B5qTouchIrq {
constexpr unsigned gpio=19, intid=32+208;
constexpr unsigned cfg=gpio*0x1000+8, status=gpio*0x1000+12;
// pinctrl-msm.c uses detection=2 and polarity=1 for a falling edge.
constexpr uint32_t disabled(uint32_t old){return (old&~0xffu)|(3u<<5)|(1u<<4)|(2u<<2)|(1u<<1);}

template<class Read,class Write> bool acknowledge(Read read,Write write){
 if(!(read(status)&1u))return false;
 write(status,0); // SM8550 TLMM acknowledges by writing zero.
 return true;
}
}
