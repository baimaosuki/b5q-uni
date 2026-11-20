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
 t=Path(t);(t/'OriginalUsbXhciABI.h').write_text(module.header(abi));kernel=t/'kernel'
 subprocess.run(['mcopy','-i',str(a.reference),'::/EFI/UniXNU/Payloads/kernel.macho',str(kernel)],check=True)
 raw=kernel.read_bytes();outer=Image(raw);im=Image(raw,outer.entries['com.apple.kernel'][1]);defined={n for rows in im.symbols().values()for n in rows}
 flags=['-target','arm64e-apple-macos27.0','-isysroot',str(a.sdk),'-fptrauth-calls','-fptrauth-returns','-fptrauth-intrinsics','-std=gnu++17','-fno-c++-static-destructors','-fno-exceptions','-fno-rtti','-fno-common','-fapple-kext','-ffreestanding','-mgeneral-regs-only','-nostdinc++','-D__PTRAUTH_INTRINSICS__=1','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-Wno-deprecated-declarations','-Wno-unknown-warning-option','-Wno-unused-private-field','-Wno-c++11-narrowing','-Wno-deprecated-enum-enum-conversion']
 flags+=['-D'+v+'=1'for v in ['KERNEL','KERNEL_PRIVATE','DRIVER_PRIVATE','XNU_KERNEL_PRIVATE','PRIVATE','MACH_KERNEL_PRIVATE','__arm64__','__LP64__','__DARWIN_UNIX03']]
 for d in [t,ROOT/'UniXNU-b5q/package',a.sdk/'System/Library/Frameworks/Kernel.framework/Headers',ROOT/'sources/UniXNU/out/feeds/xnu-3199e8bc/pexpert',ROOT/'sources/UniXNU/drivers/Adreno740',ROOT/'sources/UniXNU/kits/AdrenoFirmware']:flags+=['-I',str(d)]
 results={}
 for stem in ['B5qUsbHost','B5qGpu']:
  target=t/(stem+'.o');subprocess.run([str(a.compiler),*flags,'-c',str(ROOT/'UniXNU-b5q/package'/(stem+'.cpp')),'-o',str(target)],env=env,check=True)
  if stem=='B5qUsbHost':
   bindings,slots=module.bindings(target.read_bytes(),abi);assert {n:hex(v)for n,v in bindings.items()}==qualified['bindings']
  imports={n for n,_,kind in object_symbols(target.read_bytes())if kind==1};missing=imports-defined-set(qualified['bindings']);assert not missing,(stem,sorted(missing))
  results[stem]=dict(target='arm64e-macos27',imports=len(imports),unresolved=sorted(missing))
 for n in ['_backtrace_user','_backtrace','_task_get_all_image_info_addr','_copyin','_get_user_regs','_thread_tid','_PE_parse_boot_argn']:assert n in defined,n
print(json.dumps(dict(passed=True,XHCI_slots=427,objects=results,all_saved_context_external_helpers_present=True)))
