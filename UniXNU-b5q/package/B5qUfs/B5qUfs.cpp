// SPDX-License-Identifier: BSD-2-Clause-Patent
// Samsung DT-backed UFS warm-handoff, serial read-only queue, authenticated roots.
// No SCSI WRITE, FORMAT, UNMAP, vendor commands, GPIO, clocks or PHY reset paths.
#include <IOKit/IOService.h>
#include <IOKit/IODeviceTreeSupport.h>
#include <IOKit/IOBufferMemoryDescriptor.h>
#include <IOKit/storage/IOBlockStorageDevice.h>
#include <IOKit/IOLib.h>
#include <libkern/c++/OSIterator.h>
#include <libkern/c++/OSString.h>
#include <libkern/crypto/sha2.h>
#include <kern/thread.h>
#include <pexpert/pexpert.h>
#include <vm/vm_kern.h>
#include <vm/vm_kern_xnu.h>
#include <vm/vm_map.h>
#include <mach/mach_vm.h>
#include "verified_root.h"
#include "B5qRootFormat.h"
#include "B5qSmmu.h"
#include "B5qRootPolicies.h"
using namespace B5qFormat;
extern "C" const struct vr_crypto vr_xnu_crypto;
namespace {
constexpr uint32_t dmaBytes=0x25000,commandOffset=0x1000,responseOffset=0x200,prdOffset=0x400,dataOffset=0x2000,maxTransfer=128*1024;
constexpr uint32_t fatalStatus=0x71880U;
struct Transport {
 IOMemoryMap *hcMap=nullptr,*smmuMap=nullptr,*gccMap=nullptr;
 IOBufferMemoryDescriptor *memory=nullptr;
 uintptr_t hc=0,smmu=0;uint8_t *dma=nullptr;uint64_t physical=0;
 IOLock *lock=nullptr;uint8_t lun=0;bool selected=false,poisoned=false;uint64_t capacity[8]={};
};
static Transport host;
static uint32_t read32(uintptr_t p,unsigned off) { return *reinterpret_cast<volatile uint32_t*>(p+off); }
static void write32(uintptr_t p,unsigned off,uint32_t n) { __asm__ volatile("dsb sy":::"memory");*reinterpret_cast<volatile uint32_t*>(p+off)=n;__asm__ volatile("dsb sy":::"memory"); }
static uintptr_t map(uint64_t physical,uint64_t size,IOMemoryMap **keep) {
 IODeviceMemory *memory=IODeviceMemory::withRange(physical,size);if(!memory)return 0;
 *keep=memory->map(kIOMapAnywhere|kIOMapInhibitCache);memory->release();return *keep?uintptr_t((*keep)->getVirtualAddress()):0;
}
static void clean(void *p,size_t n) { uintptr_t a=uintptr_t(p)&~63ULL;for(uintptr_t end=uintptr_t(p)+n;a<end;a+=64)__asm__ volatile("dc civac, %0"::"r"(a):"memory");__asm__ volatile("dsb sy":::"memory"); }
static bool waitValue(unsigned reg,uint32_t mask,uint32_t value,unsigned loops) { for(unsigned i=0;i<loops;++i){if((read32(host.hc,reg)&mask)==value)return true;IODelay(10);}return false; }
static void fail(const char *why) { panic("B5qUfs: %s (HCE=%x HCS=%x IS=%x DB=%x)",why,host.hc?read32(host.hc,0x34):0,host.hc?read32(host.hc,0x30):0,host.hc?read32(host.hc,0x20):0,host.hc?read32(host.hc,0x58):0); }
// Find an unused bypass bank, preserving all streams except exact Samsung UFS SID.
// The UFS queue is already stopped and has no pending DMA before this executes.
static bool mapUfsStream() {
 return b5qConfigureUfsStream(host.physical,dmaBytes,[](unsigned off){return read32(host.smmu,off);},[](unsigned off,uint32_t v){write32(host.smmu,off,v);});
}
static bool startTransport() {
 IOMemoryMap *gcc=nullptr;uintptr_t g=map(0x00177000,0x1000,&gcc);host.gccMap=gcc;
 // Offsets are shared SM8550 clock-register facts, checked against Samsung DT clock IDs.
 if(!g||!(read32(g,4)&0x80000000U)||!(read32(g,0x18)&1)||!(read32(g,0x24)&1))return false;
 host.hc=map(0x01d84000,0x3000,&host.hcMap);host.smmu=map(0x15000000,0x100000,&host.smmuMap);
 if(!host.hc||!host.smmu)return false;
 if((read32(host.hc,0x34)&1)!=1||(read32(host.hc,0x30)&0x0f)!=0x0f||read32(host.hc,0x20)&fatalStatus)return false;
 if(!waitValue(0x58,~0U,0,200000)||!waitValue(0x78,~0U,0,200000))return false;
 // Stop transfer-list execution without resetting link/PHY or task-management state.
 write32(host.hc,0x60,0);if(!waitValue(0x60,1,0,10000)||read32(host.hc,0x58))return false;
 host.memory=IOBufferMemoryDescriptor::inTaskWithOptions(kernel_task,static_cast<IOOptionBits>(kIODirectionInOut)|static_cast<IOOptionBits>(kIOMemoryPhysicallyContiguous)|static_cast<IOOptionBits>(kIOMemoryMapperNone),dmaBytes,4096);
 if(!host.memory)return false;host.dma=static_cast<uint8_t*>(host.memory->getBytesNoCopy());IOByteCount contiguous=0;host.physical=host.memory->getPhysicalSegment(0,&contiguous,kIOMemoryMapperNone);
 if(!host.dma||!host.physical||(host.physical&4095)||contiguous<dmaBytes||(!(read32(host.hc,0)&(1U<<24))&&host.physical+dmaBytes>0x100000000ULL))return false;
 if(!mapUfsStream())return false;host.lock=IOLockAlloc();if(!host.lock)return false;
 bzero(host.dma,dmaBytes);clean(host.dma,dmaBytes);
 // Serialize/poll one slot. Disable UTRCS IRQ only, preserving error enables.
 write32(host.hc,0x24,read32(host.hc,0x24)&~1U);write32(host.hc,0x50,uint32_t(host.physical));write32(host.hc,0x54,uint32_t(host.physical>>32));write32(host.hc,0x20,1);write32(host.hc,0x60,1);
 return (read32(host.hc,0x60)&1)&&read32(host.hc,0x50)==uint32_t(host.physical)&&read32(host.hc,0x54)==uint32_t(host.physical>>32);
}
// Opcode allowlist prevents block writes at the command construction boundary.
static int command(uint8_t lun,const uint8_t cdb[16],uint32_t bytes,void *output) {
 if(host.poisoned||lun>7||!bytes||bytes>maxTransfer||bytes%4||!output||(!(cdb[0]==0x9e&&cdb[1]==0x10)&&cdb[0]!=0x88))return -1;
 IOLockLock(host.lock);if(host.poisoned||read32(host.hc,0x58)||read32(host.hc,0x20)&fatalStatus){IOLockUnlock(host.lock);return -1;}
 bzero(host.dma,dmaBytes);auto *utrd=reinterpret_cast<uint32_t*>(host.dma);auto *ucd=host.dma+commandOffset;
 utrd[0]=0x10000000U|(2U<<25);utrd[2]=15;utrd[4]=uint32_t(host.physical+commandOffset);utrd[5]=uint32_t((host.physical+commandOffset)>>32);utrd[6]=(512U/4)|((responseOffset/4)<<16);utrd[7]=1|((prdOffset/4)<<16);
 ucd[0]=1;ucd[1]=0x40;ucd[2]=lun;ucd[3]=0;putBe32(ucd+12,bytes);memcpy(ucd+16,cdb,16);
 auto *prd=reinterpret_cast<uint32_t*>(ucd+prdOffset);prd[0]=uint32_t(host.physical+dataOffset);prd[1]=uint32_t((host.physical+dataOffset)>>32);prd[3]=bytes-1;
 clean(host.dma,dmaBytes);write32(host.hc,0x20,1);write32(host.hc,0x58,1);
 bool done=waitValue(0x58,1,0,200000);if(!done||read32(host.hc,0x20)&fatalStatus){host.poisoned=true;IOLockUnlock(host.lock);return -1;}
 clean(host.dma,dmaBytes);const uint8_t *rsp=ucd+responseOffset;int status=-1;
 if((utrd[2]&255)==0&&rsp[0]==0x21&&rsp[2]==lun&&rsp[3]==0&&!rsp[8]&&((unsigned(rsp[10])<<8)|rsp[11])<=480&&!(rsp[1]&0x60)&&!be32(rsp+12)&&!rsp[6]){
  status=rsp[7];if(!status)memcpy(output,host.dma+dataOffset,bytes);
 }else host.poisoned=true;
 write32(host.hc,0x20,1);IOLockUnlock(host.lock);return status;
}
// Read only the standard Unit descriptor before any LUN content. UFS boot
// LUNs (bBootLunID != 0) and disabled units are never given block commands.
static bool normalUnit(uint8_t lun) {
 if(lun>7||host.poisoned)return false;IOLockLock(host.lock);
 if(read32(host.hc,0x58)||read32(host.hc,0x20)&fatalStatus){IOLockUnlock(host.lock);return false;}
 bzero(host.dma,dmaBytes);auto *utrd=reinterpret_cast<uint32_t*>(host.dma);auto *ucd=host.dma+commandOffset;
 utrd[0]=0x10000000U;utrd[2]=15;utrd[4]=uint32_t(host.physical+commandOffset);utrd[5]=uint32_t((host.physical+commandOffset)>>32);utrd[6]=(512U/4)|((responseOffset/4)<<16);utrd[7]=((prdOffset/4)<<16);
 ucd[0]=0x16;ucd[5]=1;ucd[12]=1;ucd[13]=2;ucd[14]=lun;ucd[18]=0;ucd[19]=0xff;
 clean(host.dma,dmaBytes);write32(host.hc,0x20,1);write32(host.hc,0x58,1);
 if(!waitValue(0x58,1,0,200000)||read32(host.hc,0x20)&fatalStatus){host.poisoned=true;IOLockUnlock(host.lock);return false;}
 clean(host.dma,dmaBytes);const uint8_t *rsp=ucd+responseOffset;unsigned length=(unsigned(rsp[10])<<8)|rsp[11],echo=(unsigned(rsp[18])<<8)|rsp[19];
 bool ok=(utrd[2]&255)==0&&rsp[0]==0x36&&!rsp[2]&&!rsp[3]&&!rsp[6]&&!rsp[8]&&rsp[12]==1&&rsp[13]==2&&rsp[14]==lun&&!rsp[15]&&length>=0x13&&length<=255&&echo==length;
 if(ok){const uint8_t *unit=rsp+32;ok=unit[0]>=0x13&&unit[0]<=length&&unit[1]==2&&unit[2]==lun&&unit[3]==1&&unit[4]==0&&unit[10]==12;}
 write32(host.hc,0x20,1);IOLockUnlock(host.lock);return ok;
}
static bool readLba(uint8_t lun,uint64_t lba,uint32_t count,void *out,bool metadata=false) {
 if(lun>7||!count||count>maxTransfer/4096||!host.capacity[lun]||lba>=host.capacity[lun]||count>host.capacity[lun]-lba)return false;
 if(metadata){if(host.selected||lba<1||lba>264||count>265-lba)return false;}
 else if(!host.selected||lun!=host.lun||lba<firstLba||lba>lastLba||count>lastLba-lba+1)return false;
 uint8_t cdb[16]={0x88};putBe64(cdb+2,lba);putBe32(cdb+10,count);return command(lun,cdb,count*4096,out)==0;
}
static bool rootRead(uint64_t offset,uint64_t bytes,void *out) {
 if(offset%4096||bytes%4096||!inside(offset,bytes,partitionBytes))return false;auto *p=static_cast<uint8_t*>(out);
 while(bytes){uint32_t take=uint32_t(bytes>maxTransfer?maxTransfer:bytes);if(!readLba(host.lun,firstLba+offset/4096,take/4096,p))return false;offset+=take;bytes-=take;p+=take;}return true;
}
static bool selectLun() {
 uint8_t *block=static_cast<uint8_t*>(IOMalloc(4096));if(!block)return false;unsigned found=0;uint8_t selected=0;
 for(uint8_t lun=0;lun<8;++lun){if(!normalUnit(lun))continue;uint8_t cdb[16]={0x9e,0x10};putBe32(cdb+10,32);int result=-1;
  for(unsigned retry=0;retry<3;++retry){result=command(lun,cdb,32,block);if(!result)break;IODelay(1000);}if(result){if(host.poisoned)break;continue;}
  uint64_t last=(uint64_t(be32(block))<<32)|be32(block+4);if(be32(block+8)!=4096||last==UINT64_MAX||last<lastLba)continue;host.capacity[lun]=last+1;
  if(!readLba(lun,1,1,block,true))continue;Gpt g={};if(!header(block,last+1,g))continue;
  size_t raw=size_t(g.count)*g.stride,allocated=(raw+4095)&~size_t(4095);auto *table=static_cast<uint8_t*>(IOMalloc(allocated));if(!table){IOFree(block,4096);return false;}
  bool ok=true;for(size_t at=0;at<allocated;){uint32_t take=uint32_t(allocated-at>maxTransfer?maxTransfer:allocated-at);if(!readLba(lun,g.entriesLba+at/4096,take/4096,table+at,true)){ok=false;break;}at+=take;}
  if(ok&&target(table,g)){++found;selected=lun;}IOFree(table,allocated);
 }
 IOFree(block,4096);if(found!=1||host.poisoned)return false;host.lun=selected;host.selected=true;IOLog("B5qUfs: unique macosroot on LUN %u, [%llu,%llu], read-only\n",selected,firstLba,lastLba);return true;
}
struct Root { Entry image,table;vr_view policy;vm_offset_t allocation;vm_size_t allocated;uint8_t digest[48];char uuid[37];bool verified; };
static Root roots[3];
static void uuidString(const uint8_t *p,char *out) {const char hex[]="0123456789ABCDEF";unsigned n=0;for(unsigned i=0;i<16;++i){if(i==4||i==6||i==8||i==10)out[n++]='-';out[n++]=hex[p[i]>>4];out[n++]=hex[p[i]&15];}out[n]=0;}
static bool authenticateRoots() {
 uint8_t block[4096],hash[32];Entry entries[6];uint64_t total=0;
 if(!rootRead(0,4096,block)||!vr_xnu_crypto.sha256(block,4064,hash)||!equal(hash,block+4064,32)||!manifestEntries(block,entries,total))return false;
 for(unsigned i=0;i<3;++i){Root &r=roots[i];r.image=entries[i];r.table=entries[i+3];vr_view headerView={};
  if(vr_open_header(b5q_root_headers[i],544,b5q_root_key,1,&vr_xnu_crypto,&headerView)!=VR_OK||headerView.image_bytes!=r.image.bytes||!equal(headerView.image_sha256,r.image.sha256,32)||r.table.bytes!=headerView.block_count*32||r.table.bytes%4096)return false;
  uint64_t envelope=544+r.table.bytes;r.allocated=round_page(envelope);if(kmem_alloc(kernel_map,&r.allocation,r.allocated,kma_flags_t(KMA_KOBJECT|KMA_DATA),VM_KERN_MEMORY_SECURITY)!=KERN_SUCCESS)return false;
  auto *buffer=reinterpret_cast<uint8_t*>(r.allocation);memcpy(buffer,b5q_root_headers[i],544);if(!rootRead(r.table.offset,r.table.bytes,buffer+544))return false;
  if(!vr_xnu_crypto.sha256(buffer+544,r.table.bytes,hash)||!equal(hash,r.table.sha256,32)||!equal(hash,b5q_root_headers[i]+88,32))return false;
  if(mach_vm_protect(kernel_map,r.allocation,r.allocated,TRUE,VM_PROT_READ)!=KERN_SUCCESS||vr_open(buffer,envelope,b5q_root_key,1,&vr_xnu_crypto,&r.policy)!=VR_OK)return false;
  uuidString(r.policy.volume_uuid,r.uuid);SHA384_CTX context;SHA384_Init(&context);SHA384_Update(&context,buffer,envelope);SHA384_Final(r.digest,&context);r.verified=true;
 }
 return strcmp(roots[0].uuid,roots[1].uuid)&&strcmp(roots[1].uuid,roots[2].uuid)&&strcmp(roots[0].uuid,roots[2].uuid);
}
}
class B5qRootBlock:public IOBlockStorageDevice {
 OSDeclareDefaultStructors(B5qRootBlock)
 Root *root=nullptr;IOLock *readLock=nullptr;uint8_t *bounce=nullptr;bool online=false;
public:
 bool configure(unsigned i){if(i>=3||!roots[i].verified)return false;root=&roots[i];readLock=IOLockAlloc();bounce=static_cast<uint8_t*>(IOMalloc(4096));return readLock&&bounce;}
 bool authenticates(const char *uuid,uint8_t *digest) {if(!online||!root||!root->verified||!uuid||strcmp(uuid,root->uuid))return false;if(digest)memcpy(digest,root->digest,48);return true;}
 bool start(IOService *p) override {if(!root||!IOBlockStorageDevice::start(p))return false;
  OSDictionary *protocol=OSDictionary::withCapacity(2);OSString *location=OSString::withCString("Internal"),*connection=OSString::withCString("Virtual Interface");
  if(!protocol||!location||!connection)return false;protocol->setObject("Physical Interconnect Location",location);protocol->setObject("Physical Interconnect",connection);setProperty("Protocol Characteristics",protocol);location->release();connection->release();protocol->release();
  OSDictionary *device=OSDictionary::withCapacity(1);OSString *solid=OSString::withCString("Solid State");if(device&&solid){device->setObject("Medium Type",solid);setProperty("Device Characteristics",device);}OSSafeReleaseNULL(device);OSSafeReleaseNULL(solid);
  online=true;registerService();return true;}
 void free() override {if(bounce)IOFree(bounce,4096);if(readLock)IOLockFree(readLock);IOBlockStorageDevice::free();}
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
  IOLockLock(readLock);uint64_t offset=block*512,remaining=count*512,done=0;IOReturn status=kIOReturnSuccess;
  while(remaining){uint64_t index=offset/4096;size_t in=size_t(offset%4096),take=size_t(remaining<4096-in?remaining:4096-in);
   if(!rootRead(root->image.offset+index*4096,4096,bounce)||vr_verify_block(&root->policy,index,bounce,4096,&vr_xnu_crypto)!=VR_OK){status=kIOReturnIOError;break;}
   if(buffer->writeBytes(done,bounce+in,take)!=take){status=kIOReturnIOError;break;}offset+=take;remaining-=take;done+=take;
  }
  IOLockUnlock(readLock);IOStorage::complete(completion,status,done);return kIOReturnSuccess;
 }
};
OSDefineMetaClassAndStructors(B5qRootBlock,IOBlockStorageDevice)
extern "C" int b5q_ufs_block_authenticates(IOService *provider,const char *uuid,uint8_t *digest) {auto *block=OSDynamicCast(B5qRootBlock,provider);return block?(block->authenticates(uuid,digest)?1:0):-1;}
namespace {
static bool mediaReady(B5qRootBlock *root,const char *uuid) {
 OSDictionary *matching=IOService::serviceMatching("IOMedia");if(!matching)return false;OSIterator *iterator=IOService::getMatchingServices(matching);matching->release();if(!iterator)return false;bool found=false;
 while(OSObject *o=iterator->getNextObject()){auto *media=OSDynamicCast(IOService,o);auto *id=media?OSDynamicCast(OSString,media->getProperty("UUID")):nullptr;if(!id||strcmp(id->getCStringNoCopy(),uuid))continue;for(IOService *p=media;p;p=p->getProvider())if(p==root)found=true;}
 iterator->release();return found;
}
static void publish(void *context,wait_result_t) {auto *provider=static_cast<IOService*>(context);unsigned order[]={1,2,0};
 for(unsigned i:order){auto *disk=new B5qRootBlock;if(!disk||!disk->init(static_cast<OSDictionary*>(nullptr))||!disk->configure(i)||!disk->attach(provider)||!disk->start(provider))fail("root block publication");
  bool ready=false;for(unsigned retry=0;retry<1200&&!ready;++retry){ready=mediaReady(disk,roots[i].uuid);if(!ready)IOSleep(50);}if(!ready)fail("APFS volume media timeout");IOLog("B5qUfs: authenticated %s volume %s ready\n",roots[i].image.name,roots[i].uuid);
 }
 provider->release();thread_terminate(current_thread());
}
}
extern "C" void b5q_ufs_start(IOService *provider) {
 unsigned requested=0;if(!PE_parse_boot_argn("b5q-root",&requested,sizeof(requested))||requested!=1)fail("explicit b5q-root=1 required");
 if(!startTransport())fail("Samsung firmware warm handoff/queue/SMMU unavailable");if(!selectLun())fail("no unique exact macosroot GPT match");if(!authenticateRoots())fail("root signature/hash-table authentication");
 provider->retain();thread_t thread=nullptr;if(kernel_thread_start(publish,provider,&thread)!=KERN_SUCCESS)fail("publisher thread");thread_deallocate(thread);
}
