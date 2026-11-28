#!/usr/bin/env python3
"""Walk the production USB tables against the actual Darwin outside selector."""
from pathlib import Path
import subprocess,tempfile
R=Path(__file__).resolve().parents[2]
# Reuse the exact existing EFI fixture/extractor, without executing its tests.
s=(R/'tests/b5q-ufs/test-v33b-reservations.py').read_text()
ns={ '__file__':str(R/'tests/b5q-ufs/test-v33b-reservations.py') }
exec(compile(s[:s.index("fixture+='static UINT8 mUsbMapBuf")],'<existing-EFI-fixture>','exec'),ns)
fixture=ns['fixture'].replace('descriptors[3]','descriptors[7]')
fixture+='static UINT8 mUsbMapBuf[32768] __attribute__((aligned(8)));\n#include "B5qReservedMemory.h"\n'+ns['body']+r'''
static UINT64 ReadUnaligned64(const UINT64 *p){UINT64 n;memcpy(&n,p,8);return n;}
static void WriteUnaligned64(UINT64 *p,UINT64 n){memcpy(p,&n,8);}
#include "MemoryWindow.h"
static void check(USB_DMA_TABLES *t,UINT64 pa){
 unsigned shift=0;UINT64 pte=walk(t,pa,&shift),mask=((UINT64)1<<shift)-1;
 assert(pte);assert((pte&(1ULL<<6))!=0);assert(((pte>>2)&7)==2);
 assert(((pte>>8)&3)==3);assert(((pte>>10)&1)==1);
 assert(((pte&USB_DMA_PA_MASK&~mask)|(pa&mask))==pa);
}
int main(void){
 static UINT64 pages[256*512];USB_DMA_TABLES table={pages,0xa0c000000,0,256};UINT64 mapped=0;
 descriptors[0]=(EFI_MEMORY_DESCRIPTOR){.Type=EfiConventionalMemory,.PhysicalStart=0xc7cc0000,.NumberOfPages=(0xd4d00000-0xc7cc0000)/4096};
 descriptors[1]=(EFI_MEMORY_DESCRIPTOR){.Type=EfiLoaderCode,.PhysicalStart=0x88ba04000,.NumberOfPages=0x180000000/4096};
 descriptors[2]=(EFI_MEMORY_DESCRIPTOR){.Type=EfiReservedMemoryType,.PhysicalStart=table.PhysicalBase,.NumberOfPages=256};
 // Additional discontiguous safe outside RAM plus a reservation: selector must
 // exclude the latter and every selected page must have an identity leaf.
 descriptors[3]=(EFI_MEMORY_DESCRIPTOR){.Type=EfiConventionalMemory,.PhysicalStart=0xf7b00000,.NumberOfPages=0x100000/4096};
 descriptors[4]=(EFI_MEMORY_DESCRIPTOR){.Type=EfiReservedMemoryType,.PhysicalStart=0xf7c00000,.NumberOfPages=0x100000/4096};
 assert(!BuildUsbTables(&table,0x88ba04000,0x180000000,&mapped));
 check(&table,0xcb14d000);check(&table,0x9838b1000);
 UINT8 outside[8*16]={};UINT64 bytes=0;
 UINTN count=DarwinOutsideRanges(descriptors,sizeof(descriptors),sizeof(descriptors[0]),0x88ba04000,0x180000000,65536,1048576,outside,8,&bytes);
 assert(count==2&&DarwinRangeBase(outside,0)==0xc7cc0000&&DarwinRangeSize(outside,0)==0xd4d00000-0xc7cc0000);
 for(UINTN i=0;i<count;i++)for(UINT64 pa=DarwinRangeBase(outside,i),end=pa+DarwinRangeSize(outside,i);pa<end;pa+=4096)check(&table,pa);
 for(UINT64 pa=0x88ba04000;pa<0xa0ba04000;pa+=4096){
  unsigned shift;UINT64 pte=walk(&table,pa,&shift);
  if(B5qDmaRangeAllowed(pa,4096))check(&table,pa);else assert(!pte);
 }
 unsigned shift;assert(!walk(&table,table.PhysicalBase,&shift));assert(!walk(&table,0xf7c00000,&shift));
 // Once other domains reserve their pools, none of those pages may enter
 // USB's stage1 domain even when they were previously low conventionalRAM.
 memset(pages,0,sizeof(pages));table.Used=0;mapped=0;
 descriptors[0].NumberOfPages=(0xca000000-0xc7cc0000)/4096;
 descriptors[3]=(EFI_MEMORY_DESCRIPTOR){.Type=EfiReservedMemoryType,.PhysicalStart=0xca000000,.NumberOfPages=0x200000/4096};
 descriptors[4]=(EFI_MEMORY_DESCRIPTOR){.Type=EfiConventionalMemory,.PhysicalStart=0xca200000,.NumberOfPages=(0xd4d00000-0xca200000)/4096};
 descriptors[5]=(EFI_MEMORY_DESCRIPTOR){.Type=EfiReservedMemoryType,.PhysicalStart=0xd5000000,.NumberOfPages=0x8000000/4096};
 descriptors[6]=(EFI_MEMORY_DESCRIPTOR){.Type=EfiBootServicesData,.PhysicalStart=0xe0000000,.NumberOfPages=0x20000/4096};
 assert(!BuildUsbTables(&table,0x88ba04000,0x180000000,&mapped));
 for(UINT64 pa=0xca000000;pa<0xca200000;pa+=4096)assert(!walk(&table,pa,&shift));
 for(UINT64 pa=0xd5000000;pa<0xdd000000;pa+=4096)assert(!walk(&table,pa,&shift));
 assert(!walk(&table,0xe0000000,&shift));check(&table,0xcb14d000);check(&table,0x9838b1000);
 puts("PASS independentaudio/video pools andBootServices inputpages remainunmapped inUSBdomain");
 puts("PASS production BuildUsbTables + DarwinOutsideRanges:cb14d000/9838b1000 AP01/Attr2/SH3/AF1/identity; every outside4K +6GiBowned page walked, originalreserved excluded, tablepool retained");
}
'''
for name in ['UsbDma.c','PcieDma.c','MediaDma.c']:
 source=(ns['D']/name).read_text()
 assert '0x00c01027'in source and '0x00803510'in source and '0x00c000e7'not in source and '0x00802010'not in source
 assert not (0x00c01027&((1<<7)|(1<<6))) and 0x00c01027&(1<<12)
 assert 'WriteBackDataCacheRange'in source and 'dsb sy'in source
with tempfile.TemporaryDirectory(prefix='b5q-v33d-table-walk-')as td:
 t=Path(td);(t/'test.c').write_text(fixture)
 subprocess.run(['cc','-std=gnu11','-O1','-g','-fsanitize=address,undefined','-I'+str(ns['I']),'-I'+str(ns['D']),'-I'+str(R/'UniXNU/drivers/DarwinBoot/DarwinBootPkg/Driver'),str(t/'test.c'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test')],check=True)
print('PASS USB/PCIe/Audio/Video configurations: SCTLRc01027 no-stall/ASIDPNE; TCR803510 WB-IS; clean/dsb preserved')
