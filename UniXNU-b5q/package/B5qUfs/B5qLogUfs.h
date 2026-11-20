/* Included in NativeUfs.cpp after the host primitives, only for logging builds.
 * All disk operations run on this ordinary thread. No panic hook, misc write,
 * reset, USB, or general-purpose writable block service is introduced.
 *
 * Every pre-commit stop names its gate in an IOLog line. The lines never
 * contain the allocation token or any token byte. They are ordinary console
 * output: if the journal cannot be committed they are visible on screen (or in
 * a boot recording) but are not themselves persisted by this writer.
 */
#include "B5qLogCore.h"
#include "B5qLogVolume.h"
#include "B5qLogProtocol.h"
#include "B5qLogArgs.h"
#include <kern/clock.h>
static const uint8_t nabu_log_build_id[32]="b5q-log-v12-26C5035r";

static struct nb_log_volume *nabu_log_volume_ptr;
#define nabu_log_volume (*nabu_log_volume_ptr)
static uint8_t *nabu_log_payload;
static uint8_t nabu_log_headers[2][4096],nabu_log_header[4096];
static const char *nabu_log_io_reason="none";
static IOReturn nabu_log_io_result;
static uint32_t nabu_log_io_scsi;
extern "C" {
volatile unsigned nabu_log_writer_state=0,nabu_log_writer_rounds=0,nabu_log_writer_failures=0;
uint64_t nabu_log_committed_end=0;
}
/* 1 success, 0 bounded contention, -2 retryable read, -1 transport/gate failure. The existing root
 * read path stays read-only. Only this function can emit the bounded WRITE(10). */
static int nabuLogIo(bool write,uint64_t lba,uint32_t blocks,uint8_t *data,bool sync=false)
{
  if(!host.selected || host.poisoned || !host.lock || (!sync && !data)) {nabu_log_io_reason="host";return -1;}
  if(!IOLockTryLock(host.lock)) {nabu_log_io_reason="busy";return 0;}
  int result=-1;
  if(!host.selected || host.poisoned || read32(host.hc,0x58) || (read32(host.hc,0x20)&fatalStatus)) {
    nabu_log_io_reason="transport-quarantined";IOLockUnlock(host.lock);return -1;
  }
  bzero(host.dma,dmaBytes);
  auto *utrd=reinterpret_cast<uint32_t*>(host.dma);auto *ucd=host.dma+commandOffset;
  if(!b5qLogRequest(utrd,ucd,host.physical,host.lun,host.capacity[host.lun],&nabu_log_volume,write,sync,lba,blocks)) {
    nabu_log_io_reason="request-gate";IOLockUnlock(host.lock);return -1;
  }
  uint32_t bytes=sync?0:blocks*4096;
  host.commandLun=host.lun;host.opcode=ucd[16];host.commandLba=lba;
  host.stage=sync?"log SYNC10":write?"log WRITE10 FUA":"log READ10";
  if(write)nb_copy(host.dma+dataOffset,data,bytes);
  if(submit()) {
    bool valid=response(ucd+responseOffset,host.lastOcs,host.lun,bytes,host.status);
    if(!valid)host.poisoned=true;
    if(valid && host.status.exact) {result=1;if(!write && bytes)nb_copy(data,host.dma+dataOffset,bytes);}
    // A valid temporary SCSI refusal is not a bad transport. Retry only reads;
    // journal writes and cache flushes retain their original failure behavior.
    else if(valid && !write && !sync && retryable(host.status))result=-2;
    write32(host.hc,0x20,1);
  }
  nabu_log_io_scsi=host.status.scsi;nabu_log_io_result=result;
  nabu_log_io_reason=result==1?"ok":result==-2?"retryable-read":"transport";
  IOLockUnlock(host.lock);return result;
}
/* Keep the counter deadline, but give each priority depression an expiry.
 * XNU's zero-ms yield has no restoration timer and can starve forever under
 * continuous single-CPU load, before this loop gets to check its deadline. */
static void nabuLogPause(unsigned milliseconds)
{
  uint64_t deadline;
  clock_interval_to_deadline(milliseconds,kMillisecondScale,&deadline);
  unsigned budget=milliseconds>1000?1000000:milliseconds*1000;
  do {
    thread_yield_internal(1);
  } while(budget-- && mach_absolute_time()<deadline);
}
static int nabuLogRead(void *,uint64_t lba,uint32_t blocks,uint8_t *data)
{
  /* The metadata verifier never blocks behind a mutex held by a stopped CPU.
   * Bound the retries by both iterations and monotonic time: before timer
   * services are proved, IOSleep may not space the attempts at all, and a
   * count-only budget could then be consumed within microseconds. */
  uint64_t deadline;
  clock_interval_to_deadline(50,kMillisecondScale,&deadline);
  unsigned transient=0;
  for(unsigned attempt=0;attempt<1000;attempt++) {
    int result=nabuLogIo(false,lba,blocks,data);
    if(result==1)return 1;
    if(result<0 && result!=-2)return 0;
    if(result==-2 && ++transient==3)return 0;
    if(mach_absolute_time()>=deadline) break;
    nabuLogPause(result==-2?10:1);
  }
  return 0;
}
static int nabuLogTokenParse(uint8_t token[16]) {return b5qLogArgs(PE_boot_args(),token)?0:1;}
static const char *nabuLogTokenReason(int reason) {return reason?"missing-or-invalid-b5q-log-args":"ok";}
#define NB_TOKEN_OK 0
static int nabuLogSlot(unsigned slot,uint8_t *header) {
  uint64_t base=nabu_log_volume.file_first+1+(uint64_t)slot*(NB_LOG_SLOT_BYTES/4096);
  if(!nabuLogRead(nullptr,base,1,header)) return -1;
  if(!nb_slot_valid(header,nabu_log_volume.token)) return 0;
  uint32_t length=nb_le32(header+72),blocks=(length+4095)/4096;
  for(unsigned at=0;at<blocks;) {
    unsigned n=blocks-at>16?16:blocks-at;
    if(!nabuLogRead(nullptr,base+1+at,n,nabu_log_payload+at*4096)) return -1;
    at+=n;
  }
  return nb_crc(nabu_log_payload,length)==nb_le32(header+76);
}
static void nabuLogThread(void *,wait_result_t)
{
  uint8_t token[16],boot[16];
  const char *stop_reason="unspecified";
  {
    int gate=nabuLogTokenParse(token);
    if(gate!=NB_TOKEN_OK) {
      IOLog("B5QLOG2: writer thread token gate detail=%s\n",nabuLogTokenReason(gate));
      stop_reason="token-gate";goto stop;
    }
  }
  nabu_log_writer_state=1;
  IOLog("B5QLOG2: writer entered; counter-paced scheduling; opening volume\n");
  thread_yield_internal(1); /* finite priority depression while root I/O runs */
  {
    bool opened=false;
    uint64_t open_deadline;
    clock_interval_to_deadline(30000,kMillisecondScale,&open_deadline);
    unsigned attempts=0;
    stop_reason="volume-open";
    for(;attempts<30;attempts++) {
      if(nb_volume_open(&nabu_log_volume,nabuLogRead,nullptr,host.capacity[host.lun],token)) {opened=true;break;}
      IOLog("B5QLOG2: volume open failed attempt=%u reason=%s lba=%u blocks=%u reads=%u poisoned=%u ready=%u\n",
            attempts+1,nb_volume_failure_name(nabu_log_volume.failure),
            (unsigned)nabu_log_volume.failure_lba,nabu_log_volume.failure_blocks,
            nabu_log_volume.reads,host.poisoned?1u:0u,host.selected?1u:0u);
      if(host.poisoned || !host.selected) {stop_reason="transport-unavailable";break;}
      if(mach_absolute_time()>=open_deadline) {stop_reason="open-deadline";break;}
      nabuLogPause(1000);
    }
    if(!opened) goto stop;
    IOLog("B5QLOG2: volume verified attempts=%u reads=%u esp=%u..%u file_first=%u\n",
          attempts+1,nabu_log_volume.reads,(unsigned)nabu_log_volume.esp_first,
          (unsigned)(nabu_log_volume.esp_first+nabu_log_volume.esp_blocks),
          (unsigned)nabu_log_volume.file_first);
    /* nb_volume_open already proves exact ESP/root bounds and disjointness. */
  }
  {
    int valid[2]={0,0};
    for(unsigned i=0;i<2;i++) {
      valid[i]=nabuLogSlot(i,nabu_log_headers[i]);
      if(valid[i]<0) {
        IOLog("B5QLOG2: slot read failed slot=%u\n",i);
        stop_reason="slot-read";goto stop;
      }
    }
    uint64_t sequence=0;unsigned newest=1;
    for(unsigned i=0;i<2;i++) if(valid[i] && nb_le64(nabu_log_headers[i]+24)>sequence) {sequence=nb_le64(nabu_log_headers[i]+24);newest=i;}
    /* Do not initialise over two damaged, previously committed headers. */
    if(!valid[0] && !valid[1]) {
      uint8_t zero[4096]={0};
      if(!nb_equal(zero,nabu_log_headers[0],4096) || !nb_equal(zero,nabu_log_headers[1],4096)) {
        IOLog("B5QLOG2: refusing to overwrite two non-zero invalid slots\n");
        stop_reason="damaged-slots";goto stop;
      }
    }
    uint64_t ticks=mach_absolute_time();
    nb_put64(boot,ticks);nb_put64(boot+8,sequence+1);
    IOLog("B5QLOG2: RAM console capture; validated preallocated ESP file; periodic writer ready\n");
    nabu_log_writer_state=2;
    uint64_t last_end=~0ULL,last_lost=~0ULL;
    unsigned snapshot_stalls=0,copy_stalls=0;
    for(;;) {
      struct nb_log_snapshot snapshot;
      if(!nabu_capture_snapshot(&snapshot)) {
        if(snapshot_stalls++==300)
          IOLog("B5QLOG2: capture snapshot unavailable for ~30s; writer still retries\n");
        nabuLogPause(100);continue;
      }
      snapshot_stalls=0;
      if(sequence==~0ULL) {stop_reason="sequence-exhausted";goto stop;}
      if(snapshot.end==last_end && snapshot.lost==last_lost) {nabuLogPause(1000);continue;}
      bool complete=true;
      for(unsigned at=0;at<snapshot.length;at+=1024) {
        unsigned n=snapshot.length-at>1024?1024:snapshot.length-at;
        if(!nabu_capture_copy(snapshot.first+at,n,nabu_log_payload+at)) {complete=false;break;}
      }
      if(!complete) {
        if(copy_stalls++==300)
          IOLog("B5QLOG2: capture copy rejected for ~30s end=%u lost=%u; writer still retries\n",
                (unsigned)snapshot.end,(unsigned)snapshot.lost);
        nabuLogPause(100);continue;
      }
      copy_stalls=0;
      unsigned padded=(snapshot.length+4095)&~4095u;
      nb_zero(nabu_log_payload+snapshot.length,padded-snapshot.length);
      nb_zero(nabu_log_header,4096);nb_copy(nabu_log_header,"NABULOG2",8);
      nb_put32(nabu_log_header+8,2);nb_put32(nabu_log_header+12,4096);
      nb_put32(nabu_log_header+16,1);nb_put32(nabu_log_header+20,NB_LOG_CAPACITY);
      nb_put64(nabu_log_header+24,sequence+1);nb_copy(nabu_log_header+32,boot,16);
      nb_put64(nabu_log_header+48,snapshot.end);nb_put64(nabu_log_header+56,snapshot.lost);
      nb_put64(nabu_log_header+64,snapshot.first);nb_put32(nabu_log_header+72,snapshot.length);
      nb_put32(nabu_log_header+76,nb_crc(nabu_log_payload,snapshot.length));
      nb_put64(nabu_log_header+88,snapshot.first);nb_copy(nabu_log_header+96,token,16);
      nb_copy(nabu_log_header+112,nabu_log_build_id,32);
      nb_put32(nabu_log_header+80,nb_header_crc(nabu_log_header,80));
      unsigned slot=newest^1u;
      uint64_t base=nabu_log_volume.file_first+1+(uint64_t)slot*(NB_LOG_SLOT_BYTES/4096);
      int result=1;const char *phase="payload";uint64_t fail_lba=base+1;unsigned fail_blocks=0;
      if(!nabu_log_writer_rounds)
        IOLog("B5QLOG2: first commit attempt slot=%u bytes=%u\n",slot,snapshot.length);
      for(unsigned at=0;at<padded/4096 && result==1;) {
        unsigned n=padded/4096-at>16?16:padded/4096-at;
        fail_lba=base+1+at;fail_blocks=n;
        result=nabuLogIo(true,fail_lba,n,nabu_log_payload+at*4096);at+=n;
      }
      /* The old active slot remains intact if payload/sync/header fails. */
      if(result==1) {phase="sync";result=nabuLogIo(false,base,NB_LOG_SLOT_BYTES/4096,nullptr,true);}
      if(result==1) {phase="header";fail_lba=base;fail_blocks=1;result=nabuLogIo(true,base,1,nabu_log_header);}
      if(result==1) {phase="sync";fail_lba=base;fail_blocks=NB_LOG_SLOT_BYTES/4096;result=nabuLogIo(false,base,NB_LOG_SLOT_BYTES/4096,nullptr,true);}
      if(result<0) {
        IOLog("B5QLOG2: commit failed slot=%u phase=%s lba=%u blocks=%u io=%s result=%x scsi=%x; old slot preserved\n",
              slot,phase,(unsigned)fail_lba,fail_blocks,nabu_log_io_reason,
              (unsigned)nabu_log_io_result,nabu_log_io_scsi);
        stop_reason="commit-write";goto stop;
      }
      if(result==1) {
        bool first=nabu_log_writer_rounds==0;
        newest=slot;sequence++;last_end=snapshot.end;last_lost=snapshot.lost;
        __atomic_store_n(&nabu_log_committed_end,snapshot.end,__ATOMIC_RELEASE);
        __atomic_fetch_add(&nabu_log_writer_rounds,1u,__ATOMIC_RELAXED);
        if(first) IOLog("B5QLOG2: first snapshot committed slot=%u bytes=%u\n",slot,snapshot.length);
      }
      nabuLogPause(1000);
    }
  }
stop:
  nabu_log_writer_state=3;__atomic_fetch_add(&nabu_log_writer_failures,1u,__ATOMIC_RELAXED);
  IOLog("B5QLOG2: writer stopped reason=%s; RAM capture continues; no fallback write window\n",stop_reason);
  thread_terminate(current_thread());
}
static void nabuLogStart(void) {
  uint8_t token[16];
  if(nabu_log_writer_state) {
    IOLog("B5QLOG2: start skipped reason=already-started state=%u\n",nabu_log_writer_state);
    return;
  }
  int gate=nabuLogTokenParse(token);
  if(gate!=NB_TOKEN_OK) {
    IOLog("B5QLOG2: start skipped reason=token-gate detail=%s\n",nabuLogTokenReason(gate));
    return;
  }
  nabu_log_volume_ptr=static_cast<nb_log_volume *>(IOMalloc(sizeof(nb_log_volume)));
  nabu_log_payload=static_cast<uint8_t *>(IOMalloc(NB_LOG_CAPACITY));
  if(!nabu_log_volume_ptr || !nabu_log_payload) {
    if(nabu_log_volume_ptr)IOFree(nabu_log_volume_ptr,sizeof(nb_log_volume));
    if(nabu_log_payload)IOFree(nabu_log_payload,NB_LOG_CAPACITY);
    nabu_log_volume_ptr=nullptr;nabu_log_payload=nullptr;
    nabu_log_writer_state=3;IOLog("B5QLOG2: logger buffer allocation failed; RAM capture continues\n");return;
  }
  bzero(nabu_log_volume_ptr,sizeof(nb_log_volume));
  thread_t thread=nullptr;
  nabu_log_writer_state=1;
  if(kernel_thread_start(nabuLogThread,nullptr,&thread)==KERN_SUCCESS) {
    thread_deallocate(thread);
    IOLog("B5QLOG2: writer thread created lun_blocks=%u\n",(unsigned)host.capacity[host.lun]);
  }
  else {
    nabu_log_writer_state=3;__atomic_fetch_add(&nabu_log_writer_failures,1u,__ATOMIC_RELAXED);
    IOLog("B5QLOG2: writer thread start failed; RAM capture continues\n");
  }
}
