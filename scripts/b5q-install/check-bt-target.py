#!/usr/bin/env python3
"""Compile the exact Bluetooth source recipe against the local target SDK.

No CI is triggered here. Final P2+P3 symbol/PAC closure is a separate joint gate.
"""
import hashlib,importlib.util,json,os,shlex,subprocess,sys,tempfile
from pathlib import Path
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'UniXNU-b5q/scripts'))
from b5q_peripherals import flags,compile_object
from b5q_bluetooth import prepare
out=R/'artifacts/b5q-p2-work/target';out.mkdir(parents=True,exist_ok=True)
sdk=R/'tools/macos-sdk/MacOSX26.5.sdk';llvm=R/'tools/llvm21/usr/lib/llvm-21/bin';cxx=llvm/'clang++'
os.environ['LD_LIBRARY_PATH']=str(R/'tools/llvm21/usr/lib/x86_64-linux-gnu')
component=R/'sources/UniXNU-sheng/drivers/QcaBluetooth'
sources,includes=prepare(component,R/'UniXNU-b5q/package',R/'sources/UniXNU-sm8550-common/kits/Sm8550Platform',out/'generated')
with tempfile.TemporaryDirectory(prefix='b5q-bt-target-') as td:
    td=Path(td);header=sdk/'System/Library/Frameworks/Kernel.framework/Headers'
    p=td/'libkern/c++/OSMetaClass.h';p.parent.mkdir(parents=True)
    p.write_text((header/'libkern/c++/OSMetaClass.h').read_text().replace('#if TARGET_OS_IPHONE && !TARGET_OS_SIMULATOR','#if !XNU_TARGET_OS_OSX').replace('#if TARGET_OS_OSX && defined(__arm64__)','#if XNU_TARGET_OS_OSX && defined(__arm64__)'))
    p=td/'os/base.h';p.parent.mkdir(exist_ok=True)
    p.write_text((header/'os/base.h').read_text().replace(', "authenticates-null-values"',''))
    xnu=R/'sources/UniXNU/out/feeds/xnu-3199e8bc'
    options=flags(sdk,td,header,R/'UniXNU-b5q/package',R/'sources/UniXNU',xnu,True)
    options += ['-Wno-sign-compare']
    for p in includes:options += ['-I',str(p)]
    objects=[]
    for source in sources:
        # The native tty owns cdevsw/selinfo/lock startup objects. Compile
        # against pinned XNU private definitions, never SDK approximations.
        selected=options
        if source.name=='btqca.c':
            selected=[*options,'-include',str(R/'UniXNU-b5q/package/B5qBtLinuxCompat.h')]
        if source.name=='qbt_tty.c':
            native=R/'artifacts/b5q-p2-work/xnu-private-source'
            generated=R/'artifacts/b5q-p2-work/xnu-private-headers'
            config=next(line.split('=',1)[1] for line in (generated/'Makefile').read_text().splitlines()
                        if line.startswith('export CONFIG_DEFINES ='))
            (td/'os/base.h').write_text((native/'libkern/os/base.h').read_text().replace(', "authenticates-null-values"',''))
            bsd_options=[v for v in options if v!='-DMACH_KERNEL_PRIVATE=1']
            selected=['-I',str(td),'-I',str(generated),'-I',str(native/'bsd'),'-I',str(native/'osfmk'),
                '-I',str(native/'pexpert'),'-I',str(native),'-I',str(native/'libkern'),
                *shlex.split(config),'-DARM64_BOARD_CONFIG_BCM2837','-DMACH_KERNEL',
                '-D_KERNEL_BUILD','-DKERNEL_BUILD','-DBSD_BUILD','-DBSD_KERNEL_PRIVATE',
                '-include',str(generated/'meta_features.h'),*bsd_options]
        objects.append(compile_object(cxx,selected,source,out/(source.stem+'.o'),llvm))
result=dict(status='TARGET_OBJECTS_COMPILED',joint_P2_P3_symbol_PAC_gate_pending=True,
    hardware_verified=False,objects={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in objects})
(out/'report.json').write_text(json.dumps(result,indent=2)+'\n')
print('PASS',len(objects),'Bluetooth arm64e objects compiled; joint P2/P3 closure remains required')
