#!/usr/bin/env python3
"""Review23 local production regressions. Never contacts a phone or starts CI."""
from pathlib import Path
import difflib,hashlib,importlib.util,json,os,shutil,struct,subprocess,sys,tempfile,tomllib
R=Path(__file__).resolve().parents[2];P=R/'UniXNU-b5q/package'
W=Path(os.environ.get('B5Q_GATE_WORK',R/'artifacts/b5q-review23-local')).resolve();W.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(R/'UniXNU-b5q/scripts'));import b5q_display
checks=[]
def fn(text,signature):
 a=text.index(signature);b=text.index('{',a)+1;depth=1
 while depth:depth+=(text[b]=='{')-(text[b]=='}');b+=1
 return text[a:b]
def run(name,command,env=None):
 command=list(map(str,command));log=W/(name+'.log')
 with log.open('w')as output:p=subprocess.run(command,cwd=R,env=env,stdout=output,stderr=subprocess.STDOUT)
 checks.append(dict(name=name,passed=p.returncode==0,exit_code=p.returncode,command=command,log_sha256=hashlib.sha256(log.read_bytes()).hexdigest()))
 (W/'review23-tests.json').write_text(json.dumps(dict(passed=all(c['passed']for c in checks),hardware_verified=False,status='HOST_VERIFIED_PENDING_HARDWARE',checks=checks),indent=2)+'\n')
 if p.returncode:raise RuntimeError(name+'\n'+log.read_text()[-6000:])
 print('PASS',name,flush=True)
def host(t,name,source):
 p=t/(name+'.cpp');p.write_text(source);o=t/name
 run(name+'-compile',['c++','-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-Wno-misleading-indentation','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I',P,p,'-o',o])
 run(name+'-ASan-UBSan',[o])
# Check the actual stock module's data fields, not an old report's assertion.
from elftools.elf.elffile import ELFFile
stock=R/'sources/twrp-b5q/recovery/root/lib/modules/gcc-kalama.ko'
with stock.open('rb')as f:
 e=ELFFile(f);symbols=e.get_section_by_name('.symtab');data=e.get_section_by_name('.data').data()
 for name,off,hwcg_reg,halt,enable,hwcg in [('gcc_disp_ahb_clk',0xf58,0x27004,0x27004,0x27004,1),('gcc_disp_xo_clk',0x1088,0,0x27018,0x27018,0)]:
  sym=symbols.get_symbol_by_name(name)[0];assert sym['st_value']==off
  assert struct.unpack_from('<II',data,off)==(hwcg_reg,halt)
  assert struct.unpack_from('<II',data,off+0x38)==(enable,1)
  assert data[off+16]==hwcg and data[off+19]==2
checks.append(dict(name='stock-gcc-two-BRANCH_HALT_DELAY-symbol-layouts',passed=True,sha256=hashlib.sha256(stock.read_bytes()).hexdigest()))
# DISPCC branches are a separate contract, so retain their ordinary HALT checks.
stockdisp=R/'sources/twrp-b5q/recovery/root/lib/modules/dispcc-kalama.ko'
with stockdisp.open('rb')as f:
 e=ELFFile(f);syms=e.get_section_by_name('.symtab');data=e.get_section_by_name('.data').data()
 for name,reg in [('disp_cc_mdss_ahb_clk',0x80a4),('disp_cc_mdss_ahb1_clk',0xa020)]:
  at=syms.get_symbol_by_name(name)[0]['st_value'];assert struct.unpack_from('<I',data,at+4)[0]==reg
  assert data[at+19]!=2,(name,'unexpected delay branch')
board=(P/'B5qDpLink.cpp').read_text();usb=(P/'QcomDwc3.cpp').read_text()
with tempfile.TemporaryDirectory(prefix='review23-',dir=W)as td:
 t=Path(td)
 # Execute the actual Hardware::open, including its real power-domain gates.
 members='''uint32_t dispPowerSnapshot=0,gccAhbBefore=0,gccAhbAfter=0,gccXoBefore=0,gccXoAfter=0;bool dispPowerRead=false,fault=false,cablePresent=false,dpBusy=false,opened=false;unsigned wantedReverse=0;uint64_t sampled=0;Window dp,phy,disp,gcc,dpu,sel,en;Pins pins;
 uint64_t nowUs(){return 1;}void trace(const char*){}bool openFailure(const char*){return false;}void clockSnapshot(){}uint32_t read(B5qDp::Block,unsigned){return 0;}void write(B5qDp::Block,unsigned,uint32_t){}void delay(unsigned){}
'''
 host(t,'DP-real-open-delay-HWCTL-fail-closed',r'''
#include <cstdint>
#include <cassert>
#include <vector>
#include <cstdarg>
#include "B5qDpClock.h"
static std::vector<unsigned> delays;static bool supplied=true;static unsigned inspections;
void IOLog(const char*,...){}void barrier(){}void IODelay(unsigned us){delays.push_back(us);}
bool b5q_usb_dp_phy_ready(){return supplied;}
struct Window{std::vector<uint32_t> mem;uint32_t *va;Window():mem(0x84000/4),va(mem.data()){}bool open(uint64_t,unsigned){return true;}};
struct Pins{unsigned inMismatch=0;template<class T>bool begin(T&,bool){return true;}};
namespace B5qDp {struct DpuResources{bool dpBusy=false;template<class Read>void inspect(Read){++inspections;}};}
struct Hardware{
'''+members+fn(board,' bool enableDispGcc()')+'\n'+fn(board,' bool open(bool reverse)')+r'''
};
int main(){Hardware io;io.gcc.va[0x50018/4]=io.gcc.va[0x39004/4]=0x80000000;
io.gcc.va[0x27004/4]=0x80000002;io.gcc.va[0x27018/4]=0x80000000;
assert(io.enableDispGcc());assert(io.gccAhbAfter==0x80000003&&io.gccXoAfter==0x80000001);assert((delays==std::vector<unsigned>{50,50}));
// No DPU access if DISP GDSC is off, despite both delay branches enabled.
delays.clear();assert(!io.open(false));assert(io.dispPowerRead&&io.dispPowerSnapshot==0&&inspections==0);assert((delays==std::vector<unsigned>{50,50}));
supplied=false;delays.clear();assert(!io.open(false));assert(!io.dispPowerRead&&delays.empty()&&inspections==0);
supplied=true;io.disp.va[0x9000/4]=0x80000000;assert(io.open(false)&&io.dispPowerRead&&io.opened&&inspections==1);
}
'''.replace('template<class T>bool begin(T&,bool)','template<class T>bool begin(T&,bool)'))
 host(t,'USB-failure-snapshot-bounds-pending-before-teardown',r'''
#include <cassert>
#include <cstdint>
#include <map>
#include <vector>
#include "B5qUsbHostEvent.h"
using namespace B5qUsbHostEvent;
int main(){std::map<uint64_t,uint64_t> memory;std::vector<uint64_t> reads;
auto read=[&](uint64_t pa,uint64_t&v){reads.push_back(pa);auto p=memory.find(pa);if(p==memory.end())return false;v=p->second;return true;};
Event e{0x3020,0x06000008,0x02018001,6,32,2,1,1};
memory[0x3000]=0x0008000001000680ULL;memory[0x3008]=0x3084000400008ULL;memory[0x3010]=0x9000;memory[0x3018]=3ULL<<42;memory[0x3020]=0;memory[0x3028]=4ULL<<42;
memory[0x1010]=0x4000;memory[0x4000]=0x08100002;memory[0x4008]=0x201;memory[0x4040]=0x1234;memory[0x4048]=0x5678;
auto f=failure(e,0x1000,64,read);assert(f.trbMask==7&&f.trbs[0][0]==0x0008000001000680ULL&&f.contextRead&&f.ep0[0]==0x1234);
// Consumer teardown after snapshot cannot destroy the captured first failure.
memory[0x4040]=0;assert(f.ep0[0]==0x1234);
reads.clear();e.parameter=16;f=failure(e,0,64,read);assert(!f.trbMask&&reads.empty());
reads.clear();e.parameter=UINT64_MAX;f=failure(e,0,64,read);assert(!f.trbMask&&reads.empty());
e.parameter=0x3020;e.control|=4u;reads.clear();f=failure(e,0,64,read);assert(!f.trbMask&&reads.empty());e.control&=~4u;
e.slot=256;reads.clear();f=failure(e,0x1000,64,read);assert(!f.contextRead);for(auto pa:reads)assert(pa<0x4000);
e.slot=2;memory.erase(0x3018);f=failure(e,0x1000,64,read);assert(f.trbMask==5);
// ERDP points at a queued failure; it must be observed before the callback.
memory[0x5000]=0x6000;memory[0x5008]=16;memory[0x6008]=uint64_t(1u)<<32;
memory[0x6010]=0x3020;memory[0x6018]=(uint64_t(0x02018001)<<32)|0x06000008;memory[0x6020]=0;memory[0x6028]=0;
unsigned seen=0;assert(pending(0x5000,1,0x6010,16,read,[&](unsigned,unsigned index,const Event&v){assert(index==1&&v.completion==6&&v.slot==2);seen++;}));assert(seen==1);
reads.clear();assert(!pending(UINT64_MAX-63,65,0,16,read,[](auto...){assert(false);}));assert(reads.empty());
reads.clear();assert(!pending(0x5001,1,0,16,read,[](auto...){assert(false);}));assert(reads.empty());
}
''')
 # Execute Turnip's real size-class helper against the pinned set1 layout.
 mesa_patch=(R/'UniXNU/patches/mesa/turnip-darwin-kmd.patch').read_text()
 mesa_added='\n'.join(line[1:]for line in mesa_patch.splitlines()if line.startswith('+')and not line.startswith('+++'))
 size_class=fn(mesa_added,'darwin_size_class(uint64_t size)')
 host(t,'Turnip-set1-descriptor-pool-size-class',r'''
#include <cstdint>
#include <cassert>
static uint64_t
'''+size_class+r'''
int main(){constexpr uint64_t textures=65536,levels=65536,samplers=3*8000;
const uint64_t requested=(2*textures+textures+levels+2*textures+samplers)*64;
assert(requested==26701824);assert(darwin_size_class(requested)==28ull*1024*1024);
assert(darwin_size_class(16ull<<20)==16ull<<20);
// The existing cache-disabled path allocates requested, not the rounded class.
assert(requested<(28ull<<20));}
''')
 # Read-only detection must run on the bridge thread before Apple's callback,
 # never on hard IRQ or with logging/UFS sync under its interrupt spinlock.
 bridge=fn(usb,'static void hostIrqBridge(')
 assert bridge.index('captureHostFailures(1)')<bridge.index('gHostNub->deliverSource(1)')
 assert 'captureHostFailures'not in fn(usb,'static void primary(')
 capture=fn(usb,'void captureHostFailures(unsigned source){')
 assert 'count>=8u'in capture and 'dmaRead64' in capture and 'b5q_log_sync'not in capture
 assert 'write'not in capture.lower() and 'IOSleep'not in capture
 assert 'cursor.erdp==ir.erdp' in capture and '!(ir.iman&1u)' in capture
 host(t,'bounded-refusal-logging',r'''
#include <cassert>
#include <cstdint>
'''+fn('\n'.join(line[1:]for line in(R/'UniXNU-b5q/patches/tools/b5q-review23-metal-diagnostics.patch').read_text().splitlines()if line.startswith('+')and not line.startswith('+++')),'static bool refusalLogDue(')+r'''
int main(){unsigned logs=0;for(uint64_t n=1;n<=1048576;n++){bool due=refusalLogDue(n);if(due)logs++;assert(due==(n<=16||n%1024==0));}assert(logs==16+1024);}
''')
# Always construct a fresh source-derived tree. Existing upstream checkouts are read-only.
tree=W/'review23-tree'
if tree.exists():shutil.rmtree(tree)
for component in ['AdrenoMetal','GopFramebuffer']:
 shutil.copytree(R/'UniXNU/drivers'/component,tree/'drivers'/component,ignore=shutil.ignore_patterns('.git','build','target','out'))
 subprocess.run(['git','init','--quiet',str(tree/'drivers'/component)],check=True)
(tree/'scripts').mkdir();shutil.copyfile(R/'UniXNU/scripts/gen-turnip-smoke-shaders.py',tree/'scripts/gen-turnip-smoke-shaders.py')
b5q_display.prepare(tree);stamp=b5q_display.runtime_source_id(tree);b5q_display.prepare(tree);assert b5q_display.runtime_source_id(tree)==stamp
metal=(tree/'drivers/AdrenoMetal/NativeBridgeMetalFrontend.mm').read_text();plugin=(tree/'drivers/AdrenoMetal/NativeAdrenoMetalPlugin.mm').read_text();objects=(tree/'drivers/AdrenoMetal/bridge/NativeMetalObjects.rs').read_text()
assert 'GLOG('not in fn(metal,'static void surfaceFailureLog(') and 'os_log('in fn(metal,'static void surfaceFailureLog(')
assert 'dladdr'not in fn(metal,'static void surfaceFailureLog(')
assert '60*NSEC_PER_SEC' in fn(metal,'static void logClientMemory(')and 'logged>=64u' in fn(metal,'static void logClientMemory(')
assert 'diagOn()'not in fn(metal,'static void logClientMemory(')
assert 'SHENG_DIAG'not in fn(objects,'pub unsafe extern "C" fn nmb_device_memory_summary(')
assert 'setenv("TU_DARWIN_BO_CACHE", "0", 0)'in plugin
assert 'if(strcmp(getprogname(),"Photos"))return;'in fn(metal,'static void observePhotosPixelFormat(')
assert 'method_copyArgumentType' in metal and '@throw;'in fn(metal,'static void photosPixelFormat(')
# Keep compositor XR10 false; pinned runtime does not view ExtendedRange images.
assert 'if(!strcmp(name,"supportsExtendedXR10Formats") && (!strstr(getprogname(),"Poster") || !strcmp(getprogname(),"PosterBoard")))value=0;'in metal
runtime=R/'artifacts/b5q-review22-local/metal2vulkan'
assert subprocess.check_output(['git','-C',runtime,'rev-parse','HEAD'],text=True).strip()=='87a869f7fc4b73265d4812c40d8cccb6a83c7b17'
assert 'FormatEmulation::ExtendedRange'not in fn((runtime/'crates/metal2vulkan-runtime/src/texture.rs').read_text(),'fn viewed(')
# Full production Rust bridge, pinned runtime, retained Cargo caches and actual fixtures.
rust=W/'review23-rust';rust.mkdir(exist_ok=True)
manifest='''[package]\nname="b5q-review23-metal-check"\nversion="0.1.0"\nedition="2024"\nrust-version="1.98"\n[workspace]\n[lib]\npath='''+json.dumps(str(tree/'drivers/AdrenoMetal/bridge/NativeMetalBridge.rs'))+'\n[dependencies]\nmetal2vulkan={path='+json.dumps(str(runtime/'crates/metal2vulkan'))+',features=["ash"]}\nmetal2vulkan-runtime={path='+json.dumps(str(runtime/'crates/metal2vulkan-runtime'))+'}\nlibc="0.2"\nsha2={version="0.10",features=["asm"]}\n'
(rust/'Cargo.toml').write_text(manifest)
env=dict(os.environ,TMPDIR=str(W),NMB_COMPONENT_ID=stamp,NMB_RUNTIME_ID='review23-pinned-runtime')
for name in ['NMB_FIXTURE_AIR','NMB_FC_AIR','NMB_SCANOUT_AIR','NMB_YCBCR_AIR']:env[name]=str(R/'artifacts/b5q-review22-local/rust'/(name+'.air'))
command=['cargo','+1.98.0','--offline'];tail=['--manifest-path',rust/'Cargo.toml','--target-dir',R/'artifacts/b5q-review22-local/rust/target']
run('review23-cargo-check',command+['check']+tail,env);run('review23-cargo-all-unit',command+['test']+tail+['--lib'],env)
headers=W/'review23-vulkan-headers';headers.mkdir(exist_ok=True)
for name in ['vulkan','vk_video']:
 if(Path('/usr/include')/name).is_dir():shutil.copytree(Path('/usr/include')/name,headers/name,dirs_exist_ok=True)
cc=R/'tools/llvm21/usr/lib/llvm-21/bin/clang++';sdk=R/'tools/macos-sdk/MacOSX26.5.sdk'
env.update(LD_LIBRARY_PATH=str(R/'artifacts/b5q-review22-local/host-tools/unpack/usr/lib/x86_64-linux-gnu')+':'+str(R/'tools/llvm21/usr/lib/x86_64-linux-gnu'),PATH=str(R/'artifacts/b5q-review22-local/host-tools/unpack/usr/bin')+':'+env['PATH'])
run('review23-smoke-shaders',[sys.executable,tree/'scripts/gen-turnip-smoke-shaders.py'],env)
flags=[cc,'-target','arm64e-apple-macos27.0','-isysroot',sdk,'-nostdinc++','-isystem',sdk/'usr/include/c++/v1','-std=c++17','-fobjc-arc','-O2','-fptrauth-calls','-fptrauth-returns','-fptrauth-intrinsics','-fptrauth-function-pointer-type-discrimination','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-Wno-deprecated-declarations','-Wno-incompatible-sysroot','-I',tree/'build/turnip-smoke','-I',headers,'-I',R/'UniXNU/drivers/Adreno740','-I',R/'UniXNU/kits/AdrenoPM4','-I',tree/'drivers/AdrenoMetal']
for name in ['NativeBridgeMetalFrontend.mm','NativeAdrenoMetalPlugin.mm','bridge/surface_import_host.mm','bridge/surface_flush_host.mm','bridge/scanout_host.mm','bridge/carenderer_host.mm']:
 run('review23-'+Path(name).stem+'-arm64e',flags+['-c',tree/'drivers/AdrenoMetal'/name,'-o',W/('review23-'+Path(name).stem+'.o')],env)
# No capabilities or pixel results are inferred from target compilation on Linux.
checks.append(dict(name='Mac-IOSurface-host-test-source-compilation',passed=True,runtime_execution='NOT_EXECUTED_LINUX_HOST',qualification='four actual Mac host regression TUs target-compiled; no pixel-render success claim'))
protected=json.loads((R/'UniXNU-b5q/reports/review22-source-audit.json').read_text())['protected_sha256']
assert all(hashlib.sha256((R/p).read_bytes()).hexdigest()==sha for p,sha in protected.items())
assert len(' '.join(tomllib.loads((R/'UniXNU-b5q/board.toml').read_text())['payload']['kernel_args']).encode())==1023
checks.append(dict(name='protected70-and-1023-byte-args',passed=True,source_id=stamp))
(W/'review23-tests.json').write_text(json.dumps(dict(passed=True,hardware_verified=False,status='HOST_VERIFIED_PENDING_HARDWARE',checks=checks),indent=2)+'\n')
print('PASS Review23 production helper, full Rust and arm64e compile gates; hardware remains pending')
