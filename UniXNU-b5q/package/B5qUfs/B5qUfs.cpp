// SPDX-License-Identifier: BSD-2-Clause-Patent
// Samsung DT-backed UFS warm-handoff, serial read-only queue, authenticated roots.
// Root commands stay read-only; B5qLogUfs adds only validated journal-slot writes.
#include <IOKit/IOService.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IOBufferMemoryDescriptor.h>
#include <IOKit/storage/IOBlockStorageDevice.h>
#include <IOKit/IOLib.h>
#include <IOKit/IOBSD.h>
#include <libkern/c++/OSIterator.h>
#include <libkern/c++/OSString.h>
#include <libkern/crypto/sha2.h>
#include <kern/thread.h>
#include <kern/clock.h>
#include "B5qLogProtocol.h"
#include "B5qLogCore.h"
#include "B5qLogArgs.h"
#include <pexpert/pexpert.h>
#include "B5qVmAlloc.h"
#include <mach/mach_vm.h>
#include "verified_root.h"
#include "B5qRootFormat.h"

#include "B5qUfsProtocol.h"
#include "B5qRootPolicies.h"
#include "B5qVerifiedRead.h"
#include "B5qDataFormat.h"
#include "B5qDataSeed.h"
using namespace B5qFormat;
extern "C" const struct vr_crypto vr_xnu_crypto;
namespace {
using namespace B5qUfsProtocol;
constexpr uint32_t dmaBytes=0x25000,maxTransfer=128*1024;
constexpr uint32_t fatalStatus=0x71880U;
struct Transport {
 IOMemoryMap *hcMap=nullptr,*gccMap=nullptr;
 IOBufferMemoryDescriptor *memory=nullptr;
 uintptr_t hc=0;uint8_t *dma=nullptr;uint64_t physical=0;
 const char *stage="initial";
 uint32_t lastOcs=0xffffffffU;
 uint8_t lastResponse=0;
 bool reuseSmmu=false;
 Status status;Power power;
 uint8_t commandLun=0xff,opcode=0xff;uint64_t commandLba=0,blocks=0;uint32_t blockSize=0;
 const char *gptReason="not-read",*rootName="none";unsigned matches=0;
 const char *scan[8]={"not-scanned","not-scanned","not-scanned","not-scanned","not-scanned","not-scanned","not-scanned","not-scanned"};
 IOLock *lock=nullptr;uint8_t lun=0;bool selected=false,poisoned=false;uint64_t capacity[8]={};
};
static Transport host;
static B5qData::Identity dataIdentity;
static bool dataRequested=false;
static uint32_t dataMode=B5qData::tailMode;
static uint32_t read32(uintptr_t p,unsigned off) { return *reinterpret_cast<volatile uint32_t*>(p+off); }
static void write32(uintptr_t p,unsigned off,uint32_t n) { __asm__ volatile("dsb sy":::"memory");*reinterpret_cast<volatile uint32_t*>(p+off)=n;__asm__ volatile("dsb sy":::"memory"); }
static uintptr_t map(uint64_t physical,uint64_t size,IOMemoryMap **keep) {
 IODeviceMemory *memory=IODeviceMemory::withRange(physical,size);if(!memory)return 0;
 *keep=memory->map(kIOMapAnywhere|kIOMapInhibitCache);memory->release();return *keep?uintptr_t((*keep)->getVirtualAddress()):0;
}
static void clean(void *p,size_t n) { uintptr_t a=uintptr_t(p)&~63ULL;for(uintptr_t end=uintptr_t(p)+n;a<end;a+=64)__asm__ volatile("dc civac, %0"::"r"(a):"memory");__asm__ volatile("dsb sy":::"memory"); }
static bool waitValue(unsigned reg,uint32_t mask,uint32_t value,unsigned loops) { for(unsigned i=0;i<loops;++i){if((read32(host.hc,reg)&mask)==value)return true;IODelay(10);}return false; }
// Keep the full last response in the panic itself: IOLog can be covered by it.
#define B5Q_STATE_FORMAT "stage=%s lun=%u op=%x lba=%llx scsi=%x flags=%x resp=%x res=%x sense=%06x/%u pwr=%x/%x cap=%llx bs=%u gpt=%s root=%s matches=%u poison=%u HCE=%x HCS=%x IS=%x DB=%x OCS=%x rsp=%x phys=%llx reuse=%u scan=[%s,%s,%s,%s,%s,%s,%s,%s]"
#define B5Q_STATE_VALUES host.stage,host.commandLun,host.opcode,static_cast<unsigned long long>(host.commandLba),host.status.scsi,host.status.flags,host.status.response,host.status.residual,host.status.sense,host.status.senseKnown,host.power.before,host.power.after,static_cast<unsigned long long>(host.blocks),host.blockSize,host.gptReason,host.rootName,host.matches,host.poisoned,host.hc?read32(host.hc,0x34):0,host.hc?read32(host.hc,0x30):0,host.hc?read32(host.hc,0x20):0,host.hc?read32(host.hc,0x58):0,host.lastOcs,host.lastResponse,static_cast<unsigned long long>(host.physical),host.reuseSmmu,host.scan[0],host.scan[1],host.scan[2],host.scan[3],host.scan[4],host.scan[5],host.scan[6],host.scan[7]
static void transportDiagnostic(const char *why) { IOLog("B5qUfs: %s " B5Q_STATE_FORMAT "\n",why,B5Q_STATE_VALUES); }
static void fail(const char *why) { panic("B5qUfs: %s " B5Q_STATE_FORMAT,why,B5Q_STATE_VALUES); }
// Samsung apps_smmu is owned by EL2. Only the verified firmware mapping
// handoff is supported; this translation unit contains no EL1 SMMU MMIO path.
static bool startTransport() {
 unsigned reuse=0;
 PE_parse_boot_argn("b5q-smmu-reuse",&reuse,sizeof(reuse));
 host.reuseSmmu=reuse==1;
 if(!host.reuseSmmu)return false;
 host.stage="UFS clock handoff";
 IOMemoryMap *gcc=nullptr;
 uintptr_t g=map(0x00177000,0x1000,&gcc);
 host.gccMap=gcc;
 // Shared SM8550 clock-register facts checked against Samsung DT clock IDs.
 if(!g||!(read32(g,4)&0x80000000U)||!(read32(g,0x18)&1)||!(read32(g,0x24)&1))return false;
 host.stage="UFS host mapping";
 host.hc=map(0x01d84000,0x3000,&host.hcMap);
 if(!host.hc)return false;

 host.stage="UFS link ready";
 if((read32(host.hc,0x34)&1)!=1||(read32(host.hc,0x30)&0x0f)!=0x0f||read32(host.hc,0x20)&fatalStatus)return false;
 host.stage="drain firmware queues";
 if(!waitValue(0x58,~0U,0,200000)||!waitValue(0x78,~0U,0,200000))return false;
 host.stage="stop transfer queue";
 write32(host.hc,0x60,0);
 if(!waitValue(0x60,1,0,10000)||read32(host.hc,0x58))return false;
 host.stage="DMA buffer allocation";
 host.memory=IOBufferMemoryDescriptor::inTaskWithOptions(kernel_task,static_cast<IOOptionBits>(kIODirectionInOut)|static_cast<IOOptionBits>(kIOMemoryPhysicallyContiguous)|static_cast<IOOptionBits>(kIOMemoryMapperNone),dmaBytes,4096);
 if(!host.memory)return false;
 host.dma=static_cast<uint8_t*>(host.memory->getBytesNoCopy());
 IOByteCount contiguous=0;
 host.physical=host.memory->getPhysicalSegment(0,&contiguous,kIOMemoryMapperNone);
 host.stage="DMA address width";
 if(!host.dma||!host.physical||(host.physical&4095)||contiguous<dmaBytes||(!(read32(host.hc,0)&(1U<<24))&&host.physical+dmaBytes>0x100000000ULL))return false;
 host.stage=host.reuseSmmu?"firmware SMMU reuse":"configure UFS stream";
 // No EL1 apps_smmu register access or fallback mapping.
 host.lock=IOLockAlloc();
 if(!host.lock)return false;
 bzero(host.dma,dmaBytes);
 clean(host.dma,dmaBytes);
 host.stage="start transfer queue";
 // Serialize/poll one slot while preserving error enables.
 write32(host.hc,0x24,read32(host.hc,0x24)&~1U);
 write32(host.hc,0x50,uint32_t(host.physical));
 write32(host.hc,0x54,uint32_t(host.physical>>32));
 write32(host.hc,0x20,1);
 write32(host.hc,0x60,1);
 bool ready=(read32(host.hc,0x60)&1)&&read32(host.hc,0x50)==uint32_t(host.physical)&&read32(host.hc,0x54)==uint32_t(host.physical>>32);
 if(ready)transportDiagnostic("ready");
 return ready;
}
// Serial queue completion is shared by SCSI, NOP and read-only queries.
static bool submit() {
 clean(host.dma,dmaBytes);write32(host.hc,0x20,1);write32(host.hc,0x58,1);
 bool done=waitValue(0x58,1,0,200000);clean(host.dma,dmaBytes);
 auto *utrd=reinterpret_cast<uint32_t*>(host.dma);auto *rsp=host.dma+commandOffset+responseOffset;
 host.lastOcs=utrd[2]&255;host.lastResponse=rsp[0];
 host.status={};host.status.type=rsp[0];host.status.flags=rsp[1];host.status.response=rsp[6];host.status.scsi=rsp[7];host.status.residual=be32(rsp+12);
 if(!done||(read32(host.hc,0x20)&fatalStatus)||host.lastOcs){host.poisoned=true;transportDiagnostic("DMA completion failure");return false;}
 return true;
}
// The only power command is exact START STOP UNIT ACTIVE to Device WLUN D0.
// TUR/capacity/READ are confined to normal LUNs; there are no block writes.
static int command(uint8_t lun,const uint8_t cdb[16],uint32_t bytes,void *output,Status *completion=nullptr) {
 if(completion)*completion={};
 if(host.poisoned||!allowed(lun,cdb,bytes)||(bytes&&!output))return -1;
 IOLockLock(host.lock);
 if(host.poisoned||read32(host.hc,0x58)||(read32(host.hc,0x20)&fatalStatus)){host.poisoned=true;IOLockUnlock(host.lock);return -1;}
 host.commandLun=lun;host.opcode=cdb[0];host.commandLba=cdb[0]==0x28?be32(cdb+2):cdb[0]==0x88?(uint64_t(be32(cdb+2))<<32)|be32(cdb+6):0;
 host.stage=cdb[0]==0x1b?"START STOP UNIT ACTIVE":cdb[0]==0?"TEST UNIT READY":cdb[0]==0x28?"READ10":cdb[0]==0x88?"READ16":"READ CAPACITY";
 bzero(host.dma,dmaBytes);auto *utrd=reinterpret_cast<uint32_t*>(host.dma);auto *ucd=host.dma+commandOffset;
 if(!B5qUfsProtocol::command(utrd,ucd,host.physical,lun,cdb,bytes)){IOLockUnlock(host.lock);return -1;}
 if(!submit()){IOLockUnlock(host.lock);return -1;}
 bool valid=response(ucd+responseOffset,host.lastOcs,lun,bytes,host.status);int result=-1;
 if(!valid)host.poisoned=true;
 else if(host.status.scsi)result=host.status.scsi;
 else if(host.status.exact){result=0;if(bytes)memcpy(output,host.dma+dataOffset,bytes);}
 else result=-2; // GOOD with short/overflow data is unusable, never copied.
 if(result)transportDiagnostic(valid?"SCSI command rejected":"invalid SCSI response");
 if(completion)*completion=host.status;
 write32(host.hc,0x20,1);IOLockUnlock(host.lock);return result;
}
static bool control(uint8_t type,uint8_t idn,uint8_t index,uint32_t *value=nullptr) {
 if(host.poisoned)return false;IOLockLock(host.lock);
 if(read32(host.hc,0x58)||(read32(host.hc,0x20)&fatalStatus)){host.poisoned=true;IOLockUnlock(host.lock);return false;}
 host.commandLun=(type==0||value)?0xff:index;host.opcode=type;host.commandLba=0;
 host.stage=type==0?"NOP OUT":value?"bCurrentPowerMode":"Unit descriptor";
 bzero(host.dma,dmaBytes);auto *utrd=reinterpret_cast<uint32_t*>(host.dma);auto *ucd=host.dma+commandOffset;
 if(!controlRequest(utrd,ucd,host.physical,type,idn,index,value!=nullptr)){IOLockUnlock(host.lock);return false;}
 bool ok=submit();
 if(ok){Control result=controlResponse(ucd+responseOffset,type,idn,index,value!=nullptr);if(!result.valid)host.poisoned=true;ok=result.success;if(ok&&value)*value=result.value;}
 if(!ok)transportDiagnostic("NOP/query rejected");write32(host.hc,0x20,1);IOLockUnlock(host.lock);return ok;
}
static int readinessCommand(uint8_t lun,const uint8_t cdb[16],uint32_t bytes,Status &status) { return command(lun,cdb,bytes,nullptr,&status); }
static void pauseMs(unsigned ms) { IOSleep(ms); }
static bool transportHealthy() { return !host.poisoned; }
static bool wakeDevice() {
 Wake result=wake(host.power,[]{return control(0,0,0);},[](uint32_t &power){return control(0x16,2,0,&power);},readinessCommand,pauseMs,transportHealthy);
 if(result==Wake::Ready)return true;
 host.gptReason=result==Wake::Nop?"nop":result==Wake::PowerQuery?"power-query":result==Wake::StartStop?"wake-scsi":result==Wake::PowerAfter?"power-requery":"power-not-active";
 return false;
}
// Query the standard Unit descriptor before TUR or any content reads.
static bool normalUnit(uint8_t lun) {
 if(lun>7||host.poisoned)return false;
 host.gptReason="unit-query";
 if(!control(0x16,2,lun))return false;
 const uint8_t *unit=host.dma+commandOffset+responseOffset+32;
 unsigned length=(unsigned(host.dma[commandOffset+responseOffset+10])<<8)|host.dma[commandOffset+responseOffset+11];
 if(unit[0]<0x13||unit[0]>length||unit[1]!=2||unit[2]!=lun){host.gptReason="unit-layout";return false;}
 if(unit[3]!=1){host.gptReason="unit-disabled";return false;}
 if(unit[4]!=0){host.gptReason="boot-unit-excluded";return false;}
 if(unit[10]!=12){host.gptReason="unit-not-4k";return false;}
 host.gptReason="unit-ready";return true;
}
static bool readLba(uint8_t lun,uint64_t lba,uint32_t count,void *out,bool metadata=false) {
 if(lun>7||!count||count>maxTransfer/4096||!host.capacity[lun]||lba>=host.capacity[lun]||count>host.capacity[lun]-lba)return false;
 if(metadata){if(host.selected||lba<1||lba>264||count>265-lba)return false;}
 else if(!host.selected||lun!=host.lun||lba<firstLba||lba>lastLba||count>lastLba-lba+1)return false;
 uint8_t cdb[16];if(!readCdb(cdb,lba,count))return false;
 return readRetry([&](Status &status){return command(lun,cdb,count*4096,out,&status);},pauseMs,transportHealthy);
}
static bool rootRead(uint64_t offset,uint64_t bytes,void *out) {
 if(offset%4096||bytes%4096||!inside(offset,bytes,partitionBytes))return false;auto *p=static_cast<uint8_t*>(out);
 while(bytes){uint32_t take=uint32_t(bytes>maxTransfer?maxTransfer:bytes);if(!readLba(host.lun,firstLba+offset/4096,take/4096,p))return false;offset+=take;bytes-=take;p+=take;}return true;
}
static bool selectLun() {
 uint8_t *block=static_cast<uint8_t*>(IOMalloc(4096));if(!block){host.gptReason="scan-allocation";return false;}
 unsigned found=0;uint8_t selected=0;
 for(uint8_t lun=0;lun<8;++lun){
  if(host.poisoned)break;
  host.gptReason="unit-query";
  if(!normalUnit(lun)){host.scan[lun]=host.gptReason;continue;}
  if(!ready(lun,readinessCommand,pauseMs,transportHealthy)){host.scan[lun]=host.gptReason="lun-not-ready";continue;}
  uint8_t cdb[16]={0x9e,0x10};putBe32(cdb+10,32);int result=-1;
  for(unsigned retry=0;retry<3;++retry){result=command(lun,cdb,32,block);if(!result||host.poisoned||!retryable(host.status))break;IOSleep(10);}
  bool capacity10=false;
  // READ CAPACITY16 is optional on some SCSI implementations. A specific
  // ILLEGAL REQUEST permits the standard 10-byte capacity query, never a guess.
  if(result==2&&host.status.senseKnown&&(host.status.sense==0x052000||host.status.sense==0x052400)){
   uint8_t cap10[16]={0x25};result=command(lun,cap10,8,block);capacity10=true;
  }
  if(result){host.scan[lun]=host.gptReason="capacity-scsi";continue;}
  uint64_t last=capacity10?be32(block):(uint64_t(be32(block))<<32)|be32(block+4);
  host.blockSize=be32(block+(capacity10?4:8));host.blocks=last==UINT64_MAX?0:last+1;
  if((capacity10&&last==UINT32_MAX)||last==UINT64_MAX||last<lastLba||host.blockSize!=4096){host.scan[lun]=host.gptReason="capacity-geometry";continue;}
  host.capacity[lun]=last+1;
  if(!readLba(lun,1,1,block,true)){host.scan[lun]=host.gptReason="gpt-header-read";continue;}
  Gpt g={};if(!header(block,last+1,g,&host.gptReason)){host.scan[lun]=host.gptReason;continue;}
  size_t raw=size_t(g.count)*g.stride,allocated=(raw+4095)&~size_t(4095);auto *table=static_cast<uint8_t*>(IOMalloc(allocated));
  if(!table){host.gptReason="gpt-table-allocation";IOFree(block,4096);return false;}
  bool ok=true;
  for(size_t at=0;at<allocated;){uint32_t take=uint32_t(allocated-at>maxTransfer?maxTransfer:allocated-at);if(!readLba(lun,g.entriesLba+at/4096,take/4096,table+at,true)){ok=false;host.gptReason="gpt-table-read";break;}at+=take;}
  if(ok&&target(table,g,&host.gptReason)){
   ++found;selected=lun;host.gptReason="matched";
   if(dataRequested && (lun!=0 || !B5qData::selectMode(block,table,g,dataMode,last+1,dataIdentity))) {
    host.gptReason="persistent-data-GPT-identity";IOFree(table,allocated);IOFree(block,4096);return false;
   }
  }
  host.matches=found;host.scan[lun]=host.gptReason;IOFree(table,allocated);
 }
 IOFree(block,4096);
 if(found!=1||host.poisoned){if(found>1)host.gptReason="duplicate-lun-match";return false;}
 host.lun=selected;host.selected=true;host.gptReason="matched";
 IOLog("B5qUfs: unique macosroot on LUN %u, [%llu,%llu], read-only\n",selected,firstLba,lastLba);return true;
}
struct Root { Entry image,table;vr_view policy;vm_offset_t allocation;vm_size_t allocated;uint8_t digest[48];char uuid[37];bool verified; };
static Root roots[3];
#include "B5qLogUfs.h"
static void uuidString(const uint8_t *p,char *out) {const char hex[]="0123456789ABCDEF";unsigned n=0;for(unsigned i=0;i<16;++i){if(i==4||i==6||i==8||i==10)out[n++]='-';out[n++]=hex[p[i]>>4];out[n++]=hex[p[i]&15];}out[n]=0;}
static bool authenticateRoots() {
 uint8_t block[4096],hash[32];Entry entries[6];uint64_t total=0;
 host.stage="SHNGROOT header read";if(!rootRead(0,4096,block))return false;
 host.stage="SHNGROOT header SHA256";if(!vr_xnu_crypto.sha256(block,4064,hash)||!equal(hash,block+4064,32))return false;
 host.stage="SHNGROOT v2 layout";if(!manifestEntries(block,entries,total))return false;
 for(unsigned i=0;i<3;++i){Root &r=roots[i];r.image=entries[i];r.table=entries[i+3];vr_view headerView={};host.rootName=r.image.name;
  host.stage="signed root header";
  if(vr_open_header(b5q_root_headers[i],544,b5q_root_key,1,&vr_xnu_crypto,&headerView)!=VR_OK||headerView.image_bytes!=r.image.bytes||!equal(headerView.image_sha256,r.image.sha256,32)||r.table.bytes!=headerView.block_count*32||r.table.bytes%4096)return false;
  host.stage="hash table allocation";uint64_t envelope=544+r.table.bytes;r.allocated=round_page(envelope);if(b5q_root_hash_allocate(&r.allocation,r.allocated)!=KERN_SUCCESS)return false;
  auto *buffer=reinterpret_cast<uint8_t*>(r.allocation);memcpy(buffer,b5q_root_headers[i],544);host.stage="hash table read";if(!rootRead(r.table.offset,r.table.bytes,buffer+544))return false;
  host.stage="hash table SHA256";if(!vr_xnu_crypto.sha256(buffer+544,r.table.bytes,hash)||!equal(hash,r.table.sha256,32)||!equal(hash,b5q_root_headers[i]+88,32))return false;
  host.stage="verified root policy";if(mach_vm_protect(kernel_map,r.allocation,r.allocated,TRUE,VM_PROT_READ)!=KERN_SUCCESS||vr_open(buffer,envelope,b5q_root_key,1,&vr_xnu_crypto,&r.policy)!=VR_OK)return false;
  uuidString(r.policy.volume_uuid,r.uuid);SHA384_CTX context;SHA384_Init(&context);SHA384_Update(&context,buffer,envelope);SHA384_Final(r.digest,&context);r.verified=true;
 }
 host.stage="root UUID uniqueness";return strcmp(roots[0].uuid,roots[1].uuid)&&strcmp(roots[1].uuid,roots[2].uuid)&&strcmp(roots[0].uuid,roots[2].uuid);
}
}
class B5qRootBlock:public IOBlockStorageDevice {
 OSDeclareDefaultStructors(B5qRootBlock)
 Root *root=nullptr;IOLock *readLock=nullptr;uint8_t *bounce=nullptr;bool online=false;
public:
 bool configure(unsigned i){if(i>=3||!roots[i].verified||roots[i].image.bytes%4096)return false;root=&roots[i];readLock=IOLockAlloc();bounce=static_cast<uint8_t*>(IOMalloc(maxTransfer));return readLock&&bounce;}
 bool authenticates(const char *uuid,uint8_t *digest) {if(!online||!root||!root->verified||!uuid||strcmp(uuid,root->uuid))return false;if(digest)memcpy(digest,root->digest,48);return true;}
 bool start(IOService *p) override {if(!root||!IOBlockStorageDevice::start(p))return false;
  OSDictionary *protocol=OSDictionary::withCapacity(2);OSString *location=OSString::withCString("Internal"),*connection=OSString::withCString("Virtual Interface");
  if(!protocol||!location||!connection)return false;protocol->setObject("Physical Interconnect Location",location);protocol->setObject("Physical Interconnect",connection);setProperty("Protocol Characteristics",protocol);location->release();connection->release();protocol->release();
  OSDictionary *device=OSDictionary::withCapacity(1);OSString *solid=OSString::withCString("Solid State");if(device&&solid){device->setObject("Medium Type",solid);setProperty("Device Characteristics",device);}OSSafeReleaseNULL(device);OSSafeReleaseNULL(solid);
  online=true;registerService();return true;}
 void free() override {if(bounce)IOFree(bounce,maxTransfer);if(readLock)IOLockFree(readLock);IOBlockStorageDevice::free();}
 IOReturn doEjectMedia() override{return kIOReturnUnsupported;} IOReturn doFormatMedia(UInt64) override{return kIOReturnNotWritable;}
 UInt32 doGetFormatCapacities(UInt64 *,UInt32) const override{return 0;}
 char *getVendorString() override{return const_cast<char*>("Samsung b5q");} char *getProductString() override{return root?root->image.name:const_cast<char*>("macosroot");}
 char *getRevisionString() override{return const_cast<char*>("1");} char *getAdditionalDeviceInfoString() override{return const_cast<char*>("Owner-authenticated read-only root");}
 IOReturn reportBlockSize(UInt64 *p) override{*p=512;return 0;} IOReturn reportMaxValidBlock(UInt64 *p) override{*p=root->image.bytes/512-1;return 0;}
 IOReturn reportEjectability(bool *p) override{*p=false;return 0;} IOReturn reportRemovability(bool *p) override{*p=false;return 0;}
 IOReturn reportMediaState(bool *p,bool *changed) override{*p=online;if(changed)*changed=false;return 0;}
 IOReturn reportWriteProtection(bool *p) override{*p=true;return 0;} IOReturn doSynchronizeCache() override{return 0;}
 IOReturn doSynchronize(UInt64,UInt64,IOOptionBits) override{return 0;} IOReturn getWriteCacheState(bool *p) override{*p=false;return 0;}
 IOReturn setWriteCacheState(bool) override{return kIOReturnUnsupported;}
 IOReturn doAsyncReadWrite(IOMemoryDescriptor *buffer,UInt64 block,UInt64 count,IOStorageAttributes *,IOStorageCompletion *completion) override {
  if(!online||!buffer||!completion||!completion->action||!count||block>=root->image.bytes/512||count>root->image.bytes/512-block||buffer->getLength()<count*512)return kIOReturnBadArgument;
  if(buffer->getDirection()!=kIODirectionIn)return kIOReturnNotWritable;
  IOLockLock(readLock);
  auto result=B5qVerifiedRead::transfer(block*512,count*512,root->image.bytes,bounce,maxTransfer,
   [&](uint64_t at,uint32_t n,uint8_t *out){return rootRead(root->image.offset+at,n,out);},
   [&](uint64_t index,const uint8_t *data){return vr_verify_block(&root->policy,index,data,4096,&vr_xnu_crypto)==VR_OK;},
   [&](uint64_t at,const uint8_t *data,uint32_t n){return buffer->writeBytes(at,data,n);});
  IOLockUnlock(readLock);completion->action(completion->target,completion->parameter,result.success?kIOReturnSuccess:kIOReturnIOError,result.done);return kIOReturnSuccess;
 }
};
OSDefineMetaClassAndStructors(B5qRootBlock,IOBlockStorageDevice)
extern "C" int b5q_ufs_block_authenticates(IOService *provider,const char *uuid,uint8_t *digest) {auto *block=OSDynamicCast(B5qRootBlock,provider);return block?(block->authenticates(uuid,digest)?1:0):-1;}
namespace {
static bool b5qDataWaitReady();
static bool mediaReady(B5qRootBlock *root,const char *uuid) {
 OSDictionary *matching=IOService::serviceMatching("IOMedia");if(!matching)return false;OSIterator *iterator=IOService::getMatchingServices(matching);matching->release();if(!iterator)return false;bool found=false;
 while(OSObject *o=iterator->getNextObject()){auto *media=OSDynamicCast(IOService,o);auto *id=media?OSDynamicCast(OSString,media->getProperty("UUID")):nullptr;if(!id||strcmp(id->getCStringNoCopy(),uuid))continue;for(IOService *p=media;p;p=p->getProvider())if(p==root)found=true;}
 iterator->release();return found;
}
static void publish(void *context,wait_result_t) {
    thread_set_thread_name(current_thread(),"b5q-ufs-publish");auto *provider=static_cast<IOService*>(context);unsigned order[]={1,2,0};
 // Root publication gates load_init_program(). Wait here, outside the loader
 // thread, until the one typed Data volume has all BSD identity properties.
 if(dataRequested&&!b5qDataWaitReady())fail("persistent Data media/UUID/BSD readiness timeout or duplicate UUID");
 for(unsigned i:order){auto *disk=new B5qRootBlock;if(!disk||!disk->init(static_cast<OSDictionary*>(nullptr))||!disk->configure(i)||!disk->attach(provider)||!disk->start(provider))fail("root block publication");
  bool ready=false;for(unsigned retry=0;retry<1200&&!ready;++retry){ready=mediaReady(disk,roots[i].uuid);if(!ready)IOSleep(50);}if(!ready)fail("APFS volume media timeout");IOLog("B5qUfs: authenticated %s volume %s ready\n",roots[i].image.name,roots[i].uuid);
 }
 provider->release();thread_terminate(current_thread());
}
}
#include "B5qDataBlock.h"
extern "C" void b5q_ufs_start(IOService *provider) {
 unsigned data=0;PE_parse_boot_argn("b5q-data-ufs",&data,sizeof(data));
 if(data>2)fail("invalid persistent Data mode");
 dataRequested=data!=0;
 char partition[32]={};PE_parse_boot_argn("b5q-data-partition",partition,sizeof(partition));
 dataMode=data==2?B5qData::userdataMode:!strcmp(partition,"macosdata")?B5qData::partitionMode:B5qData::tailMode;
 if(data==2 && partition[0] && strcmp(partition,"userdata"))fail("userdata mode conflicts with Data partition selection");
 if(data!=2 && partition[0] && strcmp(partition,"macosdata") && strcmp(partition,"macosroot-tail"))fail("invalid Data partition selection");
 unsigned requested=0;if(!PE_parse_boot_argn("b5q-root",&requested,sizeof(requested))||requested!=1)fail("explicit b5q-root=1 required");
 if(!startTransport())fail("Samsung firmware warm handoff/queue/SMMU unavailable");
 if(!wakeDevice())fail("UFS device wake/readiness");
 if(!selectLun())fail("macosroot discovery failed");
 if(!authenticateRoots())fail("root signature/hash-table authentication");
 if(dataRequested && !b5qDataStart(provider))fail("persistent Data identity/APFS validation");
 nabuLogStart();
 provider->retain();thread_t thread=nullptr;if(kernel_thread_start(publish,provider,&thread)!=KERN_SUCCESS)fail("publisher thread");thread_deallocate(thread);
}
