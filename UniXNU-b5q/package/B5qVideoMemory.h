/* SPDX-License-Identifier: GPL-2.0-only */
#pragma once
#include "QcomIrisDevice.h"
bool b5q_video_memory_init();
uint32_t b5q_video_memory_used();
int b5q_video_allocate(uint64_t bytes,uint32_t alignment,QcomIrisBuffer *buffer);
int b5q_video_map(IOMemoryDescriptor *,uint64_t offset,uint64_t bytes,QcomIrisBuffer *);
void b5q_video_release(QcomIrisBuffer *);
bool b5q_video_input(QcomIrisBuffer *,uint64_t bytes);
// Normalize a firmware payload at dataOffset to the start of the client plane.
bool b5q_video_output(QcomIrisBuffer *,uint64_t dataOffset,uint64_t bytes);
