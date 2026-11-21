#!/usr/bin/env python3
"""Recompile board objects and relink the pinned v19 XNU archive.

No XNU translation unit, Mesa/Turnip, Metal plugin or Data seed is rebuilt.
The link flags are the pinned XNU MakeInc.def arm64 DEVELOPMENT flags.
"""
import argparse,hashlib,importlib.util,json,os,re,shutil,struct,subprocess,sys
from pathlib import Path

def sha(p):
 with Path(p).open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
def run(args,**kw):
 print('+ '+' '.join(map(str,args)),flush=True);subprocess.run(list(map(str,args)),check=True,**kw)
def members(path):
 data=path.read_bytes();assert data[:8]==b'!<arch>\n';off=8
 while off<len(data):
  h=data[off:off+60];size=int(h[48:58]);body=data[off+60:off+60+size];name=h[:16].strip().decode();off+=60+size+(size%2)
  if name.startswith('#1/'):
   n=int(name[3:]);name=body[:n].rstrip(b'\0').decode();body=body[n:]
  if body[:4]==b'\xcf\xfa\xed\xfe':yield name,body

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--unixnu',type=Path,required=True);p.add_argument('--device',type=Path,required=True)
 p.add_argument('--cached-tree',type=Path,required=True);p.add_argument('--prepare-only',action='store_true')
 p.add_argument('--out',type=Path,required=True);p.add_argument('--changed',help='Comma separated changed board sources; reuse all other archive members');p.add_argument('--source-run',type=int,default=44789459847);p.add_argument('--source-commit',default='6c57bd844b2ad2fd67a93854781481c095db7c53');a=p.parse_args();selected=set(a.changed.split(',')) if a.changed else None
 core,device,cached,out=map(Path.resolve,[a.unixnu,a.device,a.cached_tree,a.out]);out.mkdir(parents=True,exist_ok=True)
 sys.path[:0]=[str(device/'scripts'),str(core/'scripts'),str(core/'kits/XnuPrelink')]
 from b5q_abi import object_symbols
 from kc_image import Image
 from b5q_peripherals import SOURCES,prepare_headers,flags as peripheral_flags,compile_object,build_added
 inputs=[
 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837.link/mach.development.bcm2837.a',
 'build/firehose/sym/Release-iphoneos/liblibfirehose_kernel.a',
 'build/corecrypto-2023/libcorecrypto_kernel_noasm-namespaced.a',
 'build/armdt-platform/libArmDTPlatform.a','build/armcpu/libArmCpu.a',
 'build/adreno740/libAdreno740.a','build/native-legacy-display/libNativeLegacyDisplay.late.a',
 'build/libpthread-kernel/libpthread_kernel.a','build/ram-block/libRamBlock.a','build/software-aes/libSoftwareAES.a']
 native=cached/'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837.unstripped.noctf'
 original=Image(native.read_bytes());defined=set();imports=set()
 for rel in inputs:
  for name,body in members(cached/rel):
   for symbol,value,kind in object_symbols(body):
    if not kind&1:continue
    if kind&0xe==0 and not value:imports.add(symbol)
    else:defined.add(symbol)
 xnu=next((core/'out/feeds').glob('xnu-*'))
 originals={n:va for va,names in original.symbols().items()for n in names}
 aliases={}
 # Use the upstream exports syntax (config/generate_linker_aliases.sh),
 # checking against the exact original native image to select its platform.
 for exports in (xnu/'config').glob('*.exports'):
  for line in exports.read_text().splitlines():
   match=re.fullmatch(r'\s*([^#\s:]+)\s*:\s*([^#\s:]+)\s*(?:#.*)?',line)
   if not match:continue
   name,target=match.groups()
   if name in originals and target in originals and target in defined and originals[name]==originals[target]:aliases[name]=target
 alias=out/'all-alias.exp';alias.write_text(''.join(f'{v} {k}\n'for k,v in sorted(aliases.items())))
 symbolsets=next(s for s in original.sections if s['segment']=='__LINKINFO'and s['name']=='__symbolsets')
 (out/'symbolsets.plist').write_bytes(original.read(symbolsets['va'],symbolsets['size']))
 record={'source_run':a.source_run,'source_commit':a.source_commit,
   'unchanged_inputs':{rel:sha(cached/rel)for rel in inputs},'native_reference_sha256':sha(native),
   'source_sha256':{n:sha(device/'package'/n)for n in ['B5qUsbHost.cpp','B5qUsbPolicy.h','LegacyDisplayProbe.cpp','B5qGpu.cpp',*SOURCES]},
   'core_translation_units_compiled':0,'board_translation_units_compiled':0,'aliases_from_same_v19_native':aliases}
 # Read actual XNU flags from the pinned pristine source. No device tables are copied.
 xnu=next((core/'out/feeds').glob('xnu-*'))
 source=(xnu/'makedefs/MakeInc.def').read_text()
 def flags(name):
  m=re.search(r'^'+name+r'\s*=\s*\\\n((?:[^\n]*\\\n)*[^\n]*)',source,re.M)
  if not m:raise RuntimeError('Missing XNU linker flag group '+name)
  text=m[1].replace('\\\n',' ')
  substitutions={'ARM64_PLKSEG_ADDR':'0xfffffff004004000','ARM64_LINK_ADDR':'0xfffffff007004000',
   'LDFLAGS_KERNEL_SEGARM64_SEG_ORDER':'__TEXT:__DATA_CONST:__DATA_SPTM:__LINKEDIT:__TEXT_EXEC:__TEXT_BOOT_EXEC:__KLD:__PPLTEXT:__PPLTRAMP:__PPLDATA_CONST:__LASTDATA_CONST:__LAST:__PPLDATA:__KLDDATA:__DATA:__HIBDATA:__BOOTDATA'}
  for k,v in substitutions.items():text=text.replace('$('+k+')',v)
  import shlex
  return shlex.split(text)
 linkflags=flags('LDFLAGS_KERNEL_GEN')+flags('LDFLAGS_KERNEL_GENARM64')+flags('LDFLAGS_KERNEL_SEGARM64')
 record['linkflags']=linkflags
 if a.prepare_only:
  (out/'incremental-inputs.json').write_text(json.dumps(record,indent=2)+'\n');return
 if sys.platform!='darwin':raise SystemExit('Build uses the pinned Xcode Darwin linker; --prepare-only is portable')
 from unixnu.cli import parser
 from unixnu.config import Context
 from unixnu import kernel
 ctx=Context(parser().parse_args(['build','payload','--device',str(device),'--os','macos-27.3-26C5035r']))
 # Reuse source archives byte-for-byte, replacing only changed members in copies.
 for rel in inputs:
  target=ctx.tree/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(cached/rel,target)
 llvm=Path(subprocess.check_output(['brew','--prefix','llvm'],text=True).strip())/'bin'
 cxx=subprocess.check_output(['xcrun','--find','clang++'],text=True).strip()
 sdk=Path(subprocess.check_output(['xcrun','--sdk','macosx','--show-sdk-path'],text=True).strip())
 include=out/'include'
 hid=next((core/'out/feeds').glob('IOHIDFamily-*'))
 header=prepare_headers(sdk,include,hid)
 spec=importlib.util.spec_from_file_location('usb_builder',device/'scripts/build-b5q-usb.py');usb=importlib.util.module_from_spec(spec);spec.loader.exec_module(usb)
 (include/'OriginalUsbXhciABI.h').write_text(usb.header(json.loads((device/'scripts/usb-xhci-26C5035r.json').read_text())))
 cflags=peripheral_flags(sdk,include,header,device/'package',ctx.tree,xnu,'_sheng_cpu_idle_mach' in defined)
 replacements={'B5qUsbHost.cpp':'build/native-legacy-display/libNativeLegacyDisplay.late.a','LegacyDisplayProbe.cpp':'build/native-legacy-display/libNativeLegacyDisplay.late.a','B5qGpu.cpp':'build/adreno740/libAdreno740.a'}
 for name,rel in replacements.items():
  if selected is not None and name not in selected:continue
  obj=compile_object(cxx,cflags,device/'package'/name,out/(Path(name).stem+'.o'),llvm)
  run(['xcrun','ar','r',ctx.tree/rel,obj]);record['board_translation_units_compiled']+=1
 added=build_added(device/'package',out/'input',cxx,cflags,llvm,device/'scripts',selected)
 if added:run(['xcrun','ar','r',ctx.tree/inputs[6],*added])
 record['board_translation_units_compiled']+=len(SOURCES if selected is None else [n for n in SOURCES if n in selected])
 record['added_objects']={p.name:sha(p) for p in added}
 record['optional_cpu_idle_helper_present']='_sheng_cpu_idle_mach' in defined
 native_out=ctx.tree/ctx.board['kernel']['prelink']['kernel'];native_out.parent.mkdir(parents=True,exist_ok=True)
 command=['xcrun','--sdk','iphoneos','clang++','-target','arm64e-apple-ios27.0',*linkflags,
   '-Wl,-add_split_seg_info','-Wl,-kernel','-Wl,-alias_list,'+str(alias),
   '-Wl,-sectcreate,__LINKINFO,__symbolsets,'+str(out/'symbolsets.plist'),'-Wl,-segprot,__LINKINFO,r--,r--',
   '-Wl,-force_load,'+str(ctx.tree/inputs[0]),'-lcc_kext',str(ctx.tree/inputs[1]),str(ctx.tree/inputs[2])]
 for rel in inputs[3:]:command+=['-Wl,-force_load,'+str(ctx.tree/rel)]
 command+=['-o',str(native_out)]
 (out/'link-command.json').write_text(json.dumps(command,indent=2)+'\n');run(command)
 run([sys.executable,ctx.tree/'scripts/seal-source-crypto-kernel.py',native_out],env=dict(os.environ,UNIXNU_XNU_ARCH='arm64e',UNIXNU_IOS_VERSION='27.0',UNIXNU_XNU_TARGET='macosx'))
 record['unchanged_core_after_link_sha256']=sha(ctx.tree/inputs[0]);record['native_output_sha256']=sha(native_out)
 record['archive_outputs']={rel:sha(ctx.tree/rel)for rel in [inputs[5],inputs[6]]};record['changed_board_sources']=sorted(selected) if selected is not None else None
 os.environ.update(UNIXNU_XNU_ARCH='arm64e',UNIXNU_IOS_VERSION='27.0',UNIXNU_XNU_TARGET='macosx')
 kernel.prelink(ctx)
 reuse_path=ctx.work/'kernel-reuse.json'
 reuse=json.loads(reuse_path.read_text()) if reuse_path.is_file() else {}
 reuse.update(kernel_recompiled=True,kernel_core_recompiled=False,kernel_relinked=True,board_objects_recompiled=record['board_translation_units_compiled'],incremental_record='kernel/incremental-relink.json')
 reuse_path.write_text(json.dumps(reuse,indent=2)+'\n')
 (ctx.work/'kernel/incremental-relink.json').write_text(json.dumps(record,indent=2)+'\n')
 (out/'incremental-inputs.json').write_text(json.dumps(record,indent=2)+'\n')
if __name__=='__main__':main()
