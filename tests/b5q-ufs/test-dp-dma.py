#!/usr/bin/env python3
"""Exercise real EFI GOP tail producer and shared XNU range/mode bounds."""
from pathlib import Path
import subprocess,tempfile
R=Path(__file__).resolve().parents[2]
s=(R/'uefi-b5q/Platforms/Samsung/b5qPkg/Drivers/B5qHandoffDxe/DpDma.c').read_text()
s='\n'.join(v for v in s.splitlines()if not v.startswith('#include'))
prefix=r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <initializer_list>
#define STATIC static
#define CONST const
#define VOID void
#define EFIAPI
#define STATIC_ASSERT static_assert
#define TRUE true
#define FALSE false
#define EFI_ERROR(x) ((x)!=0)
#define EFI_SUCCESS 0
#define EFI_NOT_STARTED 19
#define EFI_NOT_FOUND 14
#define EFI_COMPROMISED_DATA 33
#define EFI_BAD_BUFFER_SIZE 4
#define DEBUG(x) ((void)0)
typedef uint32_t UINT32;typedef uint16_t UINT16;typedef uint8_t UINT8;typedef uint64_t UINT64,UINTN,EFI_STATUS;typedef bool BOOLEAN;typedef void *EFI_HANDLE;
struct EFI_GUID{UINT32 a;UINT16 b,c;UINT8 d[8];};
#include "B5qDpDma.h"
#include "B5qDpModes.h"
constexpr unsigned PixelBltOnly=3;
struct EFI_GRAPHICS_OUTPUT_MODE_INFORMATION {unsigned HorizontalResolution=1080,VerticalResolution=2640,PixelFormat=1,PixelsPerScanLine=1080;};
struct GopMode{EFI_GRAPHICS_OUTPUT_MODE_INFORMATION *Info;UINT64 FrameBufferBase,FrameBufferSize;};
struct EFI_GRAPHICS_OUTPUT_PROTOCOL{GopMode *Mode;};
EFI_GUID gEfiGraphicsOutputProtocolGuid{};EFI_GRAPHICS_OUTPUT_PROTOCOL gop;
unsigned failure=0;void ZeroMem(void *p,size_t n){memset(p,0,n);}
EFI_STATUS locate(EFI_GUID *,void *,void **p){if(failure)return EFI_NOT_FOUND;*p=&gop;return 0;}
EFI_STATUS install(EFI_HANDLE *,EFI_GUID *,void *,void *){return 0;}
struct Services{decltype(&locate)LocateProtocol;decltype(&install)InstallMultipleProtocolInterfaces;}services{locate,install},*gBS=&services;
'''
test=r'''
int main(){unsigned cases=0;EFI_GRAPHICS_OUTPUT_MODE_INFORMATION info;GopMode mode{&info,0xb8000000,1080*2640*4};gop.Mode=&mode;
 B5Q_DP_DMA_STATE state{};PrepareDp(&state);assert(!state.PrepareStatus&&state.PoolBase==0xb8c00000&&state.PoolBytes==0x1f00000&&state.PrimaryEnd==0xb8ae0600);state.RetentionStatus=0;assert(B5qDpPoolValid(&state));cases++;
 for(unsigned bad=0;bad<11;bad++){
  auto old=mode;auto orig=info;failure=0;
  if(bad==0)failure=1;if(bad==1)mode.FrameBufferBase=0xb7ffffff;if(bad==2)mode.FrameBufferSize=UINT64_MAX;
  if(bad==3)mode.FrameBufferSize=0x2100000;if(bad==4)mode.FrameBufferBase=0xbab00000;
  if(bad==5)mode.FrameBufferSize=1;if(bad==6)info.PixelsPerScanLine=1079;if(bad==7)info.VerticalResolution=0;
  if(bad==8)info.PixelFormat=PixelBltOnly;if(bad==9)mode.Info=nullptr;if(bad==10)gop.Mode=nullptr;
  PrepareDp(&state);assert(state.PrepareStatus&&!state.PrimaryChecked&&!state.PoolBytes);mode=old;info=orig;gop.Mode=&mode;cases++;
 }
 failure=0;
 for(uint64_t size=0x1000;size<0x2b00000;size+=0x1000){
  B5Q_DP_DMA_STATE st{};bool ok=B5qDpPool(&st,0xb8000000,size,0xb8000000+size);
  if(ok){assert(st.PoolBase>=0xb8000000+size&&!(st.PoolBase&0x1fffff)&&st.PoolBase+st.PoolBytes==0xbab00000&&st.PoolBytes>=0x1000000);assert(B5qDpPoolValid(&st));}
  cases++;
 }
 for(unsigned field=0;field<10;field++){
  PrepareDp(&state);state.RetentionStatus=0;assert(B5qDpPoolValid(&state));
  if(field==0)state.PrimaryChecked=0;if(field==1)state.SidMask^=1;if(field==2)state.PoolBase+=4096;
  if(field==3)state.PoolBytes+=4096;if(field==4)state.Alignment=4096;if(field==5)state.PrepareStatus=1;
  if(field==6)state.RetentionStatus=1;if(field==7)state.Reserved=1;if(field==8)state.PrimaryEnd--;if(field==9)state.FrameBufferBytes=UINT64_MAX;
  assert(!B5qDpPoolValid(&state));cases++;
 }
 B5qDp::Modes modes;assert(modes.advertisedVic(16)&&modes.advertisedVic(97));assert(modes.count==2);
 assert(modes.fitPool(0x1f00000)==1&&modes.values[0].width==1920);
 B5qDp::Mode qhd{241500,2560,1440,160,41,48,32,3,5,true,false};assert(modes.add(qhd));assert(modes.fitPool(0x1f00000)==2);
 assert(B5qDp::Modes::scanoutSlot(qhd)*2<=0x1f00000);assert(modes.fitPool(16*1024*1024)==1);assert(modes.fitPool(1)==0);
 puts("PASS actual EFI GOP producer and XNU tail contract:11029 range/fault/overlap/retention cases; EDID1080p/1440p fit and4K rejected ASanUBSan");
}
'''
with tempfile.TemporaryDirectory(prefix='b5q-dp-dma-')as td:
 t=Path(td);(t/'test.cpp').write_text(prefix+s+test)
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-Wno-missing-field-initializers','-O1','-g','-fsanitize=address,undefined','-I'+str(R/'uefi-b5q/Platforms/Samsung/b5qPkg/Include'),'-I'+str(R/'UniXNU-b5q/package'),str(t/'test.cpp'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test')],check=True)
