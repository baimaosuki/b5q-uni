// SPDX-License-Identifier: BSD-2-Clause-Patent
// SMCCC/PSCI architectural ABI, conduit from the captured b5q FDT (/soc/psci).
#include <IOKit/IOLib.h>
#include <IOKit/IOPlatformExpert.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <libkern/c++/OSData.h>
#include <pexpert/pexpert.h>
extern "C" int b5q_ufs_shutdown_status(void);
static bool powerOffAvailable=false,powerResetAvailable=false;
static bool powerHookInstalled=false;
extern "C" bool b5q_power_ready(void) {return powerHookInstalled && powerOffAvailable && powerResetAvailable;}
static int64_t b5qPsci(uint32_t fid,uint64_t argument=0) {
 register uint64_t x0 __asm__("x0")=fid,x1 __asm__("x1")=argument,x2 __asm__("x2")=0,x3 __asm__("x3")=0;
 __asm__ volatile("smc #0":"+r"(x0),"+r"(x1),"+r"(x2),"+r"(x3)::"memory",
  "x4","x5","x6","x7","x8","x9","x10","x11","x12","x13","x14","x15","x16","x17");
 return int64_t(int32_t(uint32_t(x0))); // All supported PSCI FIDs use SMC32.
}
static int b5qPlatformPower(unsigned type) {
 uint32_t fid=0;
 switch(type) {
  case kPEHaltCPU:case kPEUPSDelayHaltCPU:if(powerOffAvailable)fid=0x84000008;break;
  case kPERestartCPU:if(powerResetAvailable)fid=0x84000009;break;
  // Panic notifications must not initiate any normal shutdown or block I/O.
  case kPEPanicSync:case kPEPagingOff:case kPEPanicBegin:case kPEPanicEnd:
  case kPEPanicDiagnosticsDone:case kPEPanicDiagnosticsInProgress:return 0;
  default:return -1;
 }
 if(!fid)return -1;
 int flushed=b5q_ufs_shutdown_status();
 IOLog("B5qPower: request=%u stage=platform-after-driver-shutdown data-flush=%d fid=%x\n",type,flushed,fid);
 if(flushed!=1) {IOLog("B5qPower: transition refused; Data shutdown flush incomplete\n");return -1;}
 int64_t result=b5qPsci(fid);
 IOLog("B5qPower: PSCI transition unexpectedly returned %lld\n",(long long)result);return -1;
}
extern "C" void b5q_power_start(void) {
 unsigned enabled=0;PE_parse_boot_argn("b5q-psci-reset",&enabled,sizeof enabled);if(enabled!=1)return;
 IORegistryEntry *node=IORegistryEntry::fromPath("/psci",gIODTPlane);
 OSData *method=node?OSDynamicCast(OSData,node->getProperty("method")):nullptr;
 bool smc=method && method->getLength()==4 && !memcmp(method->getBytesNoCopy(),"smc",4);OSSafeReleaseNULL(node);
 if(!smc) {IOLog("B5qPower: PSCI SMC conduit missing; hook refused\n");return;}
 int64_t version=b5qPsci(0x84000000);
 if(version<0 || version<0x10000) {IOLog("B5qPower: PSCI version=%lld unsupported\n",(long long)version);return;}
 powerOffAvailable=b5qPsci(0x8400000a,0x84000008)>=0;
 powerResetAvailable=b5qPsci(0x8400000a,0x84000009)>=0;
 int (*expected)(unsigned)=nullptr;
 bool installed=__atomic_compare_exchange_n(&PE_halt_restart,&expected,b5qPlatformPower,false,__ATOMIC_ACQ_REL,__ATOMIC_ACQUIRE);
 powerHookInstalled=installed;
 IOLog("B5qPower: handler=%u psci=%llx off=%u reset=%u\n",installed,(unsigned long long)version,powerOffAvailable,powerResetAvailable);
}
