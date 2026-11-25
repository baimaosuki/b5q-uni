#!/usr/bin/env python3
"""Execute USB firmware page tables with boot-services RAM and fragment bounds."""
from pathlib import Path
import hashlib,json,os,subprocess,tempfile
R=Path(__file__).resolve().parents[2];W=Path(os.environ.get('B5Q_GATE_WORK',R/'artifacts/b5q-v33d-review4'));W.mkdir(parents=True,exist_ok=True)
s=(R/'tests/b5q-ufs/test-v33b-reservations.py').read_text();ns={'__file__':str(R/'tests/b5q-ufs/test-v33b-reservations.py')};exec(compile(s[:s.index("fixture+='static UINT8 mUsbMapBuf")],'<production-EFI-fixture>','exec'),ns)
fixture=ns['fixture'].replace('static EFI_MEMORY_DESCRIPTOR descriptors[3];','static EFI_MEMORY_DESCRIPTOR descriptors[820];\nstatic UINTN descriptorCount=0;')
fixture=fixture.replace('sizeof(descriptors)','(descriptorCount*sizeof(descriptors[0]))')
fixture=fixture.replace('assert(*bytes>=(descriptorCount*sizeof(descriptors[0])));','if(*bytes<(descriptorCount*sizeof(descriptors[0]))){*bytes=descriptorCount*sizeof(descriptors[0]);return EFI_BUFFER_TOO_SMALL;}')
# Original full map is unavailable: this fixture reuses only independently
# qualified original board reservation bounds and the owned/outside ranges
# modeled from actual b5q FDT/UEFI inputs. No claim that it is the phone EFI map.
model=json.loads((R/'artifacts/b5q-batch2-work/memory-model.json').read_text())
low=[(int(x['base'],16),int(x['bytes']))for x in model['model_low_outside_ranges']]
array=','.join('{0x%xULL,0x%xULL}'%(a,n)for a,n in low)
body=fixture+'static UINT8 mUsbMapBuf[32768] __attribute__((aligned(8)));\n#include "B5qReservedMemory.h"\n'+ns['body']+r'''
static UINT64 pages[USB_DMA_TABLE_PAGES*512];
static void add(UINT32 type,UINT64 a,UINT64 bytes){assert(descriptorCount<820&&!(a&4095)&&!(bytes&4095));descriptors[descriptorCount++]=(EFI_MEMORY_DESCRIPTOR){.Type=type,.PhysicalStart=a,.NumberOfPages=bytes/4096};}
static void check(USB_DMA_TABLES *t,UINT64 pa){unsigned shift=0;UINT64 pte=walk(t,pa,&shift),mask=((UINT64)1<<shift)-1;
 assert(pte&&((pte>>6)&3)==1&&((pte>>2)&7)==2&&((pte>>8)&3)==3&&(pte&(1u<<10)));
 assert(((pte&USB_DMA_PA_MASK&~mask)|(pa&mask))==pa);}
static void reset(USB_DMA_TABLES *t,UINTN capacity){memset(pages,0,sizeof(pages));*t=(USB_DMA_TABLES){pages,0xb00000000,0,capacity};descriptorCount=0;memset(descriptors,0,sizeof(descriptors));}
int main(void){USB_DMA_TABLES table;UINT64 mapped;unsigned shift;
 reset(&table,USB_DMA_TABLE_PAGES);UINT64 low[][2]={LOW};
 for(unsigned i=0;i<sizeof(low)/sizeof(low[0]);i++){
  UINT64 a=low[i][0],n=low[i][1],split=(n/2)&~4095ULL;
  add(i&1?EfiBootServicesCode:EfiBootServicesData,a,split);add(i&1?EfiLoaderData:EfiLoaderCode,a+split,n-split);
 }
 add(EfiLoaderCode,0x88ba04000,0x180000000);add(EfiReservedMemoryType,table.PhysicalBase,USB_DMA_RESERVED_BYTES);
 add(EfiBootServicesData,0xb7f00000,0x2d00000); // crosses original no-map: subtract it
 add(5,0xf80000000,0x10000); // RuntimeServicesCode
 add(6,0xf81000000,0x10000); // RuntimeServicesData
 add(11,0xf82000000,0x10000); // MMIO
 // Independent firmware-domain pool is reserved rather than stock DT no-map.
 add(EfiReservedMemoryType,0xf83000000,0x8000000);
 mapped=0;assert(!BuildUsbTables(&table,0x88ba04000,0x180000000,&mapped));UINTN boardPages=table.Used;
 for(unsigned i=0;i<descriptorCount;i++){
  const EFI_MEMORY_DESCRIPTOR *d=descriptors+i;
  if(d->Type==EfiReservedMemoryType||d->Type==5||d->Type==6||d->Type==11)continue;
  for(UINT64 p=d->PhysicalStart;p<d->PhysicalStart+d->NumberOfPages*4096;p+=4096){
   if(B5qDmaRangeAllowed(p,4096))check(&table,p);else assert(!walk(&table,p,&shift));
  }
 }
 assert(!walk(&table,table.PhysicalBase,&shift));assert(!walk(&table,0xf80000000,&shift));assert(!walk(&table,0xf81000000,&shift));assert(!walk(&table,0xf82000000,&shift));assert(!walk(&table,0xf83000000,&shift));
 // Most fragmented disjoint descriptors that fit32768bytes: each straddles
 // one2MiB boundary, forcing two L3 pages. Both bootservices types alternate.
 reset(&table,USB_DMA_TABLE_PAGES);add(EfiLoaderCode,0x88ba04000,4096);add(EfiReservedMemoryType,table.PhysicalBase,USB_DMA_RESERVED_BYTES);
 for(unsigned i=0;i<817;i++)add(i&1?EfiBootServicesCode:EfiBootServicesData,0x100000000ULL+(UINT64)i*0x400000+0x1ff000,8192);
 assert(descriptorCount==819);mapped=0;assert(!BuildUsbTables(&table,0x88ba04000,4096,&mapped));UINTN fragmented=table.Used;
 assert(fragmented>256&&fragmented<=USB_DMA_TABLE_PAGES);
 for(unsigned i=2;i<descriptorCount;i++){check(&table,descriptors[i].PhysicalStart);check(&table,descriptors[i].PhysicalStart+4096);}
 const UINTN bound=66+2*(sizeof(mUsbMapBuf)/sizeof(EFI_MEMORY_DESCRIPTOR)+sizeof(mB5qReservedRanges)/sizeof(mB5qReservedRanges[0]));assert(bound<=USB_DMA_TABLE_PAGES&&fragmented<=bound);
 // Demonstrate the old256page limitation and guard exhaustion (no OOB).
 memset(pages,0,sizeof(pages));table.Used=0;table.Capacity=256;mapped=0;
 assert(BuildUsbTables(&table,0x88ba04000,4096,&mapped)==EFI_COMPROMISED_DATA&&table.Used==256);
 table.Used=0;table.Capacity=USB_DMA_TABLE_PAGES;descriptorCount=820;mapped=0;
 assert(BuildUsbTables(&table,0x88ba04000,4096,&mapped)==EFI_BUFFER_TOO_SMALL&&!table.Used&&!mapped);
 // OwnsHead and Retained gates remain mandatory after expanding memorytypes.
 reset(&table,USB_DMA_TABLE_PAGES);add(EfiBootServicesData,0x88ba04000,4096);add(EfiReservedMemoryType,table.PhysicalBase,USB_DMA_RESERVED_BYTES);mapped=0;
 assert(BuildUsbTables(&table,0x88ba04000,4096,&mapped)==EFI_COMPROMISED_DATA);
 reset(&table,USB_DMA_TABLE_PAGES);add(EfiLoaderData,0x88ba04000,4096);mapped=0;assert(BuildUsbTables(&table,0x88ba04000,4096,&mapped)==EFI_COMPROMISED_DATA);
 printf("PASS actual BuildUsbTables:boot/loader RAMoutsideowned,original19reservedspans+independentpool+runtimeMMIO excluded; board-rangemodel=%zu pages;819fragmentdescriptors=%zu pages,bound=%zu,capacity=%u;old256exhausts safely;staticmapoverflow rejected;OwnsHead/Retained preserved\n",boardPages,fragmented,bound,USB_DMA_TABLE_PAGES);
}
'''.replace('LOW',array)
with tempfile.TemporaryDirectory(prefix='b5q-review4-reclaim-DMA-')as td:
 t=Path(td);p=t/'test.c';p.write_text(body);subprocess.run(['cc','-std=gnu11','-O1','-g','-fsanitize=address,undefined','-I'+str(ns['I']),'-I'+str(ns['D']),'-I'+str(R/'UniXNU/drivers/DarwinBoot/DarwinBootPkg/Driver'),str(p),'-o',str(t/'test')],check=True)
 output=subprocess.check_output([str(t/'test')],text=True);print(output,end='')
 (W/'dma-fragmentation.json').write_text(json.dumps(dict(passed=True,scope='Production tables with originalb5q reservedbounds and FDT/UEFI-derived modeled ranges; adversarial map is synthetic, not capturedEFI',model_input_sha256=hashlib.sha256((R/'artifacts/b5q-batch2-work/memory-model.json').read_bytes()).hexdigest(),output=output,hardware_verified=False),indent=2)+'\n')
