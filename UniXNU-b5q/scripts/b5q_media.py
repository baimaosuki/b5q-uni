"""Production P4 source selection; exactly the target-tested media recipe."""
import hashlib,json
from pathlib import Path
from b5q_adsp import prepare as adsp,REVISION
from b5q_audio import prepare_protocol,prepare_service
from b5q_video import prepare as video
from b5q_wireless import checkout
from b5q_peripherals import compile_object

def sources(reference,soc,package,out):
    base=[package/n for n in ['B5qDaily.cpp','B5qBacklight.cpp','B5qMediaFirmware.c',
        'B5qAudioBoard.cpp','B5qAudioDma.cpp','B5qVideoMemory.cpp',
        'B5qAudioMath/udivti3.c','B5qAudioMath/udivmodti4.c']]
    groups=[]
    for generator,name in [(adsp,'adsp'),(prepare_protocol,'audio-protocol'),(prepare_service,'audio-service')]:
        extra,include=generator(reference,out/('generated-'+name));groups.append((extra,include))
    extra,include=video(reference,soc,out/'generated-video');groups.append((extra,include))
    includes=[p for _,ps in groups for p in ps]
    return base+[p for ps,_ in groups for p in ps],sorted(dict.fromkeys(includes),key=lambda p:not p.is_relative_to(out))

def build(tree,package,out,cxx,cflags,llvm):
    import subprocess
    out.mkdir(parents=True,exist_ok=True)
    reference=checkout(tree,'UniXNU-sheng','https://github.com/UniXNU/UniXNU-sheng.git',REVISION)
    inputs,include=sources(reference,tree/'kits/Sm8550Platform',package,out)
    options=[*[v for p in include for v in ['-I',str(p)]],*cflags,
        '-Wno-misleading-indentation','-Wno-missing-field-initializers']
    objects=[]
    for source in inputs:
        target=compile_object(cxx,options,source,out/(source.stem+'.o'),llvm)
        if source.name in ('B5qDaily.cpp','B5qBacklight.cpp','ShengAudioService.cpp','VtParavirt.cpp'):
            late=target.with_suffix('.late.o')
            subprocess.run([str(llvm/'llvm-objcopy'),'--remove-section=__DATA,__mod_init_func',
                '--globalize-symbol=__GLOBAL__sub_I_'+source.name,str(target),str(late)],check=True)
            target=late
        objects.append(target)
    (out/'media-build.json').write_text(json.dumps(dict(hardware_verified=False,
        sources={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in inputs},
        objects={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in objects}),indent=2)+'\n')
    return objects
