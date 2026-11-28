#!/usr/bin/env python3
"""Local target compile, xHCI ABI and complete new peripheral-symbol closure."""
import argparse,json,os,subprocess,sys,tempfile,tomllib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
DEFAULT=ROOT/'tools'
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--compiler',type=Path,default=Path(os.environ.get('B5Q_TARGET_CXX',DEFAULT/'llvm21/usr/lib/llvm-21/bin/clang++')))
p.add_argument('--sdk',type=Path,default=Path(os.environ.get('B5Q_KERNEL_SDK',DEFAULT/'macos-sdk/MacOSX26.5.sdk')))
p.add_argument('--objects-out',type=Path)
p.add_argument('--sources',help='Comma separated board sources; verify only changed translation units')
p.add_argument('--native-recount',action='store_true',help='Compile CPU/thermal with real recount import; final new-core linkage remains a separate check')
p.add_argument('--reference',type=Path,default=ROOT/'artifacts/b5q-esp-runtime-v18/esp.img');a=p.parse_args()
sys.path.insert(0,str(ROOT/'UniXNU-b5q/scripts'));sys.path.insert(0,str(ROOT/'sources/UniXNU/kits/XnuPrelink'))
from importlib.machinery import SourceFileLoader
from b5q_abi import object_symbols
from kc_image import Image
module=SourceFileLoader('b5q_usb_abi_local',str(ROOT/'UniXNU-b5q/scripts/build-b5q-usb.py')).load_module()
abi=json.loads((ROOT/'UniXNU-b5q/scripts/usb-xhci-26C5035r.json').read_text())
qualified=json.loads((ROOT/'UniXNU-b5q/scripts/usb-host-bindings-26C5035r.json').read_text())
assert abi['kernelcache_sha256']==json.loads((ROOT/'UniXNU-b5q/scripts/legacy-display-26C5035r.json').read_text())['kernelcache_sha256']
assert a.compiler.is_file() and a.sdk.is_dir() and a.reference.is_file(),'Missing local target compiler/SDK/reference ESP; set B5Q_TARGET_CXX/B5Q_KERNEL_SDK or pass --reference'
tc=a.compiler.parents[3]
env=dict(os.environ,LD_LIBRARY_PATH=str(tc/'lib/x86_64-linux-gnu')+(':'+os.environ['LD_LIBRARY_PATH']if os.environ.get('LD_LIBRARY_PATH')else''))
with tempfile.TemporaryDirectory(prefix='b5q-native-input-check-')as t:
 # SDK private headers infer the host OS from the triple. Reproduce the
 # actual XNU OSMetaClass.h XNU_TARGET_OS_OSX conditionals so reserved slots
 # match the source-kernel recipe despite its iOS Mach-O deployment target.
 t=Path(t);(t/'libkern/c++').mkdir(parents=True);(t/'libkern/c++/OSMetaClass.h').write_text((a.sdk/'System/Library/Frameworks/Kernel.framework/Headers/libkern/c++/OSMetaClass.h').read_text().replace('#if TARGET_OS_IPHONE && !TARGET_OS_SIMULATOR','#if !XNU_TARGET_OS_OSX').replace('#if TARGET_OS_OSX && defined(__arm64__)','#if XNU_TARGET_OS_OSX && defined(__arm64__)'));(t/'OriginalUsbXhciABI.h').write_text(module.header(abi));(t/'OriginalUsbXdciABI.h').write_text(module.xdci_header(json.loads((ROOT/'UniXNU-b5q/scripts/usb-xdci-26C5035r.json').read_text())));kernel=t/'kernel'
 # LLVM21 lacks Apple's fourth null-authentication qualifier; no affected
 # private fields are accessed by these helpers. Keep the override local.
 (t/'os').mkdir();(t/'os/base.h').write_text((a.sdk/'System/Library/Frameworks/Kernel.framework/Headers/os/base.h').read_text().replace(', "authenticates-null-values"',''))
 # Follow the pinned source-driver header assembly, while retaining the SDK
 # generated HIDDriverKit declarations and XNU's OSMetaClass definition.
 hid=next((ROOT/'sources/UniXNU/out/feeds').glob('IOHIDFamily-*'))
 import shutil
 for src,rel in [(hid/'IOHIDFamily','IOKit/hid'),(hid/'IOHIDSystem/IOKit/hidsystem','IOKit/hidsystem')]:
  dest=t/rel;dest.mkdir(parents=True,exist_ok=True)
  for h in src.glob('*.h'):shutil.copyfile(h,dest/h.name)
 h=t/'IOKit/hidsystem/IOHIDDescriptorParser.h';h.write_text(h.read_text().replace('#if __has_include(<MacTypes.h>)','#if __has_include(<MacTypes.h>) && !defined(KERNEL)'))
 subprocess.run(['mcopy','-i',str(a.reference),'::/EFI/UniXNU/Payloads/kernel.macho',str(kernel)],check=True)
 raw=kernel.read_bytes();outer=Image(raw);im=Image(raw,outer.entries['com.apple.kernel'][1]);defined={n for rows in im.symbols().values()for n in rows}
 flags=['-target','arm64e-apple-ios27.0','-O2','-isysroot',str(a.sdk),'-fptrauth-calls','-fptrauth-returns','-fptrauth-intrinsics','-fptrauth-function-pointer-type-discrimination','-std=gnu++17','-fno-c++-static-destructors','-fno-exceptions','-fno-rtti','-fno-common','-fapple-kext','-ffreestanding','-mgeneral-regs-only','-nostdinc++','-D__PTRAUTH_INTRINSICS__=1','-D__builtin_xnu_types_compatible(T,U)=__is_same(T,U)','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-Wno-incompatible-sysroot','-Wno-deprecated-declarations','-Wno-unknown-warning-option','-Wno-unused-private-field','-Wno-c++11-narrowing','-Wno-c99-designator','-Wno-missing-designated-field-initializers','-Wno-deprecated-enum-enum-conversion']
 flags+=['-D'+v+'=1'for v in ['KERNEL','KERNEL_PRIVATE','DRIVER_PRIVATE','XNU_KERNEL_PRIVATE','XNU_TARGET_OS_OSX','PRIVATE','MACH_KERNEL_PRIVATE','__arm64__','__LP64__','__DARWIN_UNIX03']]
 for d in [t,ROOT/'UniXNU-b5q/package',a.sdk/'System/Library/Frameworks/Kernel.framework/Headers',ROOT/'sources/UniXNU/out/feeds/xnu-3199e8bc/pexpert',ROOT/'sources/UniXNU/drivers/Adreno740',ROOT/'sources/UniXNU/kits/AdrenoFirmware',ROOT/'UniXNU-b5q/package/B5qUfs',ROOT/'UniXNU-b5q/package/Sm8550Inputs',ROOT/'sources/UniXNU-sm8550-common/kits/Sm8550Platform',ROOT/'UniXNU/kits/ArmSmmu4K',ROOT/'UniXNU/kits/AdrenoPM4',ROOT/'sources/UniXNU/out/feeds/xnu-3199e8bc/libkern',ROOT/'sources/UniXNU/out/feeds/xnu-3199e8bc/EXTERNAL_HEADERS']:flags+=['-I',str(d)]
 results={};objects=[];strong_owners={};duplicates={}
 sources=[ROOT/'UniXNU-b5q/package'/name for name in ['QcomDwc3.cpp','SoftwareAesProbe.cpp','UsbProbe.cpp','B5qUsbBoard.cpp','B5qGpu.cpp','LegacyDisplayProbe.cpp','KeyStoreProbe.cpp','B5qGmuVotes.c','CpuFreqProbe.cpp','ThermalProbe.cpp','ThermalLevel.cpp','BoardClock.cpp','ButtonProbe.cpp','DisplayTimingProbe.cpp','NativeHidInput.cpp','HidInputProbe.cpp','B5qTouch.cpp','GeniI2c.c','Sm8550Gcc.c','QcomRpmh.c','B5qBootPolicy.c','B5qProcTop.c','B5qLaunchdPolicy.c','B5qPower.cpp','B5qRamStorage.cpp','B5qUfs/B5qUfs.cpp']]
 # Compile the service with its previously excluded cold-start branches.
 service=ROOT/'UniXNU/drivers/Adreno740/NativeAdrenoService.cpp';adapted=t/service.name
 adapted.write_text(service.read_text().replace('0x23b14u*4u-0x6a000u','0x23b14u*4u-SHENG_GMU_CORE_GPU_DELTA').replace('0x23b13u*4u-0x6a000u','0x23b13u*4u-SHENG_GMU_CORE_GPU_DELTA'))
 sources.append(adapted)
 timer=t/'NativeAdrenoTimer.cpp';timer.write_text('#include "ShengGmuSource.h"\n'+(ROOT/'UniXNU/drivers/Adreno740/NativeAdrenoTimer.cpp').read_text().replace('TimerGmuLow = 0x14220','TimerGmuLow = (0x1f888u*4u)-SHENG_GMU_CORE_GPU_DELTA').replace('TimerGmuHigh = 0x14224','TimerGmuHigh = (0x1f889u*4u)-SHENG_GMU_CORE_GPU_DELTA'));sources.append(timer)
 sources += [ROOT/'sources/UniXNU-sm8550-common/kits/Sm8550Platform'/name for name in ['ShengGmu.c','ShengGmuCommandDb.c','ShengGpuSmmu.c']]
 if a.sources and 'NativeAdrenoGmuService.cpp'in a.sources.split(','):
  from b5q_adreno_mmio import prepare
  original=ROOT/'UniXNU/drivers/Adreno740/NativeAdrenoGmuService.cpp'
  sources.append(prepare(original,t/original.name));flags+=['-iquote',str(original.parent)]
 if a.sources and 'NativeKeyStoreEvents.cpp'in a.sources.split(','):
  import ast
  recipe=ast.parse((ROOT/'UniXNU-b5q/scripts/build-b5q-gop-27.py').read_text())
  assignment=next(v for v in recipe.body if isinstance(v,ast.Assign)and any(isinstance(n,ast.Name)and n.id=='keyevents_patch'for n in v.targets))
  original=(ROOT/'UniXNU/drivers/AppleKeyStoreState/NativeKeyStoreEvents.cpp').read_text()
  adapted=t/'NativeKeyStoreEvents.cpp'
  adapted.write_text(eval(compile(ast.Expression(assignment.value),'owned-keystore-adapter','eval'),{'keyevents_original':original}))
  sources.append(adapted)
 if a.sources and 'NativeRamBlock.cpp'in a.sources.split(','):
  from b5q_ramblock import prepare_source
  sources.append(prepare_source(ROOT/'UniXNU/drivers/RamBlock/NativeRamBlock.cpp',t/'NativeRamBlock.cpp'))
  flags+=['-iquote',str(ROOT/'UniXNU/drivers/RamBlock')]
 if a.sources:
  selected=set(a.sources.split(','));sources=[s for s in sources if s.name in selected]
  assert {s.name for s in sources}==selected,('Unknown/uncompiled source request',selected-{s.name for s in sources})
 if any(s.name=='B5qLaunchdPolicy.c'for s in sources):
  import b5q_peripherals
  b5q_peripherals.prepare_headers(a.sdk,t,hid,ROOT/'UniXNU-b5q/package')
 if any(s.name in ('B5qUfs.cpp','B5qRamStorage.cpp','NativeRamBlock.cpp') for s in sources):
  storage=next((ROOT/'sources/UniXNU/out/feeds').glob('IOStorageFamily-*'))
  dest=t/'IOKit/storage';dest.mkdir(parents=True,exist_ok=True)
  for h in storage.glob('*.h'):shutil.copyfile(h,dest/h.name)
  # Reproduce the source-kernel's macOS branch despite its iOS Mach-O target.
  (t/'macos-target.h').write_text('#include <TargetConditionals.h>\n#undef TARGET_OS_OSX\n#define TARGET_OS_OSX 1\n')
  flags+=['-include',str(t/'macos-target.h'),'-I',str(ROOT/'sources/UniXNU/out/feeds/xnu-3199e8bc/osfmk'),'-I',str(ROOT/'sources/UniXNU/kits/VerifiedRoot/include')]

 for source in sources:
  target=t/(source.stem+'.o');cflags=flags if source.suffix=='.cpp' else [v for v in flags if v not in ['-std=gnu++17','-fno-c++-static-destructors','-fno-exceptions','-fno-rtti','-nostdinc++','-D__builtin_xnu_types_compatible(T,U)=__is_same(T,U)','-fapple-kext']]+['-x','c','-std=gnu11','-mkernel','-fptrauth-function-pointer-type-discrimination']
  if source.name=='B5qProcTop.c':cflags=cflags+['-I',str(ROOT/'sources/UniXNU/out/feeds/xnu-3199e8bc'),'-I',str(ROOT/'sources/UniXNU/out/feeds/xnu-3199e8bc/osfmk')]
  if source.name=='NativeHidInput.cpp':cflags=cflags+['-DNATIVE_HID_SOURCE_API=1']
  if a.native_recount:cflags=cflags+['-DB5Q_HAVE_CPU_IDLE_MACH=1']
  subprocess.run([str(a.compiler),*cflags,'-c',str(source),'-o',str(target)],env=env,check=True)
  if source.stem=='NativeHidInput':
   import b5q_hid
   hid_bindings,hid_result=b5q_hid.bindings(target.read_bytes(),json.loads((ROOT/'UniXNU-b5q/scripts/hid-device-26C5035r.json').read_text()))
   qualified['bindings'].update({n:hex(v)for n,v in hid_bindings.items()})
   ((a.objects_out.parent if a.objects_out else ROOT/'artifacts/b5q-runtime-v22-work')/'hid-bindings.json').write_text(json.dumps(dict(bindings={n:hex(v)for n,v in hid_bindings.items()},**hid_result),indent=2)+'\n')
  if a.objects_out:
   import shutil
   a.objects_out.mkdir(parents=True,exist_ok=True);shutil.copyfile(target,a.objects_out/target.name)
  if source.stem=='QcomDwc3':
   bindings,slots=module.all_bindings(target.read_bytes());qualified['bindings'].update({n:hex(v)for n,v in bindings.items()});(a.objects_out.parent/'usb-dual-bindings.json').write_text(json.dumps({'bindings':{n:hex(v)for n,v in bindings.items()},'slots':slots},indent=2)+'\n') if a.objects_out else None
  symbols=object_symbols(target.read_bytes());
  # Duplicate external definitions are as fatal as undefined imports. Ignore
  # weak/coalesced inline/template definitions (N_WEAK_DEF=0x80).
  data=target.read_bytes();import struct
  from b5q_abi import macho
  st=next(at for cmd,at,_ in macho(data)['commands'] if cmd==2)
  sy,count,strings,_=struct.unpack_from('<4I',data,st+8)
  for index in range(count):
   ix,kind,section,desc,value=struct.unpack_from('<IBBHQ',data,sy+index*16)
   if kind&1 and kind&0xe and not kind&0xe0 and not desc&0x80:
    name=data[strings+ix:data.index(b'\0',strings+ix)].decode()
    if name in strong_owners:duplicates.setdefault(name,[strong_owners[name]]).append(source.stem)
    else:strong_owners[name]=source.stem
  imports={n for n,_,kind in symbols if kind==1};exports={n for n,_,kind in symbols if kind!=1}
  objects.append((source.stem,imports,exports));results[source.stem]=dict(target='arm64e-ios27',imports=len(imports))
  # Match Mach-O LC_BUILD_VERSION against the source-kernel triple. This also
  # covers the separately assembled binding/address objects that failed CI.
  sys.path.insert(0,str(ROOT/'UniXNU/scripts'));os.environ.update(UNIXNU_XNU_ARCH='arm64e',UNIXNU_IOS_VERSION='27.0');import kernel_target
  kernel_target.check_object(target.read_bytes(),source.name)
  if source.stem=='QcomDwc3':
   for name in ['bindings','addresses']:
    assembly=t/(name+'.S');assembly.write_text('.text\n.p2align 2\n.globl _b5q_abi_platform_test\n_b5q_abi_platform_test:\n ret\n')
    output=t/(name+'.o');subprocess.run([str(a.compiler),'-target','arm64e-apple-ios27.0','-c',str(assembly),'-o',str(output)],env=env,check=True);kernel_target.check_object(output.read_bytes(),name)
 expected_core={'_sheng_cpu_idle_mach'} if a.native_recount else set()
 available=defined|set(qualified['bindings'])|set().union(*(e for _,_,e in objects))
 # New wireless entry points are compiled by their own same-target recipe.
 # Resolve only actual hashed objects, never an allowlist of future symbols.
 for report_path in [ROOT/'artifacts/b5q-p2-work/target/report.json',ROOT/'artifacts/b5q-p3-work/board-target/report.json']:
  if not report_path.is_file():continue
  import hashlib
  wireless=json.loads(report_path.read_text())
  for name,digest in wireless['objects'].items():
   path=Path(name)if Path(name).is_absolute()else report_path.parent/name
   if path.is_file()and hashlib.sha256(path.read_bytes()).hexdigest()==digest:
    available.update(n for n,_,kind in object_symbols(path.read_bytes())if kind&1 and kind&0xe)
 media_report=ROOT/'artifacts/b5q-p4-work/target/report.json'
 if tomllib.loads((ROOT/'UniXNU-b5q/board.toml').read_text()).get('adt',{}).get('chosen',{}).get('u32',{}).get('b5q-feature-mask',0)&63:
  media=json.loads(media_report.read_text());assert media['passed']
  for name,digest in media['objects'].items():
   path=Path(name);assert path.is_file()and hashlib.sha256(path.read_bytes()).hexdigest()==digest
   available.update(n for n,_,kind in object_symbols(path.read_bytes())if kind&1 and kind&0xe)
 if 'b5q-dp=1'in tomllib.loads((ROOT/'UniXNU-b5q/board.toml').read_text())['payload']['kernel_args']:
  dp=json.loads((ROOT/'artifacts/b5q-p5-work/target/report.json').read_text())
  assert dp['target_compile_passed']and dp['scoped_link_imports_closed']
  for name,digest in dp['actual_objects'].items():
   path=Path(name);assert path.is_file()and hashlib.sha256(path.read_bytes()).hexdigest()==digest
   available.update(n for n,_,kind in object_symbols(path.read_bytes())if kind&1 and kind&0xe)
 for stem,imports,exports in objects:
  missing=imports-available;results[stem]['unresolved']=sorted(missing-expected_core)
  results[stem]['expected_new_core_imports']=sorted(imports&expected_core)
 for n in ['_backtrace_user','_backtrace','_task_get_all_image_info_addr','_copyin','_get_user_regs','_thread_tid','_PE_parse_boot_argn']:assert n in defined,n
print(json.dumps(dict(passed=not duplicates and not any(v['unresolved'] for v in results.values()),duplicate_external_definitions=duplicates,XHCI_slots=427,objects=results,all_saved_context_external_helpers_present=True,new_core_linkage_pending=a.native_recount)))

if duplicates or any(v['unresolved'] for v in results.values()):raise SystemExit(1)
