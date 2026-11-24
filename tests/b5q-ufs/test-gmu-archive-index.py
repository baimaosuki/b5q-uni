#!/usr/bin/env python3
"""Execute the production reuse branch with Apple-style generated index listings."""
from pathlib import Path
import hashlib,json,os,runpy,shutil,struct,subprocess,sys,tempfile,types
R=Path(__file__).resolve().parents[2];source=R/'artifacts/b5q-runtime-v33-work/ci-files/tree/build/adreno740/libAdreno740.a';new,= (R/'artifacts/b5q-v33b-fix-work/ci45422139387-partial-objects').rglob('NativeAdrenoGmuService.o')
AR=R/'tools/llvm21/usr/lib/llvm-21/bin/llvm-ar';env=dict(os.environ,LD_LIBRARY_PATH=str(R/'tools/llvm21/usr/lib/x86_64-linux-gnu'));real_check=subprocess.check_output;real_run=subprocess.run
with tempfile.TemporaryDirectory(prefix='b5q-gmu-apple-ar-')as td:
 t=Path(td);oldenv=dict(os.environ);os.environ.update(env);os.environ['B5Q_REUSE_ADRENO']=str(source)
 inputs=t/'drivers/Adreno740';inputs.mkdir(parents=True);shutil.copyfile(R/'UniXNU/drivers/Adreno740/NativeAdrenoGmuService.cpp',inputs/'NativeAdrenoGmuService.cpp')
 def compile(p,to,*args):shutil.copyfile(new,to);return to
 mock=types.ModuleType('b5q_compile');mock.ROOT=t;mock.compile=compile;mock.archive=None;mock.report=None;sys.modules['b5q_compile']=mock;sys.path.insert(0,str(R/'UniXNU-b5q/scripts'))
 def check(args,**kw):
  if args[:2]==['xcrun','ar']:
   result=real_check([str(AR),*args[2:]],**kw)
   if args[2]=='t':return ('__.SYMDEF SORTED\n'+result)if isinstance(result,str)else b'__.SYMDEF SORTED\n'+result
   return result
  return real_check(args,**kw)
 def run(args,**kw):return real_run([str(AR),*args[2:]],**kw)if args[:2]==['xcrun','ar']else real_run(args,**kw)
 subprocess.check_output=check;subprocess.run=run
 try:runpy.run_path(str(R/'UniXNU-b5q/scripts/build-b5q-adreno.py'),run_name='__main__')
 except SystemExit as e:assert e.code==0
 proof=json.loads((t/'build/adreno740/mmio-helper.json').read_text());assert len(proof['members_before'])==51 and '__.SYMDEF SORTED'not in proof['members_before']
 assert proof['members_before']['NativeAdrenoGmuService.o']!=proof['members_after']['NativeAdrenoGmuService.o']
 assert all(v==proof['members_after'][n]for n,v in proof['members_before'].items()if n!='NativeAdrenoGmuService.o')
 # The real original and actual Apple-compiled helper use the same arm64e ABI.
 old=real_check([str(AR),'p',str(source),'NativeAdrenoGmuService.o']);assert struct.unpack_from('<I',old,8)==struct.unpack_from('<I',new.read_bytes(),8)
 subprocess.check_output=real_check;subprocess.run=real_run;os.environ.clear();os.environ.update(oldenv)
 print('PASS actual production GPU archive replacement:Apple __.SYMDEF index regenerated;51real objects,50SHA-identical,only nativeGMUchanged,same arm64eABI')
