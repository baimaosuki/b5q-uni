// SPDX-License-Identifier: BSD-2-Clause-Patent
// Reuse the qualified USB HAL table/retention fixture; execute new production
// PCIe helpers as well as the original USB tests to catch shared regressions.
#define main qualified_usb_main
#include "test-usb-firmware-dma.c"
#undef main
#define AsciiStrnCmp strncmp
#define CompareMem memcmp
#define ALIGN_VALUE(v,a) (((v)+((a)-1))&~((a)-1))
#define EFI_ERROR(v) ((v)!=0)
static UINT32 ReadUnaligned32(const UINT32 *p){UINT32 v;memcpy(&v,p,4);return v;}
static UINTN AsciiStrnLenS(const char *p,UINTN n){UINTN i=0;while(i<n && p[i])i++;return i;}
#include "B5qPcieDmaLoader.h"
#include "PcieDmaTables.h"
static unsigned pcie_locates;
static EFI_STATUS missing_pcie(EFI_GUID *guid,void *unused,void **out) {
  assert(guid->Data1==0x610234d8 && unused==NULL && *out==NULL);pcie_locates++;return 14;
}
static void property(UINT8 *tree,UINTN *at,const char *name,const void *value,UINT32 length) {
  memset(tree+*at,0,36);memcpy(tree+*at,name,strlen(name));memcpy(tree+*at+32,&length,4);*at+=36;
  if(value)memcpy(tree+*at,value,length);else memset(tree+*at,0,length);*at=ALIGN_VALUE(*at+length,4);
}
int main(void) {
  assert(!qualified_usb_main());
  UINT64 pages[32*512];
  for(UINT64 base=0x80000000;base<0xfe000000;base+=0x04000000) {
    memset(pages,0,sizeof(pages));USB_DMA_TABLES t={pages,0xffe00000,0,32};
    assert(B5qPcieMapPool(&t,0xa0000000,base,0x02000000));
    for(UINT64 off=0;off<0x02000000;off+=4096) {
      unsigned shift=0;UINT64 e=walk(&t,0xa0000000+off,&shift);
      assert(shift==21 && (e&0x708)==0x708);
      assert(((e&USB_DMA_PA_MASK)+((0xa0000000+off)&((1ULL<<shift)-1)))==base+off);
    }
    unsigned shift=0;assert(!walk(&t,0x9ffff000,&shift));assert(!walk(&t,0xa2000000,&shift));
    assert(B5qPcieMapMsi(&t));
    UINT64 msi=walk(&t,0xaffff040,&shift);
    assert(shift==12 && (msi&USB_DMA_PA_MASK)==0x17110000 && (msi&0x1c)==0);
    assert(!B5qPcieMapMsi(&t));assert(!walk(&t,0xafffe000,&shift));
    assert(!B5qPcieMapPool(&t,0xa0000000,base,0x02000000)); // no overwrite
  }
  memset(pages,0,sizeof(pages));USB_DMA_TABLES t={pages,0xffe00000,0,32};
  assert(!B5qPcieMapPool(&t,0xa0000000,0x100000000,0x2000000));
  assert(!B5qPcieMapPool(&t,0xa0000000,0x80000001,0x2000000));
  assert(!B5qPcieMapPool(&t,0xfffff000,0x80000000,8192));
  assert(!B5qPcieMapPool(&t,0xa0000000,0x80000000,UINT64_MAX-4095));
  assert(!B5qPcieMapPool(&t,0xa0000000,0x80000000,0));
  for(const char **p=(const char*[]){"wifi=1","x=1 wifi=5 x=0","wifi=0 wifi=5",NULL};*p;p++)assert(PcieArgEnabled(*p));
  for(const char **p=(const char*[]){"wifi=0","wifi=1 wifi=0","wifi=-1","wifi=bad","nowifi=1","wifi=",NULL};*p;p++)assert(!PcieArgEnabled(*p));
  services.LocateProtocol=missing_pcie;
  B5Q_PCIE_DMA_RESULT result;GetPcieDmaResult("wifi=0",&result);assert(!pcie_locates && result.PrepareStatus==EFI_NOT_STARTED);
  GetPcieDmaResult("wifi=5",&result);assert(pcie_locates==1 && result.PrepareStatus==14 && result.Create==UINT32_MAX);
  UINT8 tree[512]={0};UINTN at=0;UINT32 header[2]={1,1};memcpy(tree,header,8);at=8;
  property(tree,&at,"name","/",2);UINT32 chosen[2]={3,0};memcpy(tree+at,chosen,8);at+=8;
  property(tree,&at,"name","chosen",7);property(tree,&at,"b5q-pcie-dma-ready",NULL,4);
  property(tree,&at,"b5q-pcie-dma-state",NULL,88);UINTN length=at,cursor=0;
  B5Q_PCIE_DMA_ADT adt={MAX_UINTN,MAX_UINTN};assert(FindPcieDmaNode(tree,length,&cursor,0,3,&adt) && cursor==length);
  EFI_MEMORY_DESCRIPTOR map[2]={{.Type=EfiReservedMemoryType,.PhysicalStart=0xc0000000,.NumberOfPages=8192},
    {.Type=EfiReservedMemoryType,.PhysicalStart=0xffe00000,.NumberOfPages=32}};
  result=(B5Q_PCIE_DMA_RESULT){.Version=2,.SidMask=0x007f1400,.PoolBase=0xc0000000,.PoolBytes=0x2000000,
    .Iova=0xa0000000,.TableBase=0xffe00000,.TableBytes=32*4096};
  WritePcieDmaResult(tree,&adt,&result,map,sizeof(map),sizeof(map[0]),0x8c0000000ULL,0x180000000ULL,false);
  UINT32 ready=0;memcpy(&ready,tree+adt.Ready,4);assert(ready==1);
  map[0].Type=EfiBootServicesData;
  WritePcieDmaResult(tree,&adt,&result,map,sizeof(map),sizeof(map[0]),0x8c0000000ULL,0x180000000ULL,false);
  memcpy(&ready,tree+adt.Ready,4);assert(!ready);
  map[0].Type=EfiReservedMemoryType;
  for(unsigned i=0;i<4;i++) {
    B5Q_PCIE_DMA_RESULT bad=result;
    if(i==0)bad.Create=1;else if(i==1)bad.Configure=1;else if(i==2)bad.Attach=1;else bad.Map=1;
    WritePcieDmaResult(tree,&adt,&bad,map,sizeof(map),sizeof(map[0]),0x8c0000000ULL,0x180000000ULL,false);
    memcpy(&ready,tree+adt.Ready,4);assert(!ready);
  }
  memset(tree+adt.Ready,0,4);memset(tree+adt.State,0,88);
  for(UINTN truncated=0;truncated<length;truncated++) {
    cursor=0;B5Q_PCIE_DMA_ADT bad={MAX_UINTN,MAX_UINTN};assert(!FindPcieDmaNode(tree,truncated,&cursor,0,3,&bad));
  }
  puts("PASS production PCIe DMA tables/all32MiB pages/attributes/bounds; loader option, ADT truncation, HAL failure, retained pool/table gate; USB baseline rerun");
}
