#!/usr/bin/env python3
"""Fault-inject the real EFI media HAL producer and reserved-page lifetime."""
from pathlib import Path
import subprocess,tempfile
R=Path(__file__).resolve().parents[2]
s=(R/'uefi-b5q/Platforms/Samsung/b5qPkg/Drivers/B5qHandoffDxe/MediaDma.c').read_text()
s='\n'.join(l for l in s.splitlines()if not l.startswith('#include'))
s=s.replace('__asm__ volatile("dsb sy":::"memory");','barriers++;')
# Only the EFI physical-to-host VA boundary is translated in this harness.
# Pool/table identity and all production size/status/ownership checks stay real.
s=s.replace('(VOID*)(UINTN)Table','host(Table)').replace('(VOID*)(UINTN)R->PoolBase','host(R->PoolBase)')
pre=r'''
#define _GNU_SOURCE
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#define STATIC static
#define CONST const
#define VOID void
#define OUT
#define IN
#define EFIAPI
#define STATIC_ASSERT _Static_assert
#define OFFSET_OF offsetof
#define TRUE true
#define FALSE false
#define EFI_PAGE_SIZE 4096
#define EFI_ERROR(x) ((x)!=0)
#define EFI_SUCCESS 0
#define EFI_NOT_STARTED 19
#define EFI_INVALID_PARAMETER 2
#define EFI_DEVICE_ERROR 7
#define EFI_COMPROMISED_DATA 33
#define EFI_INCOMPATIBLE_VERSION 25
#define EFI_UNSUPPORTED 3
#define EfiReservedMemoryType 0
#define AllocateMaxAddress 1
#define ALIGN_VALUE(v,a) (((v)+((a)-1))&~((a)-1))
#define DEBUG_ERROR 1
#define DEBUG(x) ((void)0)
#define ZeroMem(p,n) do{clears++;memset(p,0,n);}while(0)
typedef uint8_t UINT8;typedef uint16_t UINT16;typedef uint32_t UINT32;typedef uint64_t UINT64,EFI_STATUS,EFI_PHYSICAL_ADDRESS;typedef size_t UINTN;typedef bool BOOLEAN;typedef char CHAR8;typedef void *EFI_HANDLE;
typedef struct {UINT32 Data1;UINT16 Data2,Data3;UINT8 Data4[8];} EFI_GUID;
#include "B5qMediaDma.h"
#include "B5qReservedMemory.h"
#include "PcieDmaTables.h"
static uint8_t *buffers[2];static uint64_t bases[2],lengths[2];
static void *host(uint64_t pa){for(unsigned i=0;i<2;i++)if(buffers[i]&&pa>=bases[i]&&pa-bases[i]<lengths[i])return buffers[i]+pa-bases[i];assert(0);return NULL;}
static unsigned clears,fault,allocs,frees,creates,configures,attaches,deletes,cleans,barriers,locates;
static EFI_STATUS locate(EFI_GUID *,void *,void **);
static EFI_STATUS allocate(unsigned,unsigned,size_t,EFI_PHYSICAL_ADDRESS *);
static EFI_STATUS release(EFI_PHYSICAL_ADDRESS,size_t);
static EFI_STATUS install(EFI_HANDLE *,EFI_GUID *,void *,void *);
static struct {__typeof__(&locate) LocateProtocol;__typeof__(&allocate) AllocatePages;__typeof__(&release) FreePages;__typeof__(&install) InstallMultipleProtocolInterfaces;} services={locate,allocate,release,install},*gBS=&services;
static void WriteBackDataCacheRange(void *p,size_t n){assert(p&&n);cleans++;}
SOURCE
static UINT32 create(void **p){assert(!*p);creates++;if(fault==4)return 9;*p=(void*)1;return 0;}
static UINT32 drop(void *p){assert(p==(void*)1);deletes++;return 0;}
static UINT32 attach(void *p,const char *name,UINT32 arid,UINT32 zero){assert(p==(void*)1&&!zero);assert(!strcmp(name,"LPASS")||!strcmp(name,"VIDEO"));assert(arid==0x03000000||arid==0x03000001||arid==0x03000005||arid==0x0300000e);attaches++;return fault==6&&attaches==1?6:fault==7&&attaches==2?7:0;}
static UINT32 configure(void *p,HAL_CONFIG *c){assert(p==(void*)1&&c->Vmsa==0&&!c->Reserved&&!c->Ttbr1&&c->Ttbr0==0xe0000000&&c->Mair0==0xff0400&&c->Sctlr==0xc000e7&&c->Tcr==0x802010&&c->Tcr2==0x3c071);configures++;return fault==5?5:0;}
static HAL_TABLE hal={create,drop,attach,attach,configure};
static void init(const HAL_TABLE **p){assert(!*p);*p=&hal;}
static HAL_PROTOCOL protocol={0x10002,init,NULL};
static EFI_STATUS locate(EFI_GUID *g,void *unused,void **out){assert(g->Data1==0x54b6d3b4&&!unused&&!*out);locates++;if(fault==1)return 14;*out=&protocol;return 0;}
static EFI_STATUS allocate(unsigned type,unsigned mem,size_t pages,EFI_PHYSICAL_ADDRESS *address){assert(type==AllocateMaxAddress&&mem==EfiReservedMemoryType&&*address==0xffffffff);allocs++;if((fault==2&&allocs==1)||(fault==3&&allocs==2))return 9;uintptr_t base=allocs==1?(fault==8?0xf3800000:0xc8010000):(fault==9?0xf3800000:0xe0000000);buffers[allocs-1]=calloc(pages,4096);assert(buffers[allocs-1]);bases[allocs-1]=base;lengths[allocs-1]=pages*4096;*address=base;return 0;}
static EFI_STATUS release(EFI_PHYSICAL_ADDRESS address,size_t pages){frees++;assert(!attaches);assert(host(address)&&host(address+pages*4096-1));return 0;}
static EFI_STATUS install(EFI_HANDLE *h,EFI_GUID *g,void *p,void *last){assert(h&&g->Data1==0x061f797d&&p==&mProtocol&&!last);return 0;}
static void reset(unsigned f){for(unsigned i=0;i<2;i++){free(buffers[i]);buffers[i]=NULL;}memset(mResult,0,sizeof(mResult));memset(mAttempted,0,sizeof(mAttempted));fault=f;clears=0;allocs=frees=creates=configures=attaches=deletes=cleans=barriers=locates=0;}
int main(void){for(unsigned kind=1;kind<=2;kind++)for(unsigned f=0;f<=9;f++){
 reset(f);B5Q_MEDIA_DMA_RESULT r={0};PrepareMedia(kind,&r);assert(r.Kind==kind&&r.Version==1);assert((r.PrepareStatus==0)==(f==0));
 if(!f){assert(!r.Create&&!r.Configure&&!r.Attach[0]&&!r.Attach[1]&&!r.Map&&r.PoolBase==0xc8200000&&r.TableBase==0xe0000000);assert(creates==1&&configures==1&&attaches==2&&cleans==2&&barriers==1&&frees==2&&!deletes);}
 if(f==8||f==9){assert(!creates&&!configures&&!attaches&&!cleans&&!barriers&&!clears);}
 if(f==4||f==5){assert(!r.PoolBase&&!r.TableBase&&frees==4&&deletes==(f==5));}
 if(f==6||f==7){assert(r.PoolBase&&r.TableBase&&frees==2&&!deletes);}
 B5Q_MEDIA_DMA_RESULT twice={0};PrepareMedia(kind,&twice);assert(!memcmp(&r,&twice,sizeof(r))&&locates==1);
 }
 reset(0);B5Q_MEDIA_DMA_RESULT bad;PrepareMedia(0,&bad);assert(bad.PrepareStatus==EFI_INVALID_PARAMETER&&!allocs&&!locates);assert(!InstallB5qMediaDma(NULL));
 reset(0);puts("PASS actual EFI media producer16fault/dual-domain paths:exact HAL ABI,independentLPASS/VIDEOtuples,reservedWBISpages,cacheclean,partialattachmentretention,noDisplaydomain,idempotence; ASanUBSan");
}
'''.replace('\nSOURCE\n','\n'+s+'\n')
with tempfile.TemporaryDirectory(prefix='b5q-media-producer-')as td:
 t=Path(td);(t/'test.c').write_text(pre)
 subprocess.run(['cc','-std=c11','-O1','-g','-fsanitize=address,undefined','-I'+str(R/'uefi-b5q/Platforms/Samsung/b5qPkg/Include'),'-I'+str(R/'uefi-b5q/Platforms/Samsung/b5qPkg/Drivers/B5qHandoffDxe'),str(t/'test.c'),'-o',str(t/'test')],check=True);subprocess.run([str(t/'test')],check=True)
