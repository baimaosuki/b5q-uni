#!/usr/bin/env python3
"""Compile P4A board objects with the same arm64e PAC flags as production."""
import argparse,hashlib,json,os,subprocess,sys,tempfile
from pathlib import Path
R=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(R/'UniXNU-b5q/scripts'))
from b5q_peripherals import flags,compile_object
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--adsp',action='store_true',help='Also compile the pinned b5q ADSP firmware/transport implementation')
parser.add_argument('--audio-service',action='store_true',help='Also compile retained-DMA TFA AudioReach/service integration')
parser.add_argument('--audio-protocol',action='store_true',help='Also compile original b5q TDM AudioReach packet builders')
parser.add_argument('--video',action='store_true',help='Also compile retained-DMA Iris/VideoToolbox objects')
a=parser.parse_args()
out=R/'artifacts/b5q-p4-work/target';out.mkdir(parents=True,exist_ok=True)
sdk=R/'tools/macos-sdk/MacOSX26.5.sdk';llvm=R/'tools/llvm21/usr/lib/llvm-21/bin'
os.environ['LD_LIBRARY_PATH']=str(R/'tools/llvm21/usr/lib/x86_64-linux-gnu')
with tempfile.TemporaryDirectory(prefix='b5q-p4a-target-')as td:
    td=Path(td);header=sdk/'System/Library/Frameworks/Kernel.framework/Headers'
    p=td/'libkern/c++/OSMetaClass.h';p.parent.mkdir(parents=True)
    p.write_text((header/'libkern/c++/OSMetaClass.h').read_text().replace(
        '#if TARGET_OS_IPHONE && !TARGET_OS_SIMULATOR','#if !XNU_TARGET_OS_OSX').replace(
        '#if TARGET_OS_OSX && defined(__arm64__)','#if XNU_TARGET_OS_OSX && defined(__arm64__)'))
    p=td/'os/base.h';p.parent.mkdir(exist_ok=True)
    p.write_text((header/'os/base.h').read_text().replace(', "authenticates-null-values"',''))
    options=flags(sdk,td,header,R/'UniXNU-b5q/package',R/'sources/UniXNU',
        R/'sources/UniXNU/out/feeds/xnu-3199e8bc',True)
    options+=['-Wno-misleading-indentation','-Wno-missing-field-initializers']
    video_options=None
    video_sources=set()
    objects=[]
    sources=[R/'UniXNU-b5q/package'/n for n in ['B5qDaily.cpp','B5qBacklight.cpp','B5qUsbBoard.cpp']]
    if a.adsp:
        from b5q_adsp import prepare
        extra,include=prepare(R/'sources/UniXNU-sheng',out/'generated-adsp')
        sources+=extra+[R/'UniXNU-b5q/package/B5qMediaFirmware.c']
        options+=[flag for p in include for flag in ['-I',str(p)]]
    if a.audio_protocol:
        from b5q_audio import prepare_protocol
        extra,include=prepare_protocol(R/'sources/UniXNU-sheng',out/'generated-audio-protocol')
        sources+=extra+[R/'UniXNU-b5q/package/B5qAudioBoard.cpp']
        options=[*[flag for p in include for flag in ['-I',str(p)]],*options]
    if a.audio_service:
        from b5q_audio import prepare_service
        extra,include=prepare_service(R/'sources/UniXNU-sheng',out/'generated-audio-service')
        sources+=extra+[R/'UniXNU-b5q/package/B5qAudioDma.cpp',R/'UniXNU-b5q/package/B5qAudioMath/udivti3.c',R/'UniXNU-b5q/package/B5qAudioMath/udivmodti4.c']
        options=[*[flag for p in include for flag in ['-I',str(p)]],*options]
    if a.video:
        from b5q_video import prepare as prepare_video
        extra,include=prepare_video(R/'sources/UniXNU-sheng',R/'sources/UniXNU-sm8550-common/kits/Sm8550Platform',out/'generated-video')
        sources+=extra+[R/'UniXNU-b5q/package/B5qVideoMemory.cpp']
        video_sources=set(extra+[R/'UniXNU-b5q/package/B5qVideoMemory.cpp'])
        video_options=[*[flag for p in include for flag in ['-I',str(p)]],*options]
    if a.adsp and a.audio_protocol and a.audio_service and a.video:
        # Use the production recipe rather than maintaining a target-only list.
        from b5q_media import sources as production_sources
        sources,include=production_sources(R/'sources/UniXNU-sheng',R/'sources/UniXNU-sm8550-common/kits/Sm8550Platform',R/'UniXNU-b5q/package',out)
        sources+=[R/'UniXNU-b5q/package/B5qUsbBoard.cpp']
        options=[*[v for p in include for v in ['-I',str(p)]],*options]
        video_options=None;video_sources=set()
    for source in sources:
        name=source.name
        target=compile_object(llvm/'clang++',video_options if source in video_sources else options,
            source,out/(source.stem+'.o'),llvm)
        if name in ('B5qBacklight.cpp','B5qDaily.cpp','VtParavirt.cpp','ShengAudioService.cpp'):
            late=target.with_suffix('.late.o')
            subprocess.run([str(llvm/'llvm-objcopy'),'--remove-section=__DATA,__mod_init_func',
                '--globalize-symbol=__GLOBAL__sub_I_'+name,str(target),str(late)],check=True)
            target=late
        objects.append(target)
    (out/'report.json').write_text(json.dumps(dict(passed=True,hardware_verified=False,
        scope='P4A target compile only; joint symbols/PAC/image acceptance still required',
        objects={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in objects}),indent=2)+'\n')
print('PASS P4A actual arm64e target compile; joint symbols/PAC/integration remain required')
