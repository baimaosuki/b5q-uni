#!/usr/bin/env python3
"""Original b5q reserved intervals, EFI allocator and USB-page-table causality."""
from pathlib import Path
import importlib.util,json,re,subprocess,tempfile,sys
R=Path(__file__).resolve().parents[2];W=R/'artifacts/b5q-v33b-fix-work';I=R/'uefi-b5q/Platforms/Samsung/b5qPkg/Include';D=I.parent/'Drivers/B5qHandoffDxe'
spec=importlib.util.spec_from_file_location('causal',R/'tests/b5q-ufs/test-v33b-causal.py')
# Reuse only lexical extraction, never rerun unrelated model tests here.
def function(text,signature):
 start=text.index(signature);at=text.index('{',start);end=at+1;depth=1
 while depth:depth+=(text[end]=='{')-(text[end]=='}');end+=1
 return text[start:end]
source=(D/'UsbDma.c').read_text();body=function(source,'BuildUsbTables (')
body='static EFI_STATUS '+body
fixture=(R/'tests/b5q-ufs/test-usb-firmware-dma.c').read_text();fixture=fixture[:fixture.index('int main(void)')]
fixture=fixture.replace('#define EfiReservedMemoryType 0','#define EfiReservedMemoryType 0\n#define EfiLoaderCode 1\n#define EfiLoaderData 2\n#define EFI_BUFFER_TOO_SMALL 5\n#define EFI_DEVICE_ERROR 7\n#define EFI_OUT_OF_RESOURCES 9\n#define EFI_ERROR(v) ((v)!=0)\n#define MIN(a,b) ((a)<(b)?(a):(b))\n#define MAX(a,b) ((a)>(b)?(a):(b))')
a=fixture.index('static struct { EFI_STATUS (*LocateProtocol)');b=fixture.index('#include "B5qUsbDmaLoader.h"',a)
fixture=fixture[:a]+r'''
#include <stdlib.h>
#define DEBUG(x) ((void)0)
#define DEBUG_ERROR 1
static EFI_MEMORY_DESCRIPTOR descriptors[3];
static EFI_STATUS getmap(UINTN *bytes,EFI_MEMORY_DESCRIPTOR *to,UINTN *key,UINTN *stride,UINT32 *version){
 *stride=sizeof(descriptors[0]);*key=1;*version=1;if(!to){*bytes=sizeof(descriptors);return EFI_BUFFER_TOO_SMALL;}
 assert(*bytes>=sizeof(descriptors));*bytes=sizeof(descriptors);memcpy(to,descriptors,*bytes);return 0;
}
static struct {EFI_STATUS(*LocateProtocol)(EFI_GUID*,void*,void**);__typeof__(&getmap)GetMemoryMap;}services={missing_protocol,getmap},*gBS=&services;
static void *AllocatePool(UINTN bytes){return malloc(bytes);}static void FreePool(void *p){free(p);}
'''+fixture[b:]
fixture+='static UINT8 mUsbMapBuf[32768] __attribute__((aligned(8)));\n#include "B5qReservedMemory.h"\n'+body+r'''
int main(void){
 for(unsigned i=0;i<sizeof(mB5qReservedRanges)/sizeof(mB5qReservedRanges[0]);i++){
  UINT64 a=mB5qReservedRanges[i].Base,b=mB5qReservedRanges[i].End;
  assert(!B5qDmaRangeAllowed(a,4096));assert(!B5qDmaRangeAllowed(b-4096,4096));assert(!B5qDmaRangeAllowed(a-4096,8192));
 }
 assert(!B5qDmaRangeAllowed(UINT64_MAX-4095,8192));assert(!B5qDmaRangeAllowed(0xc8000001,4096));
 assert(B5qDmaRangeAllowed(0xc8200000,128*1024*1024));
 static UINT64 pages[256*512];USB_DMA_TABLES table={pages,0xa0c000000,0,256};UINT64 mapped=0;
 descriptors[0]=(EFI_MEMORY_DESCRIPTOR){.Type=EfiConventionalMemory,.PhysicalStart=0xf3700000,.NumberOfPages=0x4400000/4096};
 descriptors[1]=(EFI_MEMORY_DESCRIPTOR){.Type=EfiLoaderCode,.PhysicalStart=0x88ba04000,.NumberOfPages=0x180000000/4096};
 descriptors[2]=(EFI_MEMORY_DESCRIPTOR){.Type=EfiReservedMemoryType,.PhysicalStart=table.PhysicalBase,.NumberOfPages=256};
 assert(!BuildUsbTables(&table,0x88ba04000,0x180000000,&mapped));unsigned shift;
 for(UINT64 a=0xf3700000;a<0xf7b00000;a+=4096){UINT64 e=walk(&table,a,&shift);assert((e!=0)==B5qDmaRangeAllowed(a,4096));}
 for(UINT64 a=0x88ba04000;a<0xa0ba04000;a+=4096){UINT64 e=walk(&table,a,&shift);assert((e!=0)==B5qDmaRangeAllowed(a,4096));}
 assert(!walk(&table,0xf3800000,&shift)&&!walk(&table,0x8b9a00000,&shift)&&!walk(&table,0x8bba00000,&shift));
 puts("PASS actual BuildUsbTables excludes allstockno-map from erroneous EFIConventional spans; all6GiBpages checked; overflow/alignment/forbiddenallocation rejection");
}
'''
with tempfile.TemporaryDirectory(prefix='b5q-reserve-usb-')as td:
 t=Path(td);(t/'test.c').write_text(fixture)
 subprocess.run(['cc','-std=gnu11','-O1','-g','-fsanitize=address,undefined','-I'+str(I),'-I'+str(D),'-I'+str(R/'UniXNU/drivers/DarwinBoot/DarwinBootPkg/Driver'),str(t/'test.c'),'-o',str(t/'test')],check=True);subprocess.run([str(t/'test')],check=True)
# Original fixed no-map bounds must be retained in the memory map HOBs or
# already allocated firmware regions; no uncovered gap may become conventional.
rows=json.loads((W/'stock-reserved-ranges.json').read_text())['ranges'];text=(I.parent/'Library/MemoryMapLib/MemoryMapLib.c').read_text();coverage=[]
for m in re.finditer(r'\{"[^"\n]+",\s*(0x[\da-fA-F]+)(?:ULL)?,\s*(0x[\da-fA-F]+)(?:ULL)?,\s*(AddMem|HobOnlyNoCacheSetting),[^\n]+',text):
 if ', Conv,'in m[0]or ',   Conv,'in m[0]:continue
 a=int(m[1],16);coverage.append((a,a+int(m[2],16)))
for row in rows:
 if not row['no_map']:continue
 remaining=[(row['base'],row['base']+row['bytes'])]
 for x,y in coverage:
  next=[]
  for a,b in remaining:
   if b<=x or y<=a:next.append((a,b))
   else:
    if a<x:next.append((a,x))
    if y<b:next.append((y,b))
  remaining=next
 assert not remaining,(row['name'],remaining)
for name in ['PcieDma.c','MediaDma.c']:
 s=(D/name).read_text();assert s.index('B5qDmaRangeAllowed(Base,Pages*EFI_PAGE_SIZE)')<s.index('ZeroMem(')
print('PASS every original fixed no-map span covered by EFI HOB/allocated reservation; PCIe/media validate fullallocation+tables beforezero')

pcie=function((D/'PcieDma.c').read_text(),'STATIC EFI_STATUS AllocatePoolPages(')
pre=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#define STATIC static
#define CONST const
#define VOID void
#define OUT
#define EFIAPI
#define STATIC_ASSERT static_assert
#define TRUE true
#define FALSE false
#define EFI_PAGE_SIZE 4096
#define AllocateMaxAddress 1
#define EfiReservedMemoryType 0
#define EFI_ERROR(v) ((v)!=0)
#define EFI_SUCCESS 0
#define EFI_UNSUPPORTED 3
#define ALIGN_VALUE(v,a) (((v)+((a)-1))&~((a)-1))
using UINT8=uint8_t;using UINT16=uint16_t;using UINT32=uint32_t;using UINT64=uint64_t;using UINTN=uintptr_t;using EFI_PHYSICAL_ADDRESS=uint64_t;using EFI_STATUS=uint64_t;using BOOLEAN=bool;
#include "B5qPcieDma.h"
#include "B5qReservedMemory.h"
B5Q_PCIE_DMA_RESULT mResult{};UINT64 next;unsigned clears,frees;
static EFI_STATUS allocate(unsigned,unsigned,UINTN,UINT64 *p){*p=next;return 0;}
static EFI_STATUS release(UINT64,UINTN){frees++;return 0;}
struct{decltype(&allocate)AllocatePages;decltype(&release)FreePages;}services={allocate,release},*gBS=&services;
void clear(void *p,UINTN n){assert(B5qDmaRangeAllowed((UINT64)p,n));clears++;}
#define ZeroMem clear
HELPER
int main(){for(auto range:mB5qReservedRanges){if(range.Base>0xffffffff)continue;next=range.Base;clears=frees=0;
 assert(AllocatePoolPages()==EFI_UNSUPPORTED&&clears==0&&frees==1);}
 next=0xc8010000;clears=frees=0;assert(!AllocatePoolPages()&&clears==1&&mResult.PoolBase==0xc8400000);
 puts("PASS actual PCIe allocation rejects all lowreserved starts beforezero, frees unsafeallocation, safe32MiBpool accepted");}
'''.replace('HELPER',pcie)
with tempfile.TemporaryDirectory(prefix='b5q-pcie-allocation-')as td:
 t=Path(td);(t/'test.cpp').write_text(pre);subprocess.run(['c++','-std=c++17','-O1','-g','-fsanitize=address,undefined','-I'+str(I),str(t/'test.cpp'),'-o',str(t/'test')],check=True);subprocess.run([str(t/'test')],check=True)
