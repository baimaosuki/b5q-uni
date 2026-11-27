#!/usr/bin/env python3
"""Exercise review12 production helpers and the applied ArmCpu/XNU patches."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import tomllib

R = Path(__file__).resolve().parents[2]
P = R / 'UniXNU-b5q/package'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--out', type=Path, default=Path(os.environ.get('B5Q_GATE_WORK', R / 'artifacts/b5q-review12-local')))
W = parser.parse_args().out.resolve()
W.mkdir(parents=True, exist_ok=True)
checks = []


def function(text, signature):
    start = text.index(signature)
    brace = text.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


def execute(name, command, **kwargs):
    result = subprocess.run(list(map(str, command)), cwd=R, capture_output=True, text=True, **kwargs)
    (W / (name + '.log')).write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(name + ':\n' + result.stdout + result.stderr)
    checks.append(dict(name=name, passed=True, log_sha256=hashlib.sha256((result.stdout + result.stderr).encode()).hexdigest()))
    print('PASS', name, flush=True)
    return result.stdout


def model(t, name, source, cpp=False):
    path = t / (name + ('.cpp' if cpp else '.c'))
    path.write_text(source)
    binary = t / name
    execute(name + '-compile', ['c++' if cpp else 'cc', '-std=c++17' if cpp else '-std=gnu11',
                               '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                               '-fno-omit-frame-pointer', '-pthread', str(path), '-o', str(binary)])
    execute(name + '-ASan-UBSan', [binary])


patch = R / 'UniXNU-b5q/patches/tools/b5q-armcpu-spi-ipi-lock.patch'
upstream_before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in
                   [R / 'UniXNU/drivers/ArmCpu/ArmCpu.cpp', R / 'sources/UniXNU/drivers/ArmCpu/ArmCpu.cpp']}
for root in ['UniXNU', 'sources/UniXNU']:
    execute(root.replace('/', '-') + '-apply-check', ['git', '-C', R / root, 'apply', '--check', patch])
workflow = (R / '.github/workflows/b5q-p0-p5.yml').read_text()
step = workflow.split('- name: Resolve full b5q target', 1)[1].split('\n      - name:', 1)[0]
assert step.index('./unixnu tree ') < step.index('git -C out/b5q/macos-27.3-26C5035r/b5q_macos/tree/drivers/ArmCpu apply -p3 ')
assert '"$GITHUB_WORKSPACE/UniXNU-b5q/patches/tools/b5q-armcpu-spi-ipi-lock.patch"' in step

with tempfile.TemporaryDirectory(prefix='review12-', dir=W) as td:
    t = Path(td)
    target = t / 'drivers/ArmCpu/ArmCpu.cpp'
    target.parent.mkdir(parents=True)
    shutil.copyfile(R / 'UniXNU/drivers/ArmCpu/ArmCpu.cpp', target)
    applied = execute('ArmCpu-zero-fuzz', ['patch', '-p1', '--fuzz=0', '-d', t, '-i', patch])
    assert 'offset' not in applied and 'fuzz' not in applied
    arm = target.read_text()
    # A clean CI resolves ArmCpu as its own checkout, not an in-tree file.
    # Exercise exactly that layout and the workflow's -p3 application.
    resolved = t / 'resolved-ArmCpu'
    resolved.mkdir()
    shutil.copyfile(R / 'UniXNU/drivers/ArmCpu/ArmCpu.cpp', resolved / 'ArmCpu.cpp')
    subprocess.run(['git', 'init', '-q', str(resolved)], check=True)
    execute('ArmCpu-resolved-module-apply', ['git', '-C', resolved, 'apply', '-p3', patch])
    assert (resolved / 'ArmCpu.cpp').read_text() == arm
    prepare = function(arm, 'bool ArmCpu::prepareGic (')
    spi = function(arm, 'static void spiIpiConfigure (')
    enable = function(arm, 'void ArmCpu::enableGic (')
    thread = function(arm, 'void ArmCpu::startThread (')
    start = function(arm, 'bool ArmCpu::start (')
    assert spi.index('distLock ();') < spi.index('read32 (') < spi.index('distUnlock ();')
    rmw = 'write32 (dist, 0, read32 (dist, 0) | 0x12U);'
    assert enable.index('distLock ();') < enable.index(rmw) < enable.index('distUnlock ();')
    assert prepare.index('initDistributor ()') < prepare.index('distLock ();') < prepare.index('0xaaaaaaaaU')
    assert start.index('gSmpStartLock = IOLockAlloc ();') < start.index('drainPending ();', start.index('gSmpStartLock ='))
    assert thread.index('IOLockLock (gSmpStartLock)') < thread.index('processor_start (self->machProcessor)') < thread.index('IOLockUnlock (gSmpStartLock)')
    assert 'distLock' not in thread and '__atomic_add_fetch (&armcpu_smp_running, 1U, __ATOMIC_RELAXED)' in arm
    locks = function(arm, 'static inline void distLock (') + '\n' + function(arm, 'static inline void distUnlock (')
    host = locks + '\n' + spi + '\n' + prepare.replace('ArmCpu::prepareGic', 'prepareGic')
    host = host.replace('__asm__ volatile ("yield" ::: "memory");', 'std::this_thread::yield ();')
    host = host.replace('__asm__ volatile ("dsb sy" ::: "memory");', '__atomic_thread_fence (__ATOMIC_SEQ_CST);')
    ctl = enable[enable.index('    distLock ();'):enable.index('    distUnlock ();') + len('    distUnlock ();')]
    ctl = ctl.replace('__asm__ volatile ("dsb sy" ::: "memory");', '__atomic_thread_fence (__ATOMIC_SEQ_CST);')
    model(t, 'gicd-concurrent', r'''
#include <cassert>
#include <cstdint>
#include <thread>
#include <vector>
#include <mutex>
#include <atomic>
static volatile uint32_t gDistLock=0;
static volatile uint32_t armcpu_smp_running=0;
static const uint32_t kIpiSpiBase=1008;
static uint32_t regs[0x10000/4];static uint64_t routes[8];
static uintptr_t dist=0;static bool gSpiIpi=true;static unsigned gGicShared=0;
bool mapGic(){return true;}bool initDistributor(){return true;}bool wakeRedistributor(bool){return true;}
uint32_t read32(uintptr_t,unsigned at){auto v=regs[at/4];std::this_thread::yield();return v;}
void write32(uintptr_t,unsigned at,uint32_t v){
 if(at==0x100+(1008/32)*4)regs[at/4]|=v;else regs[at/4]=v;}
void write64(uintptr_t,unsigned at,uint64_t v){assert(at>=0x6000+1008*8&&at<0x6000+1016*8);routes[(at-0x6000)/8-1008]=v;}
HELPERS
void enableShared(){CTL}
int main(){
 for(unsigned round=0;round<20;round++){
  for(auto &r:regs){r=0;}assert(prepareGic()&&gGicShared);
  assert((regs[(0x80+31*4)/4]&0x00ff0000)==0x00ff0000);
  assert(regs[(0xc00+63*4)/4]==0xaaaaaaaa);
  std::vector<std::thread> threads;__atomic_store_n(&armcpu_smp_running,0u,__ATOMIC_RELAXED);
  for(unsigned core=0;core<8;core++)threads.emplace_back([&,core]{
   for(unsigned n=0;n<100;n++){spiIpiConfigure(0,core,core);enableShared();
    distLock();assert((regs[(0x80+31*4)/4]&0x00ff0000)==0x00ff0000);
    assert(regs[(0xc00+63*4)/4]==0xaaaaaaaa);distUnlock();}
   const bool boot=true;COUNT
  });
  for(auto &thread:threads){thread.join();}assert(armcpu_smp_running==8);
  assert((regs[0]&0x12)==0x12&&regs[(0x100+31*4)/4]==0x00ff0000);
  assert(regs[(0x400+252*4)/4]==0x80808080&&regs[(0x400+253*4)/4]==0x80808080);
  for(unsigned core=0;core<8;core++)assert(routes[core]==core);
  // Resume/rebuild must also work with zeroed shared words: preconfiguration
  // must not conceal a missing lock in spiIpiConfigure itself.
  regs[(0x80+31*4)/4]=0;regs[(0xc00+63*4)/4]=0;regs[0]=0;threads.clear();
  for(unsigned core=0;core<8;core++)threads.emplace_back([core]{
   for(unsigned n=0;n<100;n++){spiIpiConfigure(0,core,core);enableShared();}
  });
  for(auto &thread:threads){thread.join();}
  assert((regs[(0x80+31*4)/4]&0x00ff0000)==0x00ff0000);
  assert(regs[(0xc00+63*4)/4]==0x0000aaaa&&(regs[0]&0x12)==0x12);
 }
 // Exercise the production sleepable wrapper around a blocking processor_start.
 std::mutex mutex;using IOLock=std::mutex;IOLock *gSmpStartLock=&mutex;
 auto IOLockLock=[](IOLock*p){p->lock();};auto IOLockUnlock=[](IOLock*p){p->unlock();};
 std::atomic<unsigned> active{0},total{0};
 auto processor_start=[&](unsigned){assert(active.fetch_add(1)==0);std::this_thread::yield();assert(active.fetch_sub(1)==1);total++;};
 std::vector<std::thread> workers;
 for(unsigned cpu=1;cpu<8;cpu++)workers.emplace_back([&,cpu]{
  struct{unsigned machProcessor;}value{cpu};auto*self=&value;
  START
 });
 for(auto &thread:workers){thread.join();}assert(total==7);
}
'''.replace('HELPERS', host).replace('CTL', ctl).replace('START', thread[thread.index('  if (gSmpStartLock)'):thread.index('  // Once every secondary')]).replace('COUNT', next(line.strip() for line in arm.splitlines() if '__atomic_add_fetch (&armcpu_smp_running,' in line)), cpp=True)

    # Compile the complete patched production driver, preserving upstream trees.
    sdk = R / 'tools/macos-sdk/MacOSX26.5.sdk'
    include = t / 'include'
    for rel, text in [('libkern/c++/OSMetaClass.h', (sdk / 'System/Library/Frameworks/Kernel.framework/Headers/libkern/c++/OSMetaClass.h').read_text().replace('#if TARGET_OS_IPHONE && !TARGET_OS_SIMULATOR', '#if !XNU_TARGET_OS_OSX').replace('#if TARGET_OS_OSX && defined(__arm64__)', '#if XNU_TARGET_OS_OSX && defined(__arm64__)')),
                      ('os/base.h', (sdk / 'System/Library/Frameworks/Kernel.framework/Headers/os/base.h').read_text().replace(', "authenticates-null-values"', ''))]:
        p = include / rel;p.parent.mkdir(parents=True, exist_ok=True);p.write_text(text)
    compiler = R / 'tools/llvm21/usr/lib/llvm-21/bin/clang++'
    env = dict(os.environ, LD_LIBRARY_PATH=str(R / 'tools/llvm21/usr/lib/x86_64-linux-gnu'))
    flags = ['-target', 'arm64e-apple-ios27.0', '-O2', '-isysroot', str(sdk), '-std=gnu++17',
             '-fptrauth-calls', '-fptrauth-returns', '-fptrauth-intrinsics', '-fptrauth-function-pointer-type-discrimination',
             '-fno-c++-static-destructors', '-fno-exceptions', '-fno-rtti', '-fno-common', '-fapple-kext',
             '-ffreestanding', '-mgeneral-regs-only', '-nostdinc++', '-D__PTRAUTH_INTRINSICS__=1',
             '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter', '-Wno-incompatible-sysroot', '-Wno-deprecated-declarations']
    flags += ['-D' + name + '=1' for name in ['KERNEL', 'KERNEL_PRIVATE', 'DRIVER_PRIVATE', 'XNU_KERNEL_PRIVATE', 'XNU_TARGET_OS_OSX', 'PRIVATE', 'MACH_KERNEL_PRIVATE']]
    # The SDK omits these kernel-private declarations; take the complete
    # topology types and exact IRQ declaration from the pinned XNU source.
    xnu = R / 'sources/UniXNU/out/feeds/xnu-3199e8bc/osfmk'
    routines = (xnu / 'arm/machine_routines.h').read_text()
    decl = routines[routines.index('void ml_install_interrupt_handler('):]
    decl = decl[:decl.index(';') + 1]
    private = include / 'armcpu-private.h'
    types = (xnu / 'kern/kern_types.h').read_text()
    pset = next(line for line in types.splitlines() if line.startswith('typedef ') and 'pset_id_t;' in line)
    private.write_text('#include <IOKit/IOCPU.h>\n' + pset + '\n#include "' + str(xnu / 'arm/cpu_topology.h') + '"\nextern "C" {\n' + decl + '\n}\n')
    flags += ['-include', str(private)]
    for directory in [include, sdk / 'System/Library/Frameworks/Kernel.framework/Headers',
                      R / 'sources/UniXNU/out/feeds/xnu-3199e8bc/iokit',
                      R / 'sources/UniXNU/out/feeds/xnu-3199e8bc/pexpert', R / 'UniXNU/drivers/ArmCpu']:
        flags += ['-I', str(directory)]
    obj = W / 'ArmCpu.o'
    execute('ArmCpu-arm64e', [compiler, *flags, '-c', target, '-o', obj], env=env)
    sys_path = str(R / 'UniXNU/scripts')
    import sys
    sys.path[:0] = [sys_path, str(R / 'UniXNU-b5q/scripts')]
    os.environ.update(UNIXNU_XNU_ARCH='arm64e', UNIXNU_IOS_VERSION='27.0')
    import kernel_target
    from b5q_abi import object_symbols
    kernel_target.check_object(obj.read_bytes(), 'patched ArmCpu')
    exports = {n for n, _, kind in object_symbols(obj.read_bytes()) if kind & 14}
    assert '__ZN6ArmCpu9interruptEv' in exports and '_armcpu_spi_attach' in exports

    # Apply the real patch and test copy faults, zero syscall return, and logging budget.
    mac = t / 'security/mac_base.c';mac.parent.mkdir()
    shutil.copyfile(R / 'sources/UniXNU/out/feeds/xnu-3199e8bc/security/mac_base.c', mac)
    execute('AMFI-real-patch', ['patch', '-p1', '-d', t, '-i', R / 'UniXNU-b5q/patches/xnu/b5q-amfi-lwcr.patch'])
    patched = mac.read_text()
    helper = patched[patched.index('struct b5q_amfi_constraint_args {'):patched.index('\n#if CONFIG_MACF', patched.index('struct b5q_amfi_constraint_args {'))]
    model(t, 'amfi-boundaries', r'''
#include <assert.h>
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
typedef uint64_t user_addr_t;typedef int32_t SInt32;struct proc{int pid;};typedef struct proc*proc_t;
struct __mac_syscall_args{const char*policy;int call;user_addr_t arg;};
#define MAXCOMLEN 16
static int enabled=1,parse_ok=1,copyouts,logs;static user_addr_t bad_in,bad_out;static char observed[1024];
static int PE_parse_boot_argn(const char*n,void*p,int z){assert(!strcmp(n,"no-lc")&&z==4);*(uint32_t*)p=enabled;return parse_ok;}
static int copyin(user_addr_t p,void*out,size_t n){if(p==bad_in)return 14;memcpy(out,(void*)(uintptr_t)p,n);return 0;}
static int copyout(const void*in,user_addr_t p,size_t n){if(p==bad_out)return 14;assert(n==0x404);copyouts++;memcpy((void*)(uintptr_t)p,in,n);return 0;}
static SInt32 OSIncrementAtomic(volatile SInt32*p){return __atomic_fetch_add(p,1,__ATOMIC_RELAXED);}
static int proc_pid(proc_t p){return p->pid;}static void proc_name(int p,char*b,int n){snprintf(b,n,"p%d",p);}
static int record(const char*format,...){va_list ap;va_start(ap,format);int n=vsnprintf(observed,sizeof observed,format,ap);va_end(ap);logs++;return n;}
#define printf record
#define bzero(p,n) memset((p),0,(n))
HELPER
int main(){struct proc p={42};struct b5q_amfi_constraint_error e;
 struct b5q_amfi_constraint_args a={0};a.error_out=(uintptr_t)&e;a.error_out_size=sizeof e;
 struct __mac_syscall_args u={"AMFI",102,(uintptr_t)&a};
 memset(&e,0xaa,sizeof e);e.error_code=7;memcpy(e.message,"bad\n\001reason",12);
 assert(b5q_amfi_constraint_override(&p,&u,"AMFI",0));
 for(unsigned i=0;i<sizeof e;i++)assert(!((unsigned char*)&e)[i]);
 assert(copyouts==1&&logs==1&&strstr(observed,"ret=0 error-code=7 override=1 msg=bad..reason"));
 memset(&e,0xaa,sizeof e);e.error_code=0;struct b5q_amfi_constraint_error unchanged=e;
 assert(!b5q_amfi_constraint_override(&p,&u,"AMFI",0));assert(!memcmp(&e,&unchanged,sizeof e)&&copyouts==1&&logs==1);
 e.error_code=19;assert(b5q_amfi_constraint_override(&p,&u,"AMFI",5));assert(!e.error_code&&copyouts==2);
 bad_in=a.error_out;assert(!b5q_amfi_constraint_override(&p,&u,"AMFI",0));assert(copyouts==2);
 assert(b5q_amfi_constraint_override(&p,&u,"AMFI",5));assert(strstr(observed,"error-code=-1"));bad_in=0;
 e.error_code=7;assert(!b5q_amfi_constraint_override(&p,&u,"Other",5));
 u.call=101;assert(!b5q_amfi_constraint_override(&p,&u,"AMFI",5));u.call=102;
 a.error_out_size=4;assert(!b5q_amfi_constraint_override(&p,&u,"AMFI",5));a.error_out_size=0x404;
 enabled=0;assert(!b5q_amfi_constraint_override(&p,&u,"AMFI",5));enabled=1;
 parse_ok=0;assert(!b5q_amfi_constraint_override(&p,&u,"AMFI",5));parse_ok=1;
 bad_in=u.arg;assert(!b5q_amfi_constraint_override(&p,&u,"AMFI",5));bad_in=0;
 a.error_out=0;assert(!b5q_amfi_constraint_override(&p,&u,"AMFI",5));a.error_out=(uintptr_t)&e;
 bad_out=a.error_out;assert(!b5q_amfi_constraint_override(&p,&u,"AMFI",5));bad_out=0;
 for(int i=0;i<64;i++){memset(&e,0xff,sizeof e);e.error_code=7;assert(b5q_amfi_constraint_override(&p,&u,"AMFI",0));assert(!e.error_code);}
 assert(logs==32&&copyouts==67);return 0;}
'''.replace('HELPER', helper))
    syscall = function(patched, '__mac_syscall(proc_t p,')
    assert syscall.index('mpo_policy_syscall') < syscall.index('b5q_amfi_constraint_override')

    ath = (P / 'B5qAth11k.c').read_text()
    sram = function(ath, 'static void b5q_sram_assert_dump(')
    constants = ath[ath.index('#define B5Q_WCN6855_ASSERT_PC_ADDR'):ath.index('static void b5q_sram_assert_dump(')]
    assert 'ab->pci.ops->window_read32' in sram
    for forbidden in ['ath11k_pcic_read32', 'ath11k_pcic_read(', 'wakeup']:
        assert forbidden not in sram
    dump = function(ath, 'static void b5q_ath11k_dump_state(')
    fatal = function(ath, 'void b5q_ath11k_mhi_failed(')
    assert dump.index('b5q_ce_dump(ab,3)') < dump.index('b5q_sram_assert_dump(ab,status)')
    assert fatal.index('b5q_ath11k_dump_state(') < fatal.index('ATH11K_FLAG_CRASH_FLUSH')
    assert 'b5q_ath11k_dump_state' in function(ath, 'void b5q_ath11k_wmi_timeout(')
    model(t, 'sram-assert', r'''
#include <assert.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
typedef uint32_t u32;
struct ath11k_base;struct pci_ops{u32(*window_read32)(struct ath11k_base*,u32);};
struct ath11k_base{void*mem;struct{struct pci_ops*ops;}pci;};
static unsigned reads,logs;static unsigned char payload[64];static char message[256];
CONSTANTS
static u32 read_window(struct ath11k_base*ab,u32 at){assert(ab&&ab->mem);reads++;
 if(at==B5Q_WCN6855_ASSERT_PC_ADDR)return 0x1520c2c;
 if(at==B5Q_WCN6855_ASSERT_FMT_ADDR)return 0x1520000;
 if(at==B5Q_WCN6855_ASSERT_LINE_ADDR)return 2742;
 assert(at>=B5Q_WCN6855_ASSERT_MSG_ADDR&&at<B5Q_WCN6855_ASSERT_MSG_ADDR+64&&(at&3)==0);
 unsigned i=at-B5Q_WCN6855_ASSERT_MSG_ADDR;return payload[i]|(u32)payload[i+1]<<8|(u32)payload[i+2]<<16|(u32)payload[i+3]<<24;}
static void lx_log(unsigned level,const char*format,...){assert(level==3);char out[256];va_list ap;va_start(ap,format);vsnprintf(out,sizeof out,format,ap);va_end(ap);logs++;
 if(strstr(format,"sram-assert-msg"))strcpy(message,out);else assert(strstr(out,"pc=01520c2c line=2742 fmt=01520000"));}
HELPER
int main(){struct pci_ops ops={read_window};struct ath11k_base ab={(void*)1,{&ops}};
 const char*text="Asserted in:0x1520c2c:0x1, line#2742";memcpy(payload,text,strlen(text)+1);
 b5q_sram_assert_dump(&ab,0xff05);assert(reads==19&&logs==2&&strstr(message,text));
 memset(payload,0,sizeof payload);payload[0]='A';payload[1]=1;payload[2]=0xff;payload[3]='Z';
 b5q_sram_assert_dump(&ab,0xff05);assert(!strcmp(message,"B5qWifi: sram-assert-msg='A..Z'"));
 memset(payload,'Q',sizeof payload);b5q_sram_assert_dump(&ab,0xff05);
 const char*begin=strchr(message,'\'')+1;assert(strlen(begin)==65&&begin[64]=='\'');
 unsigned previous=reads,oldlogs=logs;b5q_sram_assert_dump(&ab,UINT32_MAX);b5q_sram_assert_dump(0,0);
 ab.mem=0;b5q_sram_assert_dump(&ab,0);ab.mem=(void*)1;ab.pci.ops=0;b5q_sram_assert_dump(&ab,0);
 ab.pci.ops=&ops;ops.window_read32=0;b5q_sram_assert_dump(&ab,0);assert(reads==previous&&logs==oldlogs);}
'''.replace('CONSTANTS', constants).replace('HELPER', sram))

    usb = (P / 'QcomDwc3.cpp').read_text()
    configure = function(usb, 'void configureHostPorts(IOService *host) {')
    xhci = usb[usb.index('class QcomDwc3Xhci :'):usb.index('OSDefineMetaClassAndStructors(QcomDwc3Xhci,')]
    start = function(xhci, 'bool start(')
    assert start.index('if(started)') < start.index('restoreHostGlobals()') < start.index('configureHostPorts(this)')
    assert 'gHost' not in start and 'gHost' not in configure
    assert 'kUsbPortDebugOptions=0x40000119u' in usb
    assert 'host->setProperties(hostSettings)' in configure and '"B5qHostDebugApplied"' in configure
    assert 'port->setProperties(settings)' in configure and 'ensureHostPortHold(port)' in configure
    assert '"B5qPortPowerPinned"' in configure and 'kPortHoldAttached' in configure
    stats = function(usb, 'void hostStats() {')
    assert 'configureHostPorts(gHost)' in stats and 'dev->setProperties(settings)' in stats and '"B5qDevDebugApplied"' in stats
    assert 'changePowerStateTo' not in function(xhci, 'IOReturn setPowerState(')
    assert 'dmaDiagnostics(' not in function(xhci, 'void XHCI_WRITE64(')
    assert 'hostCheckpoint("first-write64",true)' in xhci and 'kHostEventDumpCount=16' in usb
    model(t, 'usb-port-power', r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <memory>
#include <map>
#include <string>
#include <vector>
struct OSObject{virtual ~OSObject()=default;};
static std::vector<std::unique_ptr<OSObject>> allocations;
template<class T>T*track(T*p){allocations.emplace_back(p);return p;}
struct OSNumber:OSObject{unsigned value;explicit OSNumber(unsigned n):value(n){}
 static OSNumber*withNumber(unsigned n,unsigned bits){assert(bits==32);return track(new OSNumber(n));}
 unsigned unsigned32BitValue(){return value;}};
struct OSDictionary:OSObject{std::map<std::string,OSObject*> values;
 static OSDictionary*withCapacity(unsigned n){assert(n==1);return track(new OSDictionary);}
 void setObject(const char*n,OSObject*p){values[n]=p;}};
struct OSIterator:OSObject{std::vector<OSObject*>values;unsigned pos=0;
 OSObject*getNextObject(){return pos<values.size()?values[pos++]:nullptr;}};
using IOReturn=unsigned;constexpr unsigned kIOReturnSuccess=0,kUsbPortDebugOptions=0x40000119u,kUsbHostDebugOptions=0x4000015du;
constexpr unsigned kXhciRegisterBytes=0x8000;static uint32_t registers[kXhciRegisterBytes/4]{};
static struct{uint32_t *va=registers;}gXhciRegs;
static OSObject yes;static OSObject*kOSBooleanTrue=&yes;static const char*gIOServicePlane="service";
static unsigned powerLogs,debugLogs,forceLogs;
template<class...T>void IOLog(const char*format,T...){if(strstr(format,"port-force-power"))forceLogs++;else if(strstr(format,"port-power"))powerLogs++;else debugLogs++;}
struct IOService:OSObject{
 std::map<std::string,OSObject*>props;std::vector<OSObject*>children;bool port=false,holdFail=false;
 unsigned debugCalls=0,forceCalls=0,powerCalls=0,state=2,powerError=0,debugError=0,forceError=0;
 const char*getName(){return port?"AppleUSB20XHCIPort":"host";}
 OSObject*getProperty(const char*n){auto it=props.find(n);return it==props.end()?nullptr:it->second;}
 void setProperty(const char*n,OSObject*p){props[n]=p;}
 void setProperty(const char*n,unsigned v,unsigned bits){setProperty(n,OSNumber::withNumber(v,bits));}
 IOReturn setProperties(OSDictionary*d){if(d->values.count("UsbForcePower")){forceCalls++;auto*n=dynamic_cast<OSNumber*>(d->values["UsbForcePower"]);assert(n&&n->value==1);return forceError;}debugCalls++;auto*n=dynamic_cast<OSNumber*>(d->values["kUSBDebugOptions"]);assert(n&&n->value==(port?kUsbPortDebugOptions:kUsbHostDebugOptions));return debugError;}
 OSObject*metaCast(const char*n){assert(!strcmp(n,"AppleUSBHostPort"));return port?this:nullptr;}
 OSIterator*getChildIterator(const char*plane){assert(plane==gIOServicePlane);auto*i=track(new OSIterator);i->values=children;return i;}
 unsigned long getPowerState(){return state;}
 IOReturn changePowerStateTo(unsigned long n){assert(n==3);powerCalls++;return powerError;}
};
enum PortHoldResult{kPortHoldAttached,kPortHoldPending,kPortHoldFailed};
static PortHoldResult ensureHostPortHold(IOService*p){return p->holdFail?kPortHoldFailed:kPortHoldAttached;}
static void setHostPortHoldOwner(IOService*){}
#define OSDynamicCast(T,p) dynamic_cast<T*>(p)
#define OSSafeReleaseNULL(p) do{(p)=nullptr;}while(0)
HELPER
int main(){
 registers[0]=0x40;registers[(0x40+0x400)/4]=1;
 configureHostPorts(nullptr);IOService host,port,other;port.port=true;host.children={&port,&other};
 configureHostPorts(&host);assert(host.debugCalls==1&&port.debugCalls==1&&port.forceCalls==0&&port.powerCalls==0);
 assert(port.getProperty("B5qPortPowerPinned")&&!port.getProperty("B5qPortForcePowerApplied")&&debugLogs==2&&forceLogs==0);
 port.state=3;configureHostPorts(&host);assert(host.debugCalls==1&&port.debugCalls==1&&port.forceCalls==0&&port.powerCalls==0);
 port.state=2;configureHostPorts(&host);assert(port.powerCalls==0);
 IOService delayed;delayed.port=true;delayed.state=3;host.children.push_back(&delayed);
 configureHostPorts(&host);assert(delayed.debugCalls==1&&delayed.forceCalls==0&&delayed.powerCalls==0&&delayed.getProperty("B5qPortPowerPinned"));
 IOService failed;failed.port=true;failed.holdFail=true;failed.powerError=5;failed.forceError=5;host.children.push_back(&failed);
 for(unsigned n=0;n<10;n++)configureHostPorts(&host);
 assert(!failed.getProperty("B5qPortPowerPinned")&&failed.forceCalls==4);
 failed.holdFail=false;failed.state=3;configureHostPorts(&host);assert(failed.getProperty("B5qPortPowerPinned"));
 unsigned tries=failed.forceCalls;configureHostPorts(&host);assert(failed.forceCalls==tries&&failed.powerCalls==0);
 assert(!other.debugCalls&&!other.powerCalls);
}
'''.replace('HELPER', '#include "'+str(P/'B5qUsbHostRole.h')+'"\n'+configure), cpp=True)
    checks.append(dict(name='USB-host-contracts', passed=True))

assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == digest for p, digest in upstream_before.items())
args = ' '.join(tomllib.loads((R / 'UniXNU-b5q/board.toml').read_text())['payload']['kernel_args']).encode()
assert len(args) == 1023
receipt = dict(passed=True, hardware_verified=False, checks=checks, upstream_ArmCpu_unchanged=upstream_before,
               patched_ArmCpu_object_sha256=hashlib.sha256((W / 'ArmCpu.o').read_bytes()).hexdigest(),
               tool_patch_sha256=hashlib.sha256(patch.read_bytes()).hexdigest(), kernel_args_bytes=len(args),
               sanitizer='address,undefined', GICD_threads=8, GICD_rounds=20, GICD_configs_per_thread=100,
               GICD_preconfigured_and_zeroed_resume_tested=True,
               full_XNU_linked=False, ci_triggered=False, image_generated=False, phone_accessed=False)
(W / 'review12-tests.json').write_text(json.dumps(receipt, indent=2) + '\n')
print('PASS review12 actual patches, eight-thread GICD, serialized starts, ArmCpu arm64e, AMFI boundaries, USB contracts and SRAM decoding')
