#!/usr/bin/env python3
"""Compile P5 protocol inputs with production arm64e flags; report missing integration."""
from pathlib import Path
import hashlib,importlib.util,json,os,subprocess,sys,tempfile
R=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(R/'UniXNU-b5q/scripts'),str(R/'sources/UniXNU/kits/XnuPrelink')]
from b5q_peripherals import flags,compile_object
from kc_image import Image
from b5q_abi import object_symbols,object_vtable
spec=importlib.util.spec_from_file_location('usb',R/'UniXNU-b5q/scripts/build-b5q-usb.py')
usb=importlib.util.module_from_spec(spec);spec.loader.exec_module(usb)
spec=importlib.util.spec_from_file_location('pac',R/'scripts/b5q-install/check-proctop-pac.py')
pac=importlib.util.module_from_spec(spec);spec.loader.exec_module(pac)
out=R/'artifacts/b5q-p5-work/target';out.mkdir(parents=True,exist_ok=True)
sdk=R/'tools/macos-sdk/MacOSX26.5.sdk';llvm=R/'tools/llvm21/usr/lib/llvm-21/bin'
os.environ['LD_LIBRARY_PATH']=str(R/'tools/llvm21/usr/lib/x86_64-linux-gnu')
with tempfile.TemporaryDirectory(prefix='b5q-dp-target-')as td:
 t=Path(td);header=sdk/'System/Library/Frameworks/Kernel.framework/Headers'
 p=t/'libkern/c++/OSMetaClass.h';p.parent.mkdir(parents=True)
 p.write_text((header/'libkern/c++/OSMetaClass.h').read_text().replace('#if TARGET_OS_IPHONE && !TARGET_OS_SIMULATOR','#if !XNU_TARGET_OS_OSX').replace('#if TARGET_OS_OSX && defined(__arm64__)','#if XNU_TARGET_OS_OSX && defined(__arm64__)'))
 p=t/'os/base.h';p.parent.mkdir(exist_ok=True);p.write_text((header/'os/base.h').read_text().replace(', "authenticates-null-values"',''))
 (t/'OriginalUsbXhciABI.h').write_text(usb.header(json.loads((R/'UniXNU-b5q/scripts/usb-xhci-26C5035r.json').read_text())))
 (t/'OriginalUsbXdciABI.h').write_text(usb.xdci_header(json.loads((R/'UniXNU-b5q/scripts/usb-xdci-26C5035r.json').read_text())))
 abi_env=dict(os.environ,UNIXNU_XNU_ARCH='arm64e',UNIXNU_IOS_VERSION='27.0',UNIXNU_IPSW_BUILD='26C5035r',
  UNIXNU_XNU_TARGET='macosx',UNIXNU_OS_PROFILE=str(R/'sources/UniXNU/profiles/os/macos-27.3-26C5035r/profile.toml'),
  PYTHONPATH=str(R/'sources/UniXNU/scripts'))
 subprocess.run([sys.executable,str(R/'UniXNU-b5q/scripts/build-b5q-gop-27.py'),'--abi-header-only'],env=abi_env,check=True)
 (t/'OriginalLegacyFramebufferABI.h').write_bytes((R/'UniXNU-b5q/build/native-legacy-display/OriginalLegacyFramebufferABI.h').read_bytes())
 options=flags(sdk,t,header,R/'UniXNU-b5q/package',R/'sources/UniXNU',R/'sources/UniXNU/out/feeds/xnu-3199e8bc',True)
 options+=['-Wno-misleading-indentation','-Wno-missing-field-initializers','-Wno-sign-compare','-I',str(R/'sources/UniXNU-sheng/drivers/QcomDwc3'),'-I',str(R/'sources/UniXNU/drivers/GopFramebuffer')]
 sources=[R/'UniXNU-b5q/package/B5qUsbBoard.cpp',R/'UniXNU-b5q/package/QcomDwc3.cpp',R/'UniXNU-b5q/package/B5qDpLink.cpp',R/'UniXNU-b5q/package/B5qDpIrq.cpp',R/'UniXNU-b5q/package/B5qDpDisplay.cpp']
 # Instantiation translation unit only; never linked as a driver or stub.
 p=out/'DpProtocolInstantiation.cpp';p.write_text('''
#include "B5qDpController.h"
#include "B5qDpPhy.h"
#include "B5qDpClock.h"
#include "B5qDpTraining.h"
#include "B5qDpTiming.h"
#include "B5qDpDpuResources.h"
#include "B5qDpDpu.h"
#include "B5qDpVsync.h"
#include "B5qDpSession.h"
#include "B5qDpIoav.h"
#include "B5qDpIrq.h"
#include "B5qDpPresentation.h"
#include "B5qDpDisplay.h"
using namespace B5qDp;
struct Io {
 volatile uint32_t *blocks[12];bool online;uint64_t ticks;
 bool connected(){return online;}void delay(unsigned us){ticks+=us;}uint64_t nowUs(){return ticks;}
 bool prepareRate(unsigned){return online;}bool finishRates(){return true;}
 uint32_t read(Block b,unsigned off){return blocks[unsigned(b)][off/4];}
 void write(Block b,unsigned off,uint32_t v){blocks[unsigned(b)][off/4]=v;}
};
struct DpuIo {
 volatile uint32_t *regs;bool authorized;uint64_t begin,end;
 uint32_t read(unsigned off){return regs[off/4];}
 void write(unsigned off,uint32_t value){regs[off/4]=value;}
 bool dmaAllowed(uint64_t address,uint64_t bytes){return authorized&&address>=begin&&address<=end&&bytes<=end-address;}
 void barrier(){asm volatile("dsb sy":::"memory");}
 void delay(unsigned us){asm volatile(""::"r"(us):"memory");}
 void vsync(uint32_t frame){asm volatile(""::"r"(frame):"memory");}
};
// Test-only instantiations: the real driver must provide its authorized
// DMA producer, resource lock, IRQ and IOMFB lifetime owner separately.
extern "C" bool check_dp_target_dpu(DpuIo &io,Mode &mode,unsigned address,unsigned bytes,unsigned stride){
 DpuResources resources;resources.inspect([&](unsigned off){return io.read(off);});
 Dpu pipe;Vsync irq;
 if(!resources.choose(mode.width)||!pipe.make(resources,mode,address,bytes,stride)||!pipe.apply(io))return false;
 bool armed=irq.begin(io);bool started=pipe.start(io);
 bool flipped=started&&pipe.flip(io,address,bytes,stride),latched=pipe.latched(io);
 bool handled=irq.service(io);irq.end(io);return pipe.quiesce(io)&&armed&&handled&&flipped&&latched;
}
extern "C" bool check_dp_target_protocol(Io &io,Mode &mode,unsigned rate,unsigned lanes){
 Controller<Io> controller(io);Phy<Io> phy(io);Clock<Io> clock(io);Aux<Io> aux(io);
 uint8_t edid[128];IntfTiming timing;DpuResources resources;
 resources.inspect([&](unsigned off){return io.read(Block::Dpu,off);});
 return controller.source(lanes)&&controller.pattern(1)&&controller.stream(mode,rate,lanes,true)&&
   controller.video()&&phy.configure(rate,lanes,false)&&phy.enable()&&clock.pixel(mode.pixelKHz,rate)&&
   aux.edidBlock(0,edid)&&timing.make(mode,0)&&resources.choose(mode.width);
}
extern "C" bool check_dp_target_session(Io &io,unsigned lanes,bool reverse){
 Session<Io> session(io);
 const bool ok=session.discover(lanes,reverse)&&session.train();
 if(!ok)return false;
 const bool video=session.video();return session.stop()&&video;
}
extern "C" bool check_dp_target_ioav(Mode &mode,IoavTiming &data){return data.make(mode);}
static void checkDpFrameCallback(void *context,uint32_t frame,uint64_t time){
 auto *value=static_cast<volatile uint64_t *>(context);*value=time+frame;
}
extern "C" bool check_dp_target_irq_register(void *context){return b5q_dp_irq_start(context,checkDpFrameCallback);}
// Compile the production presentation template. These compile-only
// methods are not a native DMA producer or linked display backend.
struct PresentationIo:DpuIo {
 bool fill(const ScanoutBuffer &,uint64_t){return authorized;}
 bool clean(const ScanoutBuffer &,uint64_t){return authorized;}
 bool copy(const ScanoutBuffer &,const void *,const Mode &,unsigned){return authorized;}
 bool arm(Presentation *){return authorized;}bool disarm(){return authorized;}
 bool video(){return authorized;}bool stopVideo(){return authorized;}
 void notify(uint32_t,uint64_t){}uint64_t nowUs(){return begin;}
};
extern "C" bool check_dp_target_presentation(PresentationIo &io,Mode &mode,const ScanoutBuffer (&buffers)[2]){
 Presentation present;DpuResources resources;resources.inspect([&](unsigned off){return io.read(off);});
 if(!resources.choose(mode.width)||!present.begin(io,resources,mode,buffers,mode.width*4))return false;
 const bool offered=present.offer(io,1,&io);const auto completed=present.frame(io,io.read(0x350ac),0);
 const bool timed=present.timedOut(io);uint64_t cancelled=0;
 return present.stop(io,cancelled)&&offered&&(completed||timed||cancelled);
}
static bool checkDpPresent(void *,IOMemoryDescriptor *,uint64_t,bool,uint64_t){return false;}
static bool checkDpDrain(void *){return false;}
extern "C" void check_dp_target_display_callbacks(B5qDpDisplayConfig &config){config.present=checkDpPresent;config.drain=checkDpDrain;}
''')
 sources.append(p);objects=[]
 for source in sources:objects.append(compile_object(llvm/'clang++',options,source,out/(source.stem+'.o'),llvm))
 bindings,slots=usb.all_bindings((out/'QcomDwc3.o').read_bytes())
 scans={p.name:pac.scan(p)for p in objects}
 displayRaw=(out/'B5qDpDisplay.o').read_bytes();displaySymbols=object_symbols(displayRaw)
 fixture=json.loads((R/'UniXNU-b5q/scripts/legacy-display-26C5035r.json').read_text())
 displayTable=object_vtable(displayRaw,displaySymbols,'__ZTV12B5qDpDisplay',len(fixture['slots']))
 assert len(displayTable)==len(fixture['slots'])
 for i,(entry,previous)in enumerate(zip(displayTable,fixture['slots'])):
  assert entry and entry[1]>>63 and entry[1]>>48&1 and not(entry[1]>>49&3)and entry[1]>>32&65535==int(previous[1],16),('external IOMFB PAC',i,entry,previous)
 for name,scan in scans.items():
  values={}
  for ins in scan['instructions']:
   ops=ins.op_str.replace(' ','').split(',')
   if ins.mnemonic in ('mov','movz','movk')and len(ops)>1 and ops[1].startswith('#'):
    reg='x'+ops[0][1:];value=int(ops[1][1:],0);shift=int(ops[2].removeprefix('lsl#'),0)if len(ops)>2 else 0
    values[reg]=(values.get(reg,0)&~(65535<<shift))|value<<shift if ins.mnemonic=='movk'else value<<shift
    assert not 0x15000000<=values[reg]<0x150d0000,(name,ins.op_str)
   elif ins.mnemonic in ('bl','blr','blraa','braa','ret','retab')or ins.mnemonic.startswith('b.'):values.clear()
  assert not any(any(v in n for v in ('smmu_configure_bypass','smmu_plan_bypass','arm_smmu_'))for n,_,_ in scan['symbols'])
 arm=next((R/'artifacts/b5q-p4-work/ci45295645295').rglob('ArmCpu.o'));armScan=pac.scan(arm)
 irq=scans['QcomDwc3.late.o']['signed']['__ZN11QcomDwc3Nub7primaryEPv']
 assert irq and all(v['diversity']==0x2abe and v['key']==0 and not v['address_diversity']for v in irq)
 ins=armScan['instructions'];assert any(v.mnemonic=='blraa'and i and ins[i-1].mnemonic=='mov'and ins[i-1].op_str.endswith('#0x2abe')for i,v in enumerate(ins))
 geni=next((R/'artifacts/b5q-p4-work/ci45295645295').rglob('GeniI2c.o'));geniScan=pac.scan(geni);geniContracts=[]
 for symbol,diversity in [('__ZN12_GLOBAL__N_16seReadEPvj',0x50c7),('__ZN12_GLOBAL__N_17seWriteEPvjj',0xc120)]:
  sites=scans['B5qUsbBoard.o']['signed'][symbol]
  assert sites and all(v['key']==0 and v['diversity']==diversity and not v['address_diversity']for v in sites)
  starts=sorted((va,name)for name,va,kind in geniScan['symbols']if kind&14 and name.startswith('_geni_'))
  matched=[]
  for call in geniScan['calls']:
   candidates=[(va,name)for va,name in starts if va<=call['site']]
   if candidates and candidates[-1][1].startswith('_geni_i2c_')and call['diversity']==diversity:matched.append(call)
  assert matched,symbol
  geniContracts.append(dict(symbol=symbol,signature=sites,actual_GeniI2c_authenticated_calls=matched))
 imports={n for scan in scans.values()for n,_,kind in scan['symbols']if kind==1}
 defined={n for scan in scans.values()for n,_,kind in scan['symbols']if kind&14}
 kernel=t/'kernel';subprocess.run(['mcopy','-i',str(R/'artifacts/b5q-esp-p4/esp.img'),'::/EFI/UniXNU/Payloads/kernel.macho',str(kernel)],check=True)
 raw=kernel.read_bytes();outer=Image(raw);core=Image(raw,outer.entries['com.apple.kernel'][1]);coreSymbols=core.symbols();known={n for names in coreSymbols.values()for n in names}
 # Bind only newly needed original-family entries not already exported by
 # the accepted kernel. Reuse the same reviewed fixture/branch mechanism
 # as the primary builder; do not hide unbound native integration imports.
 originalBindings={name:int(value,16)+int(fixture['collection_slide'],16)for name,value in fixture['bindings'].items()}
 for i,entry in enumerate(displayTable):
  if '25IOMobileFramebufferLegacy'in entry[0]:
   value=int(fixture['slots'][i][0],16)+int(fixture['collection_slide'],16)
   assert originalBindings.get(entry[0],value)==value;originalBindings[entry[0]]=value
 candidates=imports-defined-known-set(bindings)
 bridge={name:originalBindings[name]for name in candidates if name in originalBindings}
 if bridge:
  code='.text\n.p2align 2\n';addresses=''
  for name,value in sorted(bridge.items()):
   if name in ['__ZN25IOMobileFramebufferLegacy10gMetaClassE','__ZTV25IOMobileFramebufferLegacy']:
    addresses+=f'.globl {name}\n.set {name}, {value:#x}\n'
   else:
    code+=f'.globl {name}\n{name}:\n bti c\n b {name}.original\n'
    addresses+=f'.globl {name}.original\n.set {name}.original, {value:#x}\n'
  for stem,body in [('DpOriginalBindings',code),('DpOriginalAddresses',addresses)]:
   path=out/(stem+'.S');path.write_text(body);obj=out/(stem+'.o')
   subprocess.run([str(llvm/'clang'),'-target','arm64e-apple-ios27.0','-c',str(path),'-o',str(obj)],check=True)
   sources.append(path);objects.append(obj);scans[obj.name]=pac.scan(obj)
  imports={n for scan in scans.values()for n,_,kind in scan['symbols']if kind==1}
  defined={n for scan in scans.values()for n,_,kind in scan['symbols']if kind&14}
 irqNative=scans['B5qDpIrq.o'];irqNativeContracts=[]
 for symbol,diversity in [('__ZN12_GLOBAL__N_13Irq7primaryEPv',0x2abe),('__ZN12_GLOBAL__N_13Irq6workerEPvi',0xd507)]:
  sites=irqNative['signed'][symbol];assert sites and all(v['key']==0 and v['diversity']==diversity and not v['address_diversity']for v in sites)
  irqNativeContracts.append(dict(symbol=symbol,sites=sites))
 continuation=next(va for va,names in coreSymbols.items()if '_Call_continuation'in names)
 import capstone
 decoder=capstone.Cs(capstone.CS_ARCH_ARM64,capstone.CS_MODE_ARM)
 actualContinuation=list(decoder.disasm(core.read(continuation,128),continuation))
 assert any(v.mnemonic=='blraa'and i and actualContinuation[i-1].mnemonic=='mov'and actualContinuation[i-1].op_str=='x21, #0xd507'for i,v in enumerate(actualContinuation))
 callback=next(sites for symbol,sites in scans['DpProtocolInstantiation.o']['signed'].items()if 'checkDpFrameCallback'in symbol)
 assert callback and all(v['key']==0 and not v['address_diversity']for v in callback)
 callbackCalls=[v for v in irqNative['calls']if v['diversity']==callback[0]['diversity']]
 assert callbackCalls
 displayContracts=[]
 for name in ['checkDpPresent','checkDpDrain']:
  sites=next(sites for symbol,sites in scans['DpProtocolInstantiation.o']['signed'].items()if name in symbol)
  assert sites and all(v['key']==0 and not v['address_diversity']for v in sites)
  calls=[v for v in scans['B5qDpDisplay.o']['calls']if v['diversity']==sites[0]['diversity']]
  assert calls,name;displayContracts.append(dict(callback=name,producer_sites=sites,actual_native_calls=calls))
 missing=sorted(imports-defined-known-set(bindings))
 # Do not turn a compile result into a false whole-driver closure result.
 result=dict(target_compile_passed=True,implementation_complete=False,hardware_verified=False,
  actual_objects={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in objects},
  input_sources={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in sources},
  original_USB_vtable_slots=slots,USB_IRQ_PAC='IA2abe matches actual ArmCpu dispatch',EL1_apps_smmu_materializations=0,
  SE6_SE8_GENI_PAC=geniContracts,actual_GeniI2c_sha256=geniScan['sha256'],
  DP_native_IRQ_PAC=irqNativeContracts,DP_worker_actual_core_dispatch=hex(continuation),
  DP_frame_callback_PAC=dict(producer_sites=callback,actual_worker_calls=callbackCalls),
  external_IOMFB_vtable_slots=len(displayTable),external_IOMFB_PAC_match=True,external_display_callbacks=displayContracts,
  external_IOMFB_original_bridge={name:hex(value)for name,value in bridge.items()},
  unresolved_integration_symbols=missing,native_link_hook_symbols_closed=not any(v in missing for v in ('_b5q_dp_link_stop','_b5q_dp_link_update')),
  scoped_link_imports_closed=not missing,whole_P5_link_closed=False,
  remaining='Qualified retained display DMA producer, native external IOMFB/hotplug/lid integration, full link/CI and actual P5 ESP')
 (out/'report.json').write_text(json.dumps(result,indent=2)+'\n')
 print('PASS P5 protocol/SE8/USB arm64e target, originalUSB ABI and IRQ PAC, zeroEL1apps_smmu; full P5 remains incomplete')
 print('Unresolved integration:',missing)
