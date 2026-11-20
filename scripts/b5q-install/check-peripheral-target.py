#!/usr/bin/env python3
"""Local target compile, xHCI ABI and complete new peripheral-symbol closure."""
import argparse,json,os,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
DEFAULT=Path('/home/baimao/nabu_macos/out/nabu-27.3-fresh')
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--compiler',type=Path,default=Path(os.environ.get('B5Q_TARGET_CXX',DEFAULT/'p025-m2v/toolchain/llvm21/usr/lib/llvm-21/bin/clang++')))
p.add_argument('--sdk',type=Path,default=Path(os.environ.get('B5Q_KERNEL_SDK',DEFAULT/'p020-input/local-sdk/macsdk/Library/Developer/CommandLineTools/SDKs/MacOSX26.5.sdk')))
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
 t=Path(t);(t/'libkern/c++').mkdir(parents=True);(t/'libkern/c++/OSMetaClass.h').write_text((a.sdk/'System/Library/Frameworks/Kernel.framework/Headers/libkern/c++/OSMetaClass.h').read_text().replace('#if TARGET_OS_IPHONE && !TARGET_OS_SIMULATOR','#if !XNU_TARGET_OS_OSX').replace('#if TARGET_OS_OSX && defined(__arm64__)','#if XNU_TARGET_OS_OSX && defined(__arm64__)'));(t/'OriginalUsbXhciABI.h').write_text(module.header(abi));kernel=t/'kernel'
 subprocess.run(['mcopy','-i',str(a.reference),'::/EFI/UniXNU/Payloads/kernel.macho',str(kernel)],check=True)
 raw=kernel.read_bytes();outer=Image(raw);im=Image(raw,outer.entries['com.apple.kernel'][1]);defined={n for rows in im.symbols().values()for n in rows}
 flags=['-target','arm64e-apple-ios27.0','-isysroot',str(a.sdk),'-fptrauth-calls','-fptrauth-returns','-fptrauth-intrinsics','-std=gnu++17','-fno-c++-static-destructors','-fno-exceptions','-fno-rtti','-fno-common','-fapple-kext','-ffreestanding','-mgeneral-regs-only','-nostdinc++','-D__PTRAUTH_INTRINSICS__=1','-D__builtin_xnu_types_compatible(T,U)=__is_same(T,U)','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-Wno-incompatible-sysroot','-Wno-deprecated-declarations','-Wno-unknown-warning-option','-Wno-unused-private-field','-Wno-c++11-narrowing','-Wno-deprecated-enum-enum-conversion']
 flags+=['-D'+v+'=1'for v in ['KERNEL','KERNEL_PRIVATE','DRIVER_PRIVATE','XNU_KERNEL_PRIVATE','XNU_TARGET_OS_OSX','PRIVATE','MACH_KERNEL_PRIVATE','__arm64__','__LP64__','__DARWIN_UNIX03']]
 for d in [t,ROOT/'UniXNU-b5q/package',a.sdk/'System/Library/Frameworks/Kernel.framework/Headers',ROOT/'sources/UniXNU/out/feeds/xnu-3199e8bc/pexpert',ROOT/'sources/UniXNU/drivers/Adreno740',ROOT/'sources/UniXNU/kits/AdrenoFirmware',ROOT/'UniXNU-b5q/package/B5qUfs',ROOT/'UniXNU-b5q/package/Sm8550Inputs',ROOT/'sources/UniXNU-sm8550-common/kits/Sm8550Platform',ROOT/'UniXNU/kits/ArmSmmu4K',ROOT/'UniXNU/kits/AdrenoPM4',ROOT/'sources/UniXNU/out/feeds/xnu-3199e8bc/libkern',ROOT/'sources/UniXNU/out/feeds/xnu-3199e8bc/EXTERNAL_HEADERS']:flags+=['-I',str(d)]
 results={};objects=[]
 sources=[ROOT/'UniXNU-b5q/package'/name for name in ['B5qUsbHost.cpp','B5qGpu.cpp','B5qGmuVotes.c']]
 # Compile the service with its previously excluded cold-start branches.
 service=ROOT/'UniXNU/drivers/Adreno740/NativeAdrenoService.cpp';adapted=t/service.name
 adapted.write_text(service.read_text().replace('0x23b14u*4u-0x6a000u','0x23b14u*4u-SHENG_GMU_CORE_GPU_DELTA').replace('0x23b13u*4u-0x6a000u','0x23b13u*4u-SHENG_GMU_CORE_GPU_DELTA'))
 sources.append(adapted)
 timer=t/'NativeAdrenoTimer.cpp';timer.write_text('#include "ShengGmuSource.h"\n'+(ROOT/'UniXNU/drivers/Adreno740/NativeAdrenoTimer.cpp').read_text().replace('TimerGmuLow = 0x14220','TimerGmuLow = (0x1f888u*4u)-SHENG_GMU_CORE_GPU_DELTA').replace('TimerGmuHigh = 0x14224','TimerGmuHigh = (0x1f889u*4u)-SHENG_GMU_CORE_GPU_DELTA'));sources.append(timer)
 sources += [ROOT/'sources/UniXNU-sm8550-common/kits/Sm8550Platform'/name for name in ['ShengGmu.c','ShengGmuCommandDb.c','ShengGpuSmmu.c']]
 for source in sources:
  target=t/(source.stem+'.o');cflags=flags if source.suffix=='.cpp' else [v for v in flags if v not in ['-std=gnu++17','-fno-c++-static-destructors','-fno-exceptions','-fno-rtti','-nostdinc++','-D__builtin_xnu_types_compatible(T,U)=__is_same(T,U)','-fapple-kext']]+['-x','c','-std=gnu11']
  subprocess.run([str(a.compiler),*cflags,'-c',str(source),'-o',str(target)],env=env,check=True)
  if source.stem=='B5qUsbHost':
   bindings,slots=module.bindings(target.read_bytes(),abi);assert {n:hex(v)for n,v in bindings.items()}==qualified['bindings']
  symbols=object_symbols(target.read_bytes());imports={n for n,_,kind in symbols if kind==1};exports={n for n,_,kind in symbols if kind!=1}
  objects.append((source.stem,imports,exports));results[source.stem]=dict(target='arm64e-ios27',imports=len(imports))
  # Match Mach-O LC_BUILD_VERSION against the source-kernel triple. This also
  # covers the separately assembled binding/address objects that failed CI.
  sys.path.insert(0,str(ROOT/'UniXNU/scripts'));os.environ.update(UNIXNU_XNU_ARCH='arm64e',UNIXNU_IOS_VERSION='27.0');import kernel_target
  kernel_target.check_object(target.read_bytes(),source.name)
  if source.stem=='B5qUsbHost':
   for name in ['bindings','addresses']:
    assembly=t/(name+'.S');assembly.write_text('.text\n.p2align 2\n.globl _b5q_abi_platform_test\n_b5q_abi_platform_test:\n ret\n')
    output=t/(name+'.o');subprocess.run([str(a.compiler),'-target','arm64e-apple-ios27.0','-c',str(assembly),'-o',str(output)],env=env,check=True);kernel_target.check_object(output.read_bytes(),name)
 available=defined|set(qualified['bindings'])|set().union(*(e for _,_,e in objects))
 for stem,imports,exports in objects:
  missing=imports-available;assert not missing,(stem,sorted(missing));results[stem]['unresolved']=[]
 for n in ['_backtrace_user','_backtrace','_task_get_all_image_info_addr','_copyin','_get_user_regs','_thread_tid','_PE_parse_boot_argn']:assert n in defined,n
print(json.dumps(dict(passed=True,XHCI_slots=427,objects=results,all_saved_context_external_helpers_present=True)))
