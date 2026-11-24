#!/usr/bin/env python3
"""Run actual DP ADT parser, EFI selection and retention gate with old gates."""
from pathlib import Path
import subprocess,tempfile
R=Path(__file__).resolve().parents[2]
s=(R/'tests/b5q-ufs/test-media-loader.c').read_text().replace('int main(void)','int qualified_media_main(void)')
s+=r'''
#include "B5qDpDmaLoader.h"
static unsigned dpPrepares;
static void dpPrepare(B5Q_DP_DMA_STATE *s){dpPrepares++;assert(B5qDpPool(s,0xb8000000,1080*2640*4,0xb8000000+1080*2640*4));s->PrepareStatus=0;}
static B5Q_DP_DMA_PROTOCOL dpProtocol={1,dpPrepare};
static EFI_STATUS dpLocate(EFI_GUID *guid,void *unused,void **out){assert(guid->Data1==0x16d34ec5&&!unused);*out=&dpProtocol;return 0;}
int main(void){assert(!qualified_media_main());services.LocateProtocol=dpLocate;
 B5Q_DP_DMA_STATE state;GetDpDmaResult("usb=1 b5q-dp=0",&state);assert(!dpPrepares);
 GetDpDmaResult("b5q-dp=1 b5q-dp=bad",&state);assert(!dpPrepares);
 GetDpDmaResult("usb=1 b5q-dp=1",&state);assert(dpPrepares==1&&!state.PrepareStatus);
 UINT8 tree[1024]={0};UINTN at=8;UINT32 root[2]={1,1};memcpy(tree,root,8);prop(tree,&at,"name","/",2);
 UINT32 chosen[2]={3,0};memcpy(tree+at,chosen,8);at+=8;prop(tree,&at,"name","chosen",7);
 prop(tree,&at,"b5q-dp-dma-ready",NULL,4);prop(tree,&at,"b5q-dp-dma-state",NULL,80);
 UINTN size=at,cursor=0;B5Q_DP_DMA_ADT adt={MAX_UINTN,MAX_UINTN};
 assert(FindDpDmaNode(tree,size,&cursor,0,3,&adt)&&cursor==size);
 for(UINTN n=0;n<size;n++){cursor=0;B5Q_DP_DMA_ADT bad={MAX_UINTN,MAX_UINTN};assert(!FindDpDmaNode(tree,n,&cursor,0,3,&bad));}
 EFI_MEMORY_DESCRIPTOR map={.Type=EfiReservedMemoryType,.PhysicalStart=0xb8000000,.NumberOfPages=0x2b00000/4096};
 WriteDpDmaResult(tree,&adt,&state,&map,sizeof map,sizeof map,0x8c0000000ULL,0x180000000ULL);
 UINT32 flag;memcpy(&flag,tree+adt.Ready,4);assert(flag==1);B5Q_DP_DMA_STATE received;memcpy(&received,tree+adt.State,sizeof received);assert(B5qDpPoolValid(&received));
 map.Type=EfiBootServicesData;WriteDpDmaResult(tree,&adt,&state,&map,sizeof map,sizeof map,0x8c0000000ULL,0x180000000ULL);
 memcpy(&flag,tree+adt.Ready,4);assert(!flag);map.Type=EfiReservedMemoryType;
 WriteDpDmaResult(tree,&adt,&state,&map,sizeof map,sizeof map,state.PoolBase,0x180000000ULL);memcpy(&flag,tree+adt.Ready,4);assert(!flag);
 state.PoolBase--;WriteDpDmaResult(tree,&adt,&state,&map,sizeof map,sizeof map,0x8c0000000ULL,0x180000000ULL);memcpy(&flag,tree+adt.Ready,4);assert(!flag);
 puts("PASS actual DP loader selection/ADTtruncation/state/EFIreserved/owned-window gates; all USB/PCIe/media retention regressions preserved");
}
'''
with tempfile.TemporaryDirectory(prefix='b5q-dp-loader-')as td:
 t=Path(td);(t/'test.c').write_text(s)
 subprocess.run(['cc','-std=c11','-O1','-g','-fsanitize=address,undefined','-I'+str(R/'tests/b5q-ufs'),'-I'+str(R/'UniXNU/drivers/DarwinBoot/DarwinBootPkg/Driver'),'-I'+str(R/'uefi-b5q/Platforms/Samsung/b5qPkg/Drivers/B5qHandoffDxe'),str(t/'test.c'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test')],check=True)
