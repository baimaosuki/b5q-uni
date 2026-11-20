// SPDX-License-Identifier: BSD-2-Clause-Patent
// Batch immutable media reads; authenticate each 4K block before copying it.
#pragma once
#include <stdint.h>
#include <stddef.h>
namespace B5qVerifiedRead {
constexpr uint32_t blockBytes=4096;
struct Result { bool success; uint64_t done; };
template<class Read,class Verify,class Copy>
Result transfer(uint64_t offset,uint64_t bytes,uint64_t imageBytes,
                uint8_t *scratch,uint32_t scratchBytes,Read read,Verify verify,Copy copy) {
 Result result={false,0};
 if(!scratch || scratchBytes<blockBytes || scratchBytes%blockBytes ||
    !bytes || imageBytes%blockBytes || offset>imageBytes || bytes>imageBytes-offset)return result;
 while(bytes) {
  const uint64_t aligned=offset&~uint64_t(blockBytes-1);
  const uint32_t skip=uint32_t(offset-aligned);
  uint64_t needed=bytes+skip;
  uint32_t chunk=needed>=scratchBytes?scratchBytes:uint32_t((needed+blockBytes-1)&~uint64_t(blockBytes-1));
  if(chunk>imageBytes-aligned || !read(aligned,chunk,scratch))return result;
  for(uint32_t at=0;at<chunk && bytes;at+=blockBytes) {
   if(!verify((aligned+at)/blockBytes,scratch+at))return result;
   const uint32_t in=at?0:skip;
   const uint32_t take=uint32_t(bytes<blockBytes-in?bytes:blockBytes-in);
   const uint64_t copied=copy(result.done,scratch+at+in,take);
   if(copied>take)return result;
   result.done+=copied;
   if(copied!=take)return result;
   offset+=take;bytes-=take;
  }
 }
 result.success=true;return result;
}
}
