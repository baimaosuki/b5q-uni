#!/usr/bin/env python3
"""Review21 local production regressions. Never deploy or contact a device."""
import argparse,hashlib,importlib.util,json,os,plistlib,re,shutil,subprocess,tempfile,tomllib
from pathlib import Path
R=Path(__file__).resolve().parents[2];P=R/'UniXNU-b5q/package';W=Path(os.environ.get('B5Q_GATE_WORK',R/'artifacts/b5q-review21-local')).resolve();W.mkdir(parents=True,exist_ok=True);checks=[]
def load(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def fn(text,signature):
 a=text.index(signature);b=text.index('{',a)+1;depth=1
 while depth:depth+=(text[b]=='{')-(text[b]=='}');b+=1
 return text[a:b]
def run(name,cmd,env=None):
 p=subprocess.run(list(map(str,cmd)),cwd=R,env=env,capture_output=True,text=True);out=p.stdout+p.stderr;(W/(name+'.log')).write_text(out)
 if p.returncode:raise RuntimeError(name+'\n'+out[-6000:])
 checks.append(dict(name=name,passed=True,command=list(map(str,cmd)),log_sha256=hashlib.sha256(out.encode()).hexdigest()));print('PASS',name,flush=True)
def host(t,name,s):
 p=t/(name+'.cpp');p.write_text(s);o=t/name;run(name+'-compile',['c++','-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-Wno-unused-parameter','-fsanitize=address,undefined','-fno-sanitize-recover=all','-pthread',p,'-o',o]);run(name+'-ASan-UBSan',[o])
policy=load('r21policy',R/'UniXNU-b5q/scripts/update-b5q-launchd-seed.py');pol=policy.policies();assert list(map(len,pol.values()))==[59,25];assert pol['disabled.plist']['com.openssh.sshd']is False and 'com.openssh.sshd'not in pol['disabled.501.plist'];assert pol['disabled.plist']['com.apple.softwareupdated']is False;assert sum(pol['disabled.plist'].values())==57
for d in pol.values():
 assert d['com.apple.SoftwareUpdateNotificationManager']is True and 'com.apple.wallpaper.agent'not in d
 assert d['com.apple.wallpaper.extension.aerials']is True
 for n in ['com.apple.WindowServer','com.apple.Dock','com.apple.finder','com.apple.iconservices.iconservicesagent']:assert n not in d
before=json.loads((R/'artifacts/b5q-review21-local/before.json').read_text());wifi=load('r21wifi',R/'UniXNU-b5q/scripts/b5q_wifi.py');display=load('r21display',R/'UniXNU-b5q/scripts/b5q_display.py');peripherals=load('r21periph',R/'UniXNU-b5q/scripts/b5q_peripherals.py')
with tempfile.TemporaryDirectory(prefix='review21-',dir=W)as td:
 t=Path(td)
 # Test real generated header bytes, not a mirror of its construction.
 inc=t/'headers';peripherals.prepare_headers(R/'tools/macos-sdk/MacOSX26.5.sdk',inc,next((R/'sources/UniXNU/out/feeds').glob('IOHIDFamily-*')),P)
 blobs=re.findall(r'b5q_policy_\d+\[\]=\{([^}]+)\}',(inc/'B5qLaunchdPolicyData.h').read_text());assert len(blobs)==2
 for b,values in zip(blobs,pol.values()):assert plistlib.loads(bytes(map(int,b.split(','))))==values
 bad=t/'conflict.json';d=json.loads((P/'b5q-launchd-lite.json').read_text());d['system_enabled'].append(d['system'][0]);bad.write_text(json.dumps(d));saved=policy.POLICY;policy.POLICY=bad
 try:policy.policies()
 except AssertionError:pass
 else:raise AssertionError('Enabled/disabled conflict accepted')
 policy.POLICY=saved
 seed=t/'data.dbr';ci=R/'artifacts/b5q-review20-ci-46064502841';run('qualified58-25-seed-extract',['mcopy','-i',ci/'payload/payload.img','::/EFI/UniXNU/Payloads/scratch-data.img',seed]);body=seed.read_bytes();meta=json.loads((ci/'runtime/data-seed.json').read_text());digest,reuse=policy.checked_seed(body,meta,'current');assert reuse and digest==policy.MIGRATED_SEED_HASH;assert meta['launchd_policy']==policy.historical_policies()
 original=json.dumps(meta);meta['launchd_policy']['disabled.plist'].append('com.apple.fake');assert not policy.checked_seed(body,meta,'current')[1];meta=json.loads(original);seed.unlink()
 checks.append(dict(name='actual-generated59-25-plist-sshd-false-notifier-true-wallpaper-enabled-oldseed-qualification',passed=True))
 # Copy upstream inputs; never apply a patch to the actual UniXNU checkout.
 tree=t/'tree'
 for component in ['AdrenoMetal','GopFramebuffer']:
  shutil.copytree(R/'UniXNU/drivers'/component,tree/'drivers'/component,ignore=shutil.ignore_patterns('.git','build','target','out'))
  subprocess.run(['git','init','--quiet',str(tree/'drivers'/component)],check=True)
 oldid=display.runtime_source_id(tree);display.prepare(tree);newid=display.runtime_source_id(tree);assert newid!=oldid;display.prepare(tree);assert display.runtime_source_id(tree)==newid
 metal=(tree/'drivers/AdrenoMetal/NativeBridgeMetalFrontend.mm').read_text();family=fn(metal,'static BOOL familyForCaller(');assert 'dladdr'not in family and 'ptrauth_strip' in family and '_dyld_register_func_for_add_image(renderBoxAdded)'in metal
 callback=metal[metal.index('static std::atomic<uintptr_t> gRenderBoxLo'):metal.index('static BOOL (*gFamilyAnswer)')]
 cxx=r'''
#include <atomic>
#include <cstdint>
#include <cstring>
#include <cassert>
#include <thread>
#include <vector>
using BOOL=bool;using id=void*;using SEL=void*;using NSInteger=long;
#define NO false
#define MH_MAGIC_64 0xfeedfacf
#define LC_ID_DYLIB 13
#define LC_SEGMENT_64 25
struct mach_header{uint32_t magic;};struct mach_header_64{uint32_t magic,cputype,cpusubtype,filetype,ncmds,sizeofcmds,flags,reserved;};
struct load_command{uint32_t cmd,cmdsize;};struct dylib_command{uint32_t cmd,cmdsize;struct{struct{uint32_t offset;}name;uint32_t timestamp,current_version,compatibility_version;}dylib;};
struct segment_command_64{uint32_t cmd,cmdsize;char segname[16];uint64_t vmaddr,vmsize,fileoff,filesize;uint32_t maxprot,initprot,nsects,flags;};
'''+callback+r'''
static unsigned delegates;static bool delegate(id,SEL,NSInteger){++delegates;return true;}
static uintptr_t host_pc;
static void *strip(void*p,unsigned){return (void*)((uintptr_t)p&UINT64_C(0x0000ffffffffffff));}
#define ptrauth_strip(p,k) strip(p,k)
#define ptrauth_key_return_address 0
#define __has_feature(x) 1
#define __builtin_return_address(x) ((void*)host_pc)
static BOOL (*gFamilyAnswer)(id,SEL,NSInteger)=delegate;
'''+family+r'''
struct Fake {mach_header_64 h{};dylib_command d{};char name[96]{};segment_command_64 seg{};};
static Fake image(){Fake f;f.h.magic=MH_MAGIC_64;f.h.ncmds=2;f.h.sizeofcmds=sizeof(f)-sizeof(f.h);f.d.cmd=LC_ID_DYLIB;f.d.cmdsize=sizeof(f.d)+sizeof(f.name);f.d.dylib.name.offset=sizeof(f.d);strcpy(f.name,"/System/Library/PrivateFrameworks/RenderBox.framework/RenderBox");f.seg.cmd=LC_SEGMENT_64;f.seg.cmdsize=sizeof(f.seg);strcpy(f.seg.segname,"__TEXT");f.seg.vmaddr=0x1000;f.seg.vmsize=0x1000;return f;}
int main(){host_pc=0x1000;assert(familyForCaller(nullptr,nullptr,1003)&&delegates==1);Fake f=image();renderBoxAdded((mach_header*)&f,0x2000);assert(gRenderBoxLo==0x3000&&gRenderBoxHi==0x4000);
 for(uintptr_t p:{uintptr_t(0x3000),uintptr_t(0x3fff),uintptr_t(0xabcd000000003010ULL)}){host_pc=p;assert(!familyForCaller(nullptr,nullptr,1003));assert(!familyForCaller(nullptr,nullptr,1999));assert(familyForCaller(nullptr,nullptr,1002));assert(familyForCaller(nullptr,nullptr,2000));}
 for(uintptr_t p:{uintptr_t(0x2fff),uintptr_t(0x4000),uintptr_t(0x9000)}){host_pc=p;assert(familyForCaller(nullptr,nullptr,1003));}
 std::vector<std::thread> readers;for(unsigned j=0;j<8;j++)readers.emplace_back([]{for(unsigned i=0;i<10000;i++){auto hi=gRenderBoxHi.load(std::memory_order_acquire);auto lo=gRenderBoxLo.load(std::memory_order_relaxed);assert(lo==0x3000&&hi==0x4000);}});for(auto &r:readers)r.join();
 gRenderBoxLo=0;gRenderBoxHi=0;gRenderBoxClaim.clear();f=image();strcpy(f.name,"/Metal.framework/Metal");renderBoxAdded((mach_header*)&f,0);assert(gRenderBoxHi==0);f=image();f.d.cmdsize=4;renderBoxAdded((mach_header*)&f,0);assert(gRenderBoxHi==0);f=image();f.seg.vmaddr=UINT64_MAX-5;renderBoxAdded((mach_header*)&f,20);assert(gRenderBoxHi==0);f=image();renderBoxAdded((mach_header*)&f,-0x2000);assert(gRenderBoxHi==0);}
''';host(t,'metal-dyld-range-late-load-boundaries-PAC-and-concurrent-read',cxx)
 checks.append(dict(name='display-prepare-positive-idempotent-runtime-source-digest-invalidates-cache',passed=True,old_source_id=oldid,new_source_id=newid))
 # Compile the actual changed full Objective-C++ TU using the local Apple SDK.
 compiler=R/'tools/llvm21/usr/lib/llvm-21/bin/clang++';sdk=R/'tools/macos-sdk/MacOSX26.5.sdk';env=dict(os.environ,LD_LIBRARY_PATH=str(R/'tools/llvm21/usr/lib/x86_64-linux-gnu'))
 command=[compiler,'-target','arm64e-apple-macos27.0','-isysroot',sdk,'-nostdinc++','-isystem',sdk/'usr/include/c++/v1','-std=c++17','-fobjc-arc','-O2','-fptrauth-calls','-fptrauth-returns','-fptrauth-intrinsics','-fptrauth-function-pointer-type-discrimination','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-Wno-deprecated-declarations','-Wno-incompatible-sysroot','-I',R/'UniXNU/drivers/Adreno740','-I',R/'UniXNU/kits/AdrenoPM4','-I',tree/'drivers/AdrenoMetal','-c',tree/'drivers/AdrenoMetal/NativeBridgeMetalFrontend.mm','-o',W/'NativeBridgeMetalFrontend.o']
 result=subprocess.run(list(map(str,command)),capture_output=True,text=True,env=env);(W/'metal-full-target.log').write_text(result.stdout+result.stderr)
 target=dict(command=list(map(str,command)),passed=result.returncode==0,full_TU=True,first_error=result.stderr[:2500]if result.returncode else None)
 (W/'metal-target.json').write_text(json.dumps(target,indent=2)+'\n')
 if result.returncode:print('LIMIT full Metal target:',result.stderr.splitlines()[:3],flush=True)
 else:checks.append(dict(name='full-Metal-ObjectiveCxx-arm64e-target-zero-warning',passed=True,sha256=hashlib.sha256((W/'NativeBridgeMetalFrontend.o').read_bytes()).hexdigest()))
 # Real callback tracking helpers from the generated shared executor.
 rt=wifi.select_shared(R/'sources/UniXNU-sheng/drivers/Ath12kWifi/shim/src/lx_rt.c',t/'wifi').read_text();net=wifi.select_shared(R/'sources/UniXNU-sheng/drivers/Ath12kWifi/src/nw_net.c',t/'wifi').read_text()
 helper=rt[rt.index('volatile uint64_t b5q_wifi_last_slow'):rt.index('#define B5Q_CALLBACK')]
 for k in ['B5Q_CALLBACK(1','B5Q_CALLBACK(2','B5Q_CALLBACK(3','B5Q_CALLBACK(4','B5Q_CALLBACK(5','B5Q_CALLBACK(6','B5Q_CALLBACK(7','B5Q_CALLBACK(8']:assert k in rt
 assert 'b5q_wifi_slow_note(9' in net
 host(t,'wifi-completed-slow-callback-nested-context-200ms-boundary',r'''
#include <cstdint>
#include <cassert>
static uint64_t ms;static unsigned g_depth=1;static uint64_t lx_now_ms(){return ms;}volatile uint64_t nw_wifi_where[4];
'''+helper+r'''
static void callback(){}
int main(){auto a=b5q_callback_begin(3,(const void*)callback);ms=200;b5q_callback_end(&a);assert(!b5q_wifi_last_slow[2]);a=b5q_callback_begin(3,(const void*)callback);ms=201;auto b=b5q_callback_begin(5,(const void*)callback);ms=20402;b5q_callback_end(&b);assert(b5q_wifi_last_slow[0]==5&&b5q_wifi_last_slow[2]==20201&&nw_wifi_where[0]==3);b5q_callback_end(&a);assert(b5q_wifi_last_slow[0]==3&&b5q_wifi_last_slow[2]==20202&&nw_wifi_where[0]==0);assert(b5q_wifi_last_slow[1]==uint64_t(uintptr_t(callback)-uintptr_t(lx_now_ms)));b5q_wifi_slow_note(9,(const void*)callback,20401,2);assert(b5q_wifi_last_slow[0]==3);}
''')
 # GPU helpers are extracted verbatim, screen updates remain unconditional.
 gpu=(P/'B5qGpu.cpp').read_text();row=fn(gpu,'static bool gpuRowLog(');memory=fn(gpu,'static void gpuMemoryRow(')
 host(t,'GPU-memory-top-format-and-stage97-console-throttle',r'''
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <cassert>
volatile uint32_t native_adreno_bo_memory[8],native_adreno_bo_owners[24][4],native_adreno_bo_sizes[6][2],native_adreno_import_memory[4],native_adreno_import_owners[24][4];
'''+row+'\n'+memory+r'''
int main(){assert(gpuRowLog(0x96,0,"e0",0,0));assert(gpuRowLog(0x97,0,"H0 F0 f0",0,0));assert(!gpuRowLog(0x97,0,"H2 F0 f0",2000,0));assert(!gpuRowLog(0x97,0,"H28 F0 f0",29999,0));assert(gpuRowLog(0x97,0,"H30 F0 f0",30000,0));assert(gpuRowLog(0x97,0,"H31 F1 f0",31000,0));assert(!gpuRowLog(0x97,0,"H32 F1 f0",32000,0));assert(gpuRowLog(0x97,0,"H33 F0 f0",33000,0));assert(gpuRowLog(0x97,0,"H34 F0 f0",34000,1));assert(gpuRowLog(0x97,0,"gx-off",35000,1));assert(gpuRowLog(0x98,0,"e0",35001,0));
 native_adreno_bo_memory[0]=10;native_adreno_bo_memory[4]=600;native_adreno_bo_memory[5]=700;native_adreno_bo_memory[6]=2;native_adreno_import_memory[0]=3;native_adreno_import_memory[1]=2048;native_adreno_import_memory[2]=4096;native_adreno_bo_owners[0][0]=30;native_adreno_bo_owners[0][1]=100;native_adreno_bo_owners[1][0]=20;native_adreno_bo_owners[1][1]=200;native_adreno_import_owners[0][0]=42;native_adreno_import_owners[0][1]=2048;char out[320];gpuMemoryRow(out,sizeof(out));assert(strstr(out,"bo_mib=600/700 bo_n=10 kbo=2 imp_kib=2048/4096 imp_n=3 bo_top=20:200K,30:100K,0:0K imp_top=42:2048K,0:0K"));char shortbuf[8];gpuMemoryRow(shortbuf,sizeof(shortbuf));assert(shortbuf[7]==0);}
''')
 setrow=fn(gpu,'void setRow(');assert setrow.index('if(gpuRowLog')<setrow.index('b5q_gpu_progress[slot][i] = text[i]');assert 'gpuMemoryRow(memory' in fn(gpu,'void heartbeat() {')
 # The whole production worker/ring/SCSI fixture includes timed-wait mocks,
 # commit-vs-arm races, asynchronous IRQ requests, timeout/stop and no yields.
 run('logger-production-sleep-urgent-races-and-disk-gates',['python3',R/'tests/b5q-ufs/test-log-writer.py'])
 for n,digest in before['protected_sha256'].items():assert hashlib.sha256((R/n).read_bytes()).hexdigest()==digest,n
 assert hashlib.sha256((R/'UniXNU-b5q/patches/xnu/series').read_bytes()).hexdigest()==before['hashes']['UniXNU-b5q/patches/xnu/series']
 assert len(' '.join(tomllib.loads((R/'UniXNU-b5q/board.toml').read_text())['payload']['kernel_args']).encode())==1023
 for n,digest in before['hashes'].items():
  if n.startswith('UniXNU/drivers/AdrenoMetal/')or n.startswith('UniXNU/drivers/Adreno740/'):assert hashlib.sha256((R/n).read_bytes()).hexdigest()==digest,n
 checks.append(dict(name='protected68-args1023-core-series-unchanged-no-direct-upstream-edits',passed=True))
(W/'review21-tests.json').write_text(json.dumps(dict(passed=True,status='HOST_VERIFIED_PENDING_HARDWARE',hardware_verified=False,checks=checks,metal_full_target=target),indent=2)+'\n');print('PASS Review21 production host regressions; hardware pending')
