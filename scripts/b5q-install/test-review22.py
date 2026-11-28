#!/usr/bin/env python3
"""Review22 production helpers, actual DP poll, source policy and target compile."""
from pathlib import Path
import ast,hashlib,importlib.util,json,os,plistlib,shutil,subprocess,sys,tempfile,tomllib
R=Path(__file__).resolve().parents[2];P=R/'UniXNU-b5q/package';W=Path(os.environ.get('B5Q_GATE_WORK',R/'artifacts/b5q-review22-local')).resolve();W.mkdir(parents=True,exist_ok=True);checks=[]
sys.path.insert(0,str(R/'UniXNU-b5q/scripts'))
import b5q_display,b5q_identity

def fn(text,signature):
 a=text.index(signature);b=text.index('{',a)+1;depth=1
 while depth:depth+=(text[b]=='{')-(text[b]=='}');b+=1
 return text[a:b]
def run(name,command,env=None):
 p=subprocess.run(list(map(str,command)),cwd=R,env=env,capture_output=True,text=True);log=p.stdout+p.stderr;(W/(name+'.log')).write_text(log)
 if p.returncode:raise RuntimeError(name+'\n'+log[-6000:])
 checks.append(dict(name=name,passed=True,command=list(map(str,command)),log_sha256=hashlib.sha256(log.encode()).hexdigest()));print('PASS',name,flush=True)
def host(t,name,source):
 p=t/(name+'.cpp');p.write_text(source);o=t/name
 run(name+'-compile',['c++','-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-Wno-unused-parameter','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I',P,p,'-o',o]);run(name+'-ASan-UBSan',[o])
with tempfile.TemporaryDirectory(prefix='review22-',dir=W)as td:
 t=Path(td);tree=t/'tree'
 for component in ['AdrenoMetal','GopFramebuffer']:
  shutil.copytree(R/'UniXNU/drivers'/component,tree/'drivers'/component,ignore=shutil.ignore_patterns('.git','build','target','out'))
  subprocess.run(['git','init','--quiet',str(tree/'drivers'/component)],check=True)
 (tree/'scripts').mkdir();shutil.copyfile(R/'UniXNU/scripts/build-boot-runtime.py',tree/'scripts/build-boot-runtime.py')
 b5q_display.prepare(tree);newid=b5q_display.runtime_source_id(tree);b5q_display.prepare(tree);assert b5q_display.runtime_source_id(tree)==newid
 metal=(tree/'drivers/AdrenoMetal/NativeBridgeMetalFrontend.mm').read_text();caps=(tree/'drivers/AdrenoMetal/bridge/NativeMetalCapabilities.rs').read_text();purge=(tree/'drivers/AdrenoMetal/bridge/NativeMetalPurge.rs').read_text();bridge=(tree/'drivers/AdrenoMetal/bridge/NativeMetalBridge.rs').read_text();plugin=(tree/'drivers/AdrenoMetal/NativeAdrenoMetalPlugin.mm').read_text()
 for name in ['deviceLinearReadOnlyTextureAlignmentBytes','deviceLinearTextureAlignmentBytes','linearTextureAlignmentBytes','iosurfaceTextureAlignmentBytes','iosurfaceReadOnlyTextureAlignmentBytes']:assert name in caps
 assert '| "iosurfaceReadOnlyTextureAlignmentBytes" => 64' in caps
 assert 'minimum_linear_texture_alignment' in fn(caps,'pub(crate) fn linear_alignment(')
 assert 'RGBA16Float'not in fn(metal,'- (NSUInteger)iosurfaceReadOnlyTextureAlignmentBytes')
 assert 'if(isRenderServer())return;'in fn(metal,'static void watchBackgroundIdle(')
 assert 'native_bridge_metal_purge(1,4000)'in metal and 'noteBackgroundSubmit();'in fn(metal,'- (void)submit {')
 assert 'if !optional { registry.seed_driver_blobs(); }'in bridge and 'if optional { None } else { Some(runtime_cache) }'in bridge
 client=fn(plugin,'static id clientDevice(');assert 'if (!device) {\n        setenv("METAL2VULKAN_SHADER_CACHE_OPTIONAL"'in client
 # Rust host tests execute the production alignment and monotonic idle helpers.
 rust=fn(caps,'fn frontend_alignment(')+'\n'+fn(purge,'fn idle_enough(')+r'''
#[test]fn rows(){for(d,b)in[(256,4),(512,8),(64,1)]{let a=frontend_alignment(d,b);assert_eq!(a,64);for r in[10624,5696,4160,192,64]{assert_eq!(r%a,0);}}assert_eq!(frontend_alignment(192,12),192);assert_eq!(frontend_alignment(128,0),128);}
#[test]fn ages(){let t=Instant::now();let age=Duration::from_millis(4000);assert!(!idle_enough(t+Duration::from_millis(3999),t,age));assert!(idle_enough(t+age,t,age));assert!(!idle_enough(t,t+age,age));}
'''
 (t/'metal.rs').write_text('use std::time::{Instant,Duration};\n'+rust);run('metal-Rust-unit-compile',['rustc','--edition','2024','--test','-Dwarnings',t/'metal.rs','-o',t/'metal-rust']);run('metal-Rust-unit',[t/'metal-rust'])
 # The actual purge order protects live, NonVolatile, held, tied and pinned objects.
 sweep=fn(purge,'fn sweep(&self, cause: Cause, now: Instant, idle: Duration) -> Swept {')
 assert sweep.index('!discardable(slot.state)')<sweep.index('slot.object.take()') and sweep.index('self.holds.load')<sweep.index('slot.object.take()') and sweep.index('self.ties.load')<sweep.index('slot.object.take()')
 budget=fn(metal,'- (NSUInteger)recommendedMaxWorkingSetSize').replace('- (NSUInteger)recommendedMaxWorkingSetSize','static uint64_t budget()')
 host(t,'metal-idle-budget',r'''
#include <cstdint>
#include <cassert>
#include <algorithm>
using NSUInteger=unsigned long;static bool render;static uint64_t memory;static int failure;
bool isRenderServer(){return render;}int sysctlbyname(const char*,void*out,size_t*,void*,size_t){*(uint64_t*)out=memory;return failure;}
'''+budget+'\n'+fn(metal,'static bool backgroundIdleDue(')+r'''
int main(){memory=uint64_t(6410)<<20;render=false;assert(budget()==256ull<<20);render=true;assert(budget()==768ull<<20);memory=1024ull<<20;assert(budget()==256ull<<20);failure=1;assert(budget()==768ull<<20);
assert(!backgroundIdleDue(4000000,0,0));assert(!backgroundIdleDue(4000099,100,0));assert(backgroundIdleDue(4000100,100,0));assert(!backgroundIdleDue(5000000,100,100));assert(!backgroundIdleDue(99,100,0));assert(backgroundIdleDue(5000000,200,100));}
''')
 board=(P/'B5qUsbBoard.cpp').read_text();start=board.index('struct PdicIo {');end=board.index('extern "C" bool b5q_dp_port_poll',start);globals=board[start:end].rsplit('}',1)[0]
 poll=fn(board,'extern "C" bool b5q_dp_port_poll(');stop=fn(board,'extern "C" void b5q_dp_port_stop(')
 host(t,'dp-real-poll-prswap-attention-retry',r'''
#include <cstdint>
#include <cstring>
#include <cassert>
#include <cstdarg>
#include <vector>
#include "B5qMax77705.h"
#include "B5qDpPdic.h"
#include "B5qDpPort.h"
static uint64_t clockNs;uint64_t mach_absolute_time(){return clockNs;}void absolutetime_to_nanoseconds(uint64_t v,uint64_t*out){*out=v;}
void IOSleep(unsigned ms){clockNs+=uint64_t(ms)*1000000;}void IODelay(unsigned us){clockNs+=uint64_t(us)*1000;}void IOLog(const char*,...){}void IOLockLock(int*){}void IOLockUnlock(int*){}
struct Maxim{int *lock=nullptr;uint8_t cc0=0x42,cc1=0,pd=0x80,bc=0x80,pdIrq=0,vdmIrq=0,opcode=0,id=0;unsigned off=0,on=0,gets=0,statusRequests=0;bool timeout=false;
bool read(uint8_t a,uint8_t r,uint8_t&v){assert(a==0x25);switch(r){case 0x0a:v=cc0;break;case 0x0b:v=cc1;break;case 0x0d:v=pd;break;case 8:v=bc;break;case 4:v=pdIrq;pdIrq=0;break;case 5:v=vdmIrq;vdmIrq=0;break;default:assert(false);}return true;}
bool writeBuffer(uint8_t a,const uint8_t*d,unsigned n){assert(a==0x25&&n>=2);if(d[0]==0x21){opcode=d[1];if(opcode==0x55){if(d[2]==1)off++;else on++;}if(opcode==0x4b){id=d[2];gets++;}if(opcode==0x48&&(d[3]&31)==16)statusRequests++;}return true;}
bool readBuffer(uint8_t a,uint8_t r,uint8_t*d,unsigned n){assert(a==0x25);memset(d,0,n);if(r==2){assert(n==1);d[0]=timeout?0:128;}else if(r==0x51){assert(n==1);d[0]=opcode;}else if(r==0x52&&opcode==0x4b){uint8_t p[33]={0x4b,id,3};B5qDp::put32(p+4,0xff018000u|(id==6?0:64)|id);B5qDp::put32(p+8,2|128);memcpy(d,p+1,n);}return true;}};
static Maxim hardware;static Maxim *maxim=&hardware;bool openMaxim(){return true;}
'''+globals+poll+'\n'+stop+r'''
int main(){using A=B5qDp::AltMode;B5qDpPortState out{};B5qMax77705::Cable src;src.valid=true;src.cc0=0x42;src.pd=0x80;
dpStarted=true;dpCable=src.dpSessionSignature();dpAlt.phase=A::Phase::Active;dpAlt.pin=4;dpAlt.generation=8;dpStatusAt=999999;
assert(b5q_dp_port_poll(&out)&&out.configured&&!out.hpd);hardware.cc0=0x41;assert(b5q_dp_port_poll(&out)&&out.configured&&out.generation==8&&hardware.off==0&&hardware.on==0);
hardware.vdmIrq=0x10;assert(b5q_dp_port_poll(&out)&&out.hpd&&out.configured&&hardware.gets==1&&hardware.id==6);
unsigned gets=hardware.gets;hardware.pdIrq=0x20;assert(b5q_dp_port_poll(&out)&&hardware.gets==gets);
hardware.pdIrq=0x10;assert(b5q_dp_port_poll(&out)&&hardware.id==6&&out.hpd);
// Orientation/data-role/water still invalidate the established session.
auto sig=src.dpSessionSignature();src.cc0=0x41;assert(sig==src.dpSessionSignature());src.cc0=0x81;assert(sig!=src.dpSessionSignature());src.cc0=0x41;src.pd=0;assert(sig!=src.dpSessionSignature());src.pd=0x80;src.cc1=2;assert(sig!=src.dpSessionSignature());
b5q_dp_port_stop();assert(hardware.off==1);hardware.timeout=true;hardware.cc0=0x42;clockNs=1000000000;
assert(!b5q_dp_port_poll(&out)&&dpStartAttempts==1&&!dpFailed);unsigned on=hardware.on;
assert(b5q_dp_port_poll(&out)&&hardware.on==on&&dpStartAttempts==1);
clockNs+=1000000000;assert(!b5q_dp_port_poll(&out)&&dpStartAttempts==2&&!dpFailed);
clockNs+=1000000000;assert(!b5q_dp_port_poll(&out)&&dpStartAttempts==3&&dpFailed);on=hardware.on;clockNs+=5000000000;assert(b5q_dp_port_poll(&out)&&hardware.on==on);
}
''')
 gpu=(P/'B5qGpu.cpp').read_text()
 host(t,'GPU-six-BO-size-bins',r"""
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <cassert>
volatile uint32_t native_adreno_bo_memory[8],native_adreno_bo_owners[24][4],native_adreno_bo_sizes[6][2],native_adreno_import_memory[4],native_adreno_import_owners[24][4];
"""+fn(gpu,'static void gpuMemoryRow(')+r"""
int main(){for(unsigned i=0;i<6;i++){native_adreno_bo_sizes[i][0]=i+1;native_adreno_bo_sizes[i][1]=(i+1)*1024;}char row[512];gpuMemoryRow(row,sizeof row);assert(strstr(row,"bo_sizes=1:1024K,2:2048K,3:3072K,4:4096K,5:5120K,6:6144K"));char tiny[8];gpuMemoryRow(tiny,sizeof tiny);assert(tiny[7]==0);}
""")
 # Stable seed is the one already delivered, not a newly invented identity.
 a=t/'one/seed';b=t/'two/seed';b5q_identity.write_seed(a);b5q_identity.write_seed(b);assert a.read_bytes()==b.read_bytes() and a.stat().st_mode&0o777==0o600
 a.write_text('deadbeefdeadbeef\n');b5q_identity.write_seed(a);assert a.read_bytes()==b.read_bytes()
 assert len(b5q_identity.UNIQUE_CHIP_ID)==16 and int(b5q_identity.UNIQUE_CHIP_ID,16)>0
 policy=importlib.util.spec_from_file_location('r22policy',R/'UniXNU-b5q/scripts/update-b5q-launchd-seed.py');m=importlib.util.module_from_spec(policy);policy.loader.exec_module(m);pol=m.policies();assert list(map(len,pol.values()))==[59,25]and pol['disabled.plist']['com.apple.softwareupdated']is False and pol['disabled.plist']['com.openssh.sshd']is False
 assert all(p['com.apple.SoftwareUpdateNotificationManager']is True for p in pol.values())
 assert 'gpu-bundle-system=1'in(P/'B5qBootPolicy.c').read_text()
 runtime=(tree/'scripts/build-boot-runtime.py').read_text();assert runtime.index("board_policy =")<runtime.index('hashes = addon_hashes(addon, work / \'signed-addon\'')
 checks.append(dict(name='stable21-platform-policy59-25-softwareupdate-XPC-enabled-runtime-hook-before-seal',passed=True))
 # Compile the entire changed .mm translation unit with the actual SDK/PAC ABI.
 headers=W/'vulkan-headers';headers.mkdir(exist_ok=True)
 for name in ['vulkan','vk_video']:
  if (Path('/usr/include')/name).is_dir():shutil.copytree(Path('/usr/include')/name,headers/name,dirs_exist_ok=True)
 cc=R/'tools/llvm21/usr/lib/llvm-21/bin/clang++';sdk=R/'tools/macos-sdk/MacOSX26.5.sdk';env=dict(os.environ,LD_LIBRARY_PATH=str(R/'tools/llvm21/usr/lib/x86_64-linux-gnu'))
 env.update(PATH=str(R/'artifacts/b5q-review22-local/host-tools/unpack/usr/bin')+':'+env['PATH'],LD_LIBRARY_PATH=str(R/'artifacts/b5q-review22-local/host-tools/unpack/usr/lib/x86_64-linux-gnu')+':'+env['LD_LIBRARY_PATH'])
 shutil.copyfile(R/'UniXNU/scripts/gen-turnip-smoke-shaders.py',tree/'scripts/gen-turnip-smoke-shaders.py')
 run('actual-smoke-shaders-generation',[sys.executable,tree/'scripts/gen-turnip-smoke-shaders.py'],env)
 for name in ['NativeBridgeMetalFrontend.mm','NativeAdrenoMetalPlugin.mm']:
  command=[cc,'-target','arm64e-apple-macos27.0','-isysroot',sdk,'-nostdinc++','-isystem',sdk/'usr/include/c++/v1','-std=c++17','-fobjc-arc','-O2','-fptrauth-calls','-fptrauth-returns','-fptrauth-intrinsics','-fptrauth-function-pointer-type-discrimination','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-Wno-deprecated-declarations','-Wno-incompatible-sysroot','-I',tree/'build/turnip-smoke','-I',headers,'-I',R/'UniXNU/drivers/Adreno740','-I',R/'UniXNU/kits/AdrenoPM4','-I',tree/'drivers/AdrenoMetal','-c',tree/'drivers/AdrenoMetal'/name,'-o',W/(Path(name).stem+'.o')]
  run(Path(name).stem+'-arm64e-full-TU',command,env)
 checks.append(dict(name='reproducible-display-prepare-idempotent-new-runtime-source-id',passed=True,source_id=newid))
assert len(' '.join(tomllib.loads((R/'UniXNU-b5q/board.toml').read_text())['payload']['kernel_args']).encode())==1023
(W/'review22-tests.json').write_text(json.dumps(dict(passed=True,hardware_verified=False,status='HOST_VERIFIED_PENDING_HARDWARE',checks=checks),indent=2)+'\n')
print('PASS Review22 local source/production helper/target tests; real hardware is a separate qualification')
