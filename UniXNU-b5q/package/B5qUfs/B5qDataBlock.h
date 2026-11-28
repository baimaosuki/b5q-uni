// SPDX-License-Identifier: BSD-2-Clause-Patent
// Included once by B5qUfs.cpp. Tag 1 and its UCD/data allocation belong only
// to Data. Root and journal retain tag 0. The hardware queue lock is shared.
#include <IOKit/IOMessage.h>
#include <IOKit/pwr_mgt/RootDomain.h>
namespace {
static IOBufferMemoryDescriptor *dataMemory;
static uint8_t *dataDma;
static uint64_t dataPhysical;
static B5qData::Volume dataVolume;
static unsigned dataFlushed=0;
static IOReturn dataIo(B5qData::Direction direction,uint64_t block,uint32_t count,
                      uint8_t *buffer) {
 if(!dataRequested || !dataMemory || !dataVolume.valid || host.lun!=0 ||
    (direction!=B5qData::Direction::Sync && !buffer))return kIOReturnNotReady;
 IOLockLock(host.lock);
 IOReturn result=kIOReturnIOError;
 if(host.poisoned || read32(host.hc,0x58) || (read32(host.hc,0x20)&fatalStatus))goto done;
 bzero(dataDma,dmaBytes);
 {
  uint32_t *utrd=reinterpret_cast<uint32_t *>(dataDma);
  uint8_t *ucd=dataDma+commandOffset;
  if(!B5qData::request(utrd,ucd,dataPhysical,host.lun,dataVolume,direction,block,count)) {
   result=kIOReturnBadArgument;goto done;
  }
  if(direction==B5qData::Direction::Write)__atomic_store_n(&dataFlushed,0U,__ATOMIC_RELEASE);
  uint32_t bytes=direction==B5qData::Direction::Sync?0:count*4096;
  if(direction==B5qData::Direction::Write)memcpy(dataDma+dataOffset,buffer,bytes);
  // UTRL base stays fixed. Slot 1 refers exclusively to Data's independent UCD.
  memcpy(host.dma+32,dataDma,32);clean(dataDma,dmaBytes);clean(host.dma+32,32);
  write32(host.hc,0x20,1);write32(host.hc,0x58,2);
  bool doneDma=waitValue(0x58,2,0,200000);
  clean(host.dma+32,32);clean(dataDma,dmaBytes);
  Status status;uint32_t ocs=reinterpret_cast<uint32_t *>(host.dma+32)[2]&255;
  if(!doneDma || ocs || (read32(host.hc,0x20)&fatalStatus)) {
   host.poisoned=true;goto done;
  }
  uint8_t *rsp=dataDma+commandOffset+responseOffset;
  // The common response checker is tag-0-specific; validate Data's tag first.
  if(rsp[3]!=1) {host.poisoned=true;goto done;}
  rsp[3]=0;
  if(!response(rsp,ocs,host.lun,bytes,status)) {host.poisoned=true;goto done;}
  if(!status.exact)goto done;
  if(direction==B5qData::Direction::Read)memcpy(buffer,dataDma+dataOffset,bytes);
  result=kIOReturnSuccess;write32(host.hc,0x20,1);
  // A late filesystem write is still accepted with FUA; never reuse an earlier
  // successful shutdown-flush flag after another request or failed flush.
  if(direction==B5qData::Direction::Write)__atomic_store_n(&dataFlushed,0U,__ATOMIC_RELEASE);
  if(direction==B5qData::Direction::Sync)__atomic_store_n(&dataFlushed,1U,__ATOMIC_RELEASE);
 }
done:
 if(result && direction==B5qData::Direction::Sync)__atomic_store_n(&dataFlushed,2U,__ATOMIC_RELEASE);
 IOLockUnlock(host.lock);
 if(result)IOLog("B5qData: I/O rejected dir=%u block=%llu count=%u status=%x poison=%u\n",
  unsigned(direction),(unsigned long long)block,count,result,host.poisoned);
 return result;
}
static IOReturn dataFlush() {
 return dataIo(B5qData::Direction::Sync,0,0,nullptr);
}
}
class B5qDataBlock:public IOBlockStorageDevice {
 OSDeclareDefaultStructors(B5qDataBlock)
 IOLock *bufferLock=nullptr;
 uint8_t *bounce=nullptr;
 bool online=false;
public:
 bool start(IOService *p) override {
  if(!dataVolume.valid || !IOBlockStorageDevice::start(p))return false;
  bufferLock=IOLockAlloc();bounce=static_cast<uint8_t *>(IOMalloc(maxTransfer));
  if(!bufferLock || !bounce)return false;
  PMinit();
  IOPMrootDomain *power=IOService::getPMRootDomain();
  if(!power || power->addPowerChild(this)!=kIOReturnSuccess) {PMstop();return false;}
  online=true;registerService();return true;
 }
 void free() override {PMstop();if(bounce)IOFree(bounce,maxTransfer);if(bufferLock)IOLockFree(bufferLock);IOBlockStorageDevice::free();}
 void systemWillShutdown(IOOptionBits specifier) override {
  IOLog("B5qData: shutdown specifier=%x stage=driver-notify writes=FUA-still-accepted\n",specifier);
  __atomic_store_n(&nabu_log_stopping,true,__ATOMIC_RELEASE);
  IOReturn status=dataFlush();
  IOLog("B5qData: shutdown flush=%x stage=before-platform-transition\n",status);
  IOBlockStorageDevice::systemWillShutdown(specifier);
 }
 IOReturn doEjectMedia() override{return kIOReturnUnsupported;}
 IOReturn doFormatMedia(UInt64) override{return kIOReturnUnsupported;}
 UInt32 doGetFormatCapacities(UInt64 *,UInt32) const override{return 0;}
 char *getVendorString() override{return const_cast<char *>("Samsung b5q");}
 char *getProductString() override{return const_cast<char *>("B5q Persistent Data");}
 char *getRevisionString() override{return const_cast<char *>("1");}
 char *getAdditionalDeviceInfoString() override{return const_cast<char *>("GPT+root-bound APFS Data");}
 IOReturn reportBlockSize(UInt64 *p) override{*p=4096;return 0;}
 IOReturn reportMaxValidBlock(UInt64 *p) override{*p=dataVolume.blocks-1;return 0;}
 IOReturn reportEjectability(bool *p) override{*p=false;return 0;}
 IOReturn reportRemovability(bool *p) override{*p=false;return 0;}
 IOReturn reportMediaState(bool *p,bool *changed) override{*p=online;if(changed)*changed=false;return 0;}
 IOReturn reportWriteProtection(bool *p) override{*p=false;return 0;}
 IOReturn doSynchronizeCache() override{return dataFlush();}
 IOReturn doSynchronize(UInt64 block,UInt64 count,IOOptionBits) override{
  uint64_t lba;if(count && !B5qData::absolute(dataVolume,block,count,lba))return kIOReturnBadArgument;
  if(!count && block>dataVolume.blocks)return kIOReturnBadArgument;return dataFlush();
 }
 IOReturn getWriteCacheState(bool *p) override{*p=true;return 0;}
 IOReturn setWriteCacheState(bool enabled) override{return enabled?kIOReturnSuccess:dataFlush();}
 IOReturn doAsyncReadWrite(IOMemoryDescriptor *buffer,UInt64 block,UInt64 count,
                          IOStorageAttributes *,IOStorageCompletion *completion) override {
  uint64_t lba;
  if(!online || !buffer || !completion || !completion->action ||
     !B5qData::absolute(dataVolume,block,count,lba) || count>UINT64_MAX/4096 ||
     buffer->getLength()<count*4096)return kIOReturnBadArgument;
  const IODirection direction=buffer->getDirection();
  if(direction!=kIODirectionIn && direction!=kIODirectionOut)return kIOReturnBadArgument;
  IOLockLock(bufferLock);uint64_t done=0;IOReturn status=kIOReturnSuccess;
  while(done<count) {
   unsigned take=unsigned(count-done>32?32:count-done);unsigned bytes=take*4096;
   if(direction==kIODirectionOut && buffer->readBytes(done*4096,bounce,bytes)!=bytes) {status=kIOReturnUnderrun;break;}
   status=dataIo(direction==kIODirectionIn?B5qData::Direction::Read:B5qData::Direction::Write,block+done,take,bounce);
   if(status)break;
   if(direction==kIODirectionIn && buffer->writeBytes(done*4096,bounce,bytes)!=bytes) {status=kIOReturnUnderrun;break;}
   done+=take;
  }
  IOLockUnlock(bufferLock);
  completion->action(completion->target,completion->parameter,status,done*4096);return kIOReturnSuccess;
 }
};
OSDefineMetaClassAndStructors(B5qDataBlock,IOBlockStorageDevice)
namespace {
static bool b5qDataStart(IOService *provider) {
 uint8_t header[4096],rootHeader[4096],hash[32];
 if(host.lun!=0 || !B5qData::validIdentity(dataIdentity,host.capacity[host.lun]) ||
    !rootRead(0,4096,rootHeader) || !vr_xnu_crypto.sha256(rootHeader,4096,hash) ||
    !equal(hash,B5qData::rootHeaderSha,32))return false;
 uint8_t cdb[16];if(!readCdb(cdb,dataIdentity.first,1) || command(host.lun,cdb,4096,header)!=0 ||
    !B5qData::open(header,dataIdentity,host.capacity[host.lun],dataVolume))return false;
 // UFSHCI CAP.NUTRS is encoded as number of slots minus one.
 if((read32(host.hc,0)&31)<1)return false;
 dataMemory=IOBufferMemoryDescriptor::inTaskWithOptions(kernel_task,
  static_cast<IOOptionBits>(kIODirectionInOut)|static_cast<IOOptionBits>(kIOMemoryPhysicallyContiguous)|
  static_cast<IOOptionBits>(kIOMemoryMapperNone),dmaBytes,4096);
 if(!dataMemory)return false;dataDma=static_cast<uint8_t *>(dataMemory->getBytesNoCopy());
 if(dataMemory->prepare(kIODirectionInOut)!=kIOReturnSuccess)return false;
 IOByteCount contiguous=0;dataPhysical=dataMemory->getPhysicalSegment(0,&contiguous,kIOMemoryMapperNone);
 if(!dataDma || !dataPhysical || (dataPhysical&4095) || contiguous<dmaBytes ||
    dataPhysical>UINT64_MAX-dmaBytes || (!(read32(host.hc,0)&(1U<<24)) && dataPhysical+dmaBytes>0x100000000ULL) ||
    (dataPhysical<host.physical+dmaBytes && host.physical<dataPhysical+dmaBytes))return false;
 if(dataIo(B5qData::Direction::Read,0,1,header) || !equal(header+32,"NXSB",4) ||
    le32(header+36)!=4096 || le64(header+40)!=dataVolume.blocks || !equal(header+72,dataVolume.container,16))return false;
 auto *disk=new B5qDataBlock;
 if(!disk || !disk->init(static_cast<OSDictionary *>(nullptr)) || !disk->attach(provider) || !disk->start(provider))return false;
 IOLog("B5qData: mode=%u LUN=0 window=[%llu,%llu] blocks=%llu tag=1 FUA=1 writable=1\n",
  dataIdentity.mode,(unsigned long long)dataVolume.first,(unsigned long long)dataIdentity.last,(unsigned long long)dataVolume.blocks);
 return true;
}
}
extern "C" int b5q_ufs_shutdown_status(void) {
 return dataRequested?int(__atomic_load_n(&dataFlushed,__ATOMIC_ACQUIRE)):1;
}
