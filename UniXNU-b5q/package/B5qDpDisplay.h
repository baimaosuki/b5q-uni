/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#pragma once
#include "B5qDpModes.h"
class IOService;
class IOMemoryDescriptor;
// Adapter calls run on the external framebuffer work loop. The native
// scanout owner retains its context through a successful disconnect.
struct B5qDpDisplayConfig {
 B5qDp::Mode mode;
 uint8_t edid[1024];unsigned edidBytes;
 void *context;
 bool (*present)(void *,IOMemoryDescriptor *,uint64_t,bool,uint64_t);
 bool (*drain)(void *);
};
extern "C" IOService *b5q_dp_display_create(IOService *,const B5qDpDisplayConfig *);
extern "C" bool b5q_dp_display_disconnect(IOService *);
// Called by the real IRQ/presentation worker. A zero tag is a VSync with
// no completed flip, never a fabricated request completion.
extern "C" void b5q_dp_display_frame(IOService *,uint64_t,uint32_t,uint64_t);
