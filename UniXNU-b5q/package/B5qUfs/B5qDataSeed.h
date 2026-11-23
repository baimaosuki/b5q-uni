// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "B5qDataFormat.h"
namespace B5qData {
constexpr const char *volumeUuid="1552CFEE-78FF-48D8-8A6C-694B867D61AC";
// This identifies the validated immutable envelope, not a hash of mutable Data.
inline bool seed(const Volume &v,bool online,const char *uuid,const uint8_t hash[32],
                 uint64_t *base,uint64_t *bytes,uint8_t digest[32]) {
 if(!base||!bytes||!digest||!uuid||!hash||!online||!v.valid||
    !equal(v.uuid,expectedVolumeUuid,16)||!nonzero(hash,32)||
    !v.blocks||v.blocks>((UINT64_C(1)<<40)/sector))return false;
 unsigned i=0;for(;volumeUuid[i];++i)if(uuid[i]!=volumeUuid[i])return false;
 if(uuid[i])return false;
 *base=0;*bytes=v.blocks*sector;
 for(unsigned j=0;j<32;++j)digest[j]=hash[j];
 return true;
}
}
