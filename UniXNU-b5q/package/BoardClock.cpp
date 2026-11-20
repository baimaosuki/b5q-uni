// SPDX-License-Identifier: BSD-2-Clause-Patent
// PMK8550 RTC read-only, b5q rtc@6100. Calendar offset stays in RAM.
// Uses the reference v7 observer protocol; no Xiaomi SDAM offset/reboot cells.
#include <IOKit/IOLib.h>
#include <IOKit/IODeviceMemory.h>
#include <pexpert/pexpert.h>
#include "BootResetCore.h"
extern "C" void armdt_platform_clock_register(int(*)(uint64_t*),void(*)(uint64_t)) __attribute__((weak_import));
extern "C" {volatile uint32_t native_board_clock[16];}
namespace {
IOMemoryMap *maps[3];br_arbiter arb={};volatile uint32_t *obs;int apid=-1;bool opened;uint64_t offset;volatile uint8_t busy;
volatile uint32_t *mapping(unsigned n,uint64_t base,uint64_t bytes) {
 auto *m=IODeviceMemory::withRange(base,bytes);maps[n]=m?m->map(kIOMapAnywhere|kIOMapInhibitCache):nullptr;OSSafeReleaseNULL(m);
 return maps[n]?reinterpret_cast<volatile uint32_t *>(maps[n]->getVirtualAddress()):nullptr;
}
bool open() {
 if(opened)return apid>=0;opened=true;arb.ee=0;
 arb.core=mapping(0,0xc400000,0x3000);arb.cnfg=mapping(1,0xc42d000,0x4000);if(!arb.core||!arb.cnfg)return false;
 unsigned count=arb.core[1]&0x7ff;uint32_t version=arb.core[0];
 if(version<BR_VERSION_V7_MIN||version>=BR_VERSION_V8_MIN||!count||count>1024)return false;
 obs=mapping(2,0xc440000,(count*0x20+0xfff)&~0xfffu);if(!obs)return false;
 for(unsigned i=0;i<count;++i)if(((arb.core[(0x2000+4*i)/4]>>8)&0xfff)==0x61){apid=int(i);break;}
 native_board_clock[2]=uint32_t(apid);return apid>=0;
}
int counter(uint32_t *value) {
 if(!open())return -1;uint8_t ctrl=0;if(br_read8(obs,&arb,apid,0x46,&ctrl)||!(ctrl&0x80))return -2;
 uint32_t prev=~0u;
 for(unsigned t=0;t<4;++t){uint32_t v=0;for(unsigned b=0;b<4;++b){uint8_t q=0;if(br_read8(obs,&arb,apid,uint8_t(0x48+b),&q))return -3;v|=uint32_t(q)<<(8*b);}if(v==prev){*value=v;return 0;}prev=v;}
 return -4;
}
int read(uint64_t *seconds) {
 unsigned mode=0;PE_parse_boot_argn("board-clock",&mode,4);if(!mode||!seconds||__atomic_test_and_set(&busy,__ATOMIC_ACQUIRE))return 1;
 uint32_t value=0;int rc=counter(&value);native_board_clock[4]=uint32_t(rc);native_board_clock[5]=value;native_board_clock[8]++;
 if(!rc&&offset)*seconds=offset+value;else rc=1;
 __atomic_clear(&busy,__ATOMIC_RELEASE);return rc;
}
void set(uint64_t seconds) {
 if(__atomic_test_and_set(&busy,__ATOMIC_ACQUIRE))return;uint32_t value=0;
 if(!counter(&value)&&seconds>=value)offset=seconds-value;
 __atomic_clear(&busy,__ATOMIC_RELEASE);
}
struct Register{Register(){if(armdt_platform_clock_register){armdt_platform_clock_register(read,set);native_board_clock[0]=1;}}} registration;
}
extern "C" void sheng_board_clock_probe(void){uint64_t value=0;read(&value);IOLog("B5qClock: rtc apid=%d rc=%d counter=%u registered=%u\n",apid,int(native_board_clock[4]),native_board_clock[5],native_board_clock[0]);}
extern "C" unsigned sheng_board_clock_row(char *row,unsigned size){return snprintf(row,size,"RTC apid=%d rc=%d counter=%u reads=%u offset=%llu",apid,int(native_board_clock[4]),native_board_clock[5],native_board_clock[8],offset);}
