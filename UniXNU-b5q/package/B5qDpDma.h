/* SPDX-License-Identifier: BSD-2-Clause-Patent */
#pragma once
#include <stdint.h>
#define UINT32 uint32_t
#define UINT64 uint64_t
#define BOOLEAN bool
#define CONST const
#define STATIC static
#define STATIC_ASSERT static_assert
/* SPDX-License-Identifier: BSD-2-Clause-Patent */
/* b5q original DT cont_splash/earlymap contract, explicitly selected by
 * the owner. The producer validates real GOP/SSPP occupancy; no SMMU
 * register access, mapping change or DisplayDxe patch is involved. */
#ifndef B5Q_DP_DMA_H
#define B5Q_DP_DMA_H
#define B5Q_DP_DMA_PROTOCOL_GUID {0x16d34ec5,0x82cc,0x481e,{0xa7,0x66,0x31,0x9e,0x57,0x20,0x15,0xb5}}
#define B5Q_DP_SPLASH_BASE 0xb8000000ULL
#define B5Q_DP_SPLASH_END  0xbab00000ULL
#define B5Q_DP_ALIGNMENT  0x200000ULL
#define B5Q_DP_MIN_POOL   0x1000000ULL
typedef struct {
 UINT32 Version,PrimaryChecked,SidMask,Reserved;
 UINT64 FrameBufferBase,FrameBufferBytes,PrimaryEnd,PoolBase,PoolBytes,Alignment,PrepareStatus,RetentionStatus;
} B5Q_DP_DMA_STATE;
STATIC_ASSERT(sizeof(B5Q_DP_DMA_STATE)==80,"DP DMA handoff ABI");
STATIC inline BOOLEAN B5qDpPool(B5Q_DP_DMA_STATE *S,UINT64 Base,UINT64 Bytes,UINT64 PrimaryEnd)
{
 if(!S||Base<B5Q_DP_SPLASH_BASE||Base>=B5Q_DP_SPLASH_END||!Bytes||Bytes>B5Q_DP_SPLASH_END-Base||
    PrimaryEnd<Base+Bytes||PrimaryEnd>B5Q_DP_SPLASH_END)return false;
 UINT64 Pool=(PrimaryEnd+B5Q_DP_ALIGNMENT-1)&~(B5Q_DP_ALIGNMENT-1);
 if(Pool>B5Q_DP_SPLASH_END||B5Q_DP_SPLASH_END-Pool<B5Q_DP_MIN_POOL)return false;
 S->Version=1;S->PrimaryChecked=1;S->SidMask=0x00021c00;S->Reserved=0;
 S->FrameBufferBase=Base;S->FrameBufferBytes=Bytes;S->PrimaryEnd=PrimaryEnd;
 S->PoolBase=Pool;S->PoolBytes=B5Q_DP_SPLASH_END-Pool;S->Alignment=B5Q_DP_ALIGNMENT;
 return true;
}
STATIC inline BOOLEAN B5qDpPoolValid(CONST B5Q_DP_DMA_STATE *S)
{
 B5Q_DP_DMA_STATE Expected={0};
 return S&&S->Version==1&&S->PrimaryChecked==1&&S->SidMask==0x00021c00&&!S->Reserved&&
  !S->PrepareStatus&&!S->RetentionStatus&&B5qDpPool(&Expected,S->FrameBufferBase,S->FrameBufferBytes,S->PrimaryEnd)&&
  S->PoolBase==Expected.PoolBase&&S->PoolBytes==Expected.PoolBytes&&S->Alignment==B5Q_DP_ALIGNMENT;
}
#ifdef EFIAPI
typedef VOID(EFIAPI *B5Q_DP_DMA_PREPARE)(B5Q_DP_DMA_STATE *);
typedef struct {UINT64 Revision;B5Q_DP_DMA_PREPARE Prepare;} B5Q_DP_DMA_PROTOCOL;
#endif
#endif

#undef UINT32
#undef UINT64
#undef BOOLEAN
#undef CONST
#undef STATIC
#undef STATIC_ASSERT
