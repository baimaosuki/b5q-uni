#!/usr/bin/env python3
"""Execute full USB HAL producer and final-map coverage with stale TLB faults."""
from pathlib import Path
import ast,subprocess,tempfile
R=Path(__file__).resolve().parents[2];D=R/'uefi-b5q/Platforms/Samsung/b5qPkg/Drivers/B5qHandoffDxe';I=D.parent.parent/'Include'
module=ast.parse((R/'tests/b5q-ufs/test-media-producer.py').read_text());assign=next(n for n in module.body if isinstance(n,ast.Assign)and any(isinstance(t,ast.Name)and t.id=='pre'for t in n.targets));prefix=ast.literal_eval(assign.value.func.value).split('\nSOURCE\n')[0]
prefix=prefix.replace('#include "B5qMediaDma.h"','#include "B5qUsbDma.h"').replace('static unsigned clears,','static unsigned clears,')
prefix=prefix.replace('static struct {__typeof__(&locate)', 'typedef struct {UINT32 Type;UINT64 PhysicalStart,VirtualStart,NumberOfPages,Attribute;}EFI_MEMORY_DESCRIPTOR;\nstatic EFI_STATUS getmap(UINTN*,EFI_MEMORY_DESCRIPTOR*,UINTN*,UINTN*,UINT32*);\nstatic struct {__typeof__(&getmap)GetMemoryMap;__typeof__(&locate)').replace('services={locate,allocate,release,install}', 'services={getmap,locate,allocate,release,install}')
prefix+='''
#define EFI_ALREADY_STARTED 20
#define MAX_UINT64 UINT64_MAX
#define MAX_UINT32 UINT32_MAX
#define EfiLoaderCode 1
#define EfiLoaderData 2
#define EfiBootServicesCode 3
#define EfiBootServicesData 4
#define EfiConventionalMemory 7
#define MIN(a,b) ((a)<(b)?(a):(b))
#define MAX(a,b) ((a)>(b)?(a):(b))
'''
source='\n'.join(l for l in (D/'UsbDma.c').read_text().splitlines()if not l.startswith('#include'))
source=source.replace('__asm__ volatile ("dsb sy" ::: "memory");','barriers++;').replace('(VOID *)(UINTN)Table','host(Table)')
tail=r'''
static unsigned faultCode,flushCalls;static bool stale;
static UINT32 create(void **p){creates++;*p=(void*)1;return 0;}
static UINT32 drop(void *p){assert(p==(void*)1);deletes++;return 0;}
static UINT32 configure(void *p,HAL_DOMAIN_CONFIG *c){assert(p==(void*)1&&c->Ttbr0==bases[0]&&c->Sctlr==0xc01027&&c->Tcr==0x803510&&c->Tcr2==0x3c071);configures++;return 0;}
static UINT32 attach(void *p,const char*n,UINT32 arid,UINT32 zero){assert(p==(void*)1&&!strcmp(n,"USB0")&&arid==0x03000000&&!zero&&cleans==1&&barriers==1&&configures==1);attaches++;stale=true;return faultCode==3?3:0;}
static UINT32 flush(void *p){assert(p==(void*)1&&stale&&attaches==1);flushCalls++;if(faultCode==4)return 4;stale=false;return 0;}
static HAL_TABLE hal={create,drop,attach,attach,configure,flush};
static void init(const HAL_TABLE **out){*out=&hal;}
static HAL_PROTOCOL protocol={0x10002,init,NULL};
static EFI_STATUS locate(EFI_GUID *g,void*u,void**o){assert(g->Data1==0x54b6d3b4&&!u);*o=&protocol;return 0;}
static EFI_STATUS allocate(unsigned type,unsigned mem,size_t pages,EFI_PHYSICAL_ADDRESS *pa){assert(type==1&&mem==0&&pages==2048);allocs++;if(allocs==1){assert(*pa==0xffffffffULL);if(faultCode==1)return 9;}else assert(*pa==B5Q_USB_DMA_LIMIT-1);bases[0]=faultCode==1?0xa0c000000:0xd0000000;lengths[0]=pages*4096;buffers[0]=calloc(pages,4096);assert(buffers[0]);*pa=bases[0];return 0;}
static EFI_STATUS release(EFI_PHYSICAL_ADDRESS pa,size_t pages){assert(!attaches);assert(pa==bases[0]&&pages==2048);frees++;return 0;}
static EFI_STATUS install(EFI_HANDLE*h,EFI_GUID*g,void*v,void*x){return 0;}
static EFI_STATUS getmap(UINTN *bytes,EFI_MEMORY_DESCRIPTOR *out,UINTN*key,UINTN*stride,UINT32*v){
 EFI_MEMORY_DESCRIPTOR map[4]={{.Type=EfiLoaderCode,.PhysicalStart=0x88ba04000,.NumberOfPages=0x180000000/4096},
 {.Type=EfiReservedMemoryType,.PhysicalStart=bases[0],.NumberOfPages=2048}};
 if(bases[0]<0x100000000ULL){map[2]=(EFI_MEMORY_DESCRIPTOR){.Type=EfiConventionalMemory,.PhysicalStart=0xc7cc0000,.NumberOfPages=(bases[0]-0xc7cc0000)/4096};map[3]=(EFI_MEMORY_DESCRIPTOR){.Type=EfiConventionalMemory,.PhysicalStart=bases[0]+lengths[0],.NumberOfPages=(0xd4d00000-bases[0]-lengths[0])/4096};}
 else {map[2]=(EFI_MEMORY_DESCRIPTOR){.Type=EfiConventionalMemory,.PhysicalStart=0xc7cc0000,.NumberOfPages=(0xd4d00000-0xc7cc0000)/4096};map[3]=(EFI_MEMORY_DESCRIPTOR){.Type=EfiBootServicesData,.PhysicalStart=0xe0000000,.NumberOfPages=16};}
 assert(*bytes>=sizeof(map));*bytes=sizeof(map);*stride=sizeof(map[0]);*key=*v=1;memcpy(out,map,sizeof(map));return 0;}
static UINT64 ReadUnaligned64(const UINT64 *p){UINT64 pa=(UINT64)(uintptr_t)p,result;if(pa>=bases[0]&&pa-bases[0]<lengths[0])memcpy(&result,host(pa),8);else memcpy(&result,p,8);return result;}
static UINT64 DarwinRangeBase(const UINT8*p,UINTN i){return ReadUnaligned64((const UINT64*)(p+i*16));}
static UINT64 DarwinRangeSize(const UINT8*p,UINTN i){return ReadUnaligned64((const UINT64*)(p+i*16+8));}
#define AsciiStrCmp strcmp
#define CopyMem memcpy
#define MAX_UINTN SIZE_MAX
static bool IsZeroBuffer(const void*p,size_t n){const unsigned char*b=p;while(n--)if(*b++)return false;return true;}
#include "B5qUsbDmaLoader.h"
int main(){for(unsigned f=0;f<6;f++){
 memset(&mResult,0,sizeof(mResult));mResult.State=(B5Q_USB_DMA_STATE){1,0x40,0,UINT32_MAX,UINT32_MAX,UINT32_MAX,UINT32_MAX,0x88ba04000,0x180000000};mResult.Diagnostics.Flush=UINT32_MAX;
 faultCode=f;allocs=frees=attaches=creates=configures=cleans=barriers=flushCalls=0;hal.FlushDomain=f==5?NULL:flush;
 EFI_STATUS status=ConfigureUsbDma(&mResult);assert((status==0)==(f==0||f==1||f==2));
 if(f==3||f==4)assert(!frees&&attaches==1&&stale);if(f==5)assert(!allocs&&!attaches&&!flushCalls);
 if(!status){assert(!stale&&flushCalls==1&&mResult.Diagnostics.UsedPages>0);assert((allocs==2)==(f==1));
  UINT64 excluded[]={0x8b9a00000,0x200000,0x8bba00000,0x4600000}; // exact original b5q reserved hole inside owned RAM
  UINT64 outside[]={0xc7cc0000,0x10000};
  assert(UsbDmaCoverage(&mResult.Diagnostics,0x88ba04000,0x180000000,(UINT8*)excluded,2,(UINT8*)outside,1));
  outside[0]=bases[0];assert(!UsbDmaCoverage(&mResult.Diagnostics,0x88ba04000,0x180000000,(UINT8*)excluded,2,(UINT8*)outside,1));
  outside[0]=0xf3800000;assert(!UsbDmaCoverage(&mResult.Diagnostics,0x88ba04000,0x180000000,(UINT8*)excluded,2,(UINT8*)outside,1));
  outside[0]=0xc7cc0000;UINT64 *root=host(bases[0]);UINT64 saved=root[0];root[0]=((bases[0]+lengths[0])|3);assert(!UsbDmaIdentityRange(&mResult.Diagnostics,0xc7cc0000,4096));root[0]=saved;
 }
 free(buffers[0]);buffers[0]=NULL;
 }
 puts("PASS fullUSBproducer:low4GiBfirst/highfallback,2048reservedpages,fullcacheclean,attach-beforeflush clearscausalstaleTLB,flusherror/missingpointerreject;actualfinalcoverage6GiB+outside rejectssecure/table/invalidnexttable");}
'''
with tempfile.TemporaryDirectory(prefix='b5q-review5-firmware-')as td:
 t=Path(td);(t/'test.c').write_text(prefix+'\n'+source+'\n'+tail)
 subprocess.run(['cc','-std=c11','-O1','-g','-fsanitize=address,undefined','-I'+str(I),'-I'+str(D),'-I'+str(R/'UniXNU/drivers/DarwinBoot/DarwinBootPkg/Driver'),str(t/'test.c'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test')],check=True)
