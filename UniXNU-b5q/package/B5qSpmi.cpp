// SPDX-License-Identifier: BSD-2-Clause-Patent
// b5q PM8550B SID7 peripheralFD; DT/source hashes in runtime-v21.json.
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceMemory.h>
#include "B5qSpmi.h"
extern "C" int b5q_usb_repeater_host(void) {
 IODeviceMemory *core=IODeviceMemory::withRange(0xc400000,0x3000),*cnfg=IODeviceMemory::withRange(0xc42d000,0x4000);
 IOMemoryMap *cm=core?core->map(kIOMapAnywhere|kIOMapInhibitCache):nullptr,*cf=cnfg?cnfg->map(kIOMapAnywhere|kIOMapInhibitCache):nullptr;
 OSSafeReleaseNULL(core);OSSafeReleaseNULL(cnfg);int rc=-1,apid=-1;uint32_t version=0,count=0;IOMemoryMap *channel=nullptr;
 if(cm&&cf) {
  auto *c=reinterpret_cast<volatile uint32_t *>(cm->getVirtualAddress());auto *owners=reinterpret_cast<volatile uint32_t *>(cf->getVirtualAddress());
  version=c[0];count=c[1]&0x7ff;
  if(version>=BR_VERSION_V7_MIN&&version<BR_VERSION_V8_MIN&&count&&count<=1024) {
   for(unsigned i=0;i<count;++i)if(((c[(0x2000+4*i)/4]>>8)&0xfff)==0x7fd && (owners[i]&7)==0){apid=int(i);break;}
   if(apid>=0) {
    IODeviceMemory *memory=IODeviceMemory::withRange(0xc500000+uint64_t(apid)*0x1000,0x1000);
    channel=memory?memory->map(kIOMapAnywhere|kIOMapInhibitCache):nullptr;OSSafeReleaseNULL(memory);
    if(channel) {
     auto *ch=reinterpret_cast<volatile uint32_t *>(channel->getVirtualAddress());
     ch[BR_WDATA0/4]=1u<<6;__asm__ volatile("dsb sy":::"memory");ch[BR_CMD/4]=br_cmd(BR_OP_EXT_WRITEL,0x55,0);rc=br_wait(ch);
     if(!rc){ch[BR_WDATA0/4]=1u<<6;__asm__ volatile("dsb sy":::"memory");ch[BR_CMD/4]=br_cmd(BR_OP_EXT_WRITEL,0x56,0);rc=br_wait(ch);}
    }
   } else rc=-2;
  } else rc=-3;
 }
 IOLog("B5qUsb: stage=repeater-host ver=%08x apids=%u ppid=7fd apid=%d rc=%d\n",version,count,apid,rc);
 OSSafeReleaseNULL(channel);OSSafeReleaseNULL(cm);OSSafeReleaseNULL(cf);return rc;
}
