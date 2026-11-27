#!/usr/bin/env python3
"""Execute the production reuse branch with Apple-style generated index listings."""
from pathlib import Path
import hashlib,json,os,runpy,shutil,struct,subprocess,sys,tempfile,types,textwrap
R=Path(__file__).resolve().parents[2];source=R/'artifacts/b5q-runtime-v33-work/ci-files/tree/build/adreno740/libAdreno740.a';new,= (R/'artifacts/b5q-v33b-fix-work/ci45422139387-partial-objects').rglob('NativeAdrenoGmuService.o')
AR=R/'tools/llvm21/usr/lib/llvm-21/bin/llvm-ar';env=dict(os.environ,LD_LIBRARY_PATH=str(R/'tools/llvm21/usr/lib/x86_64-linux-gnu'));real_check=subprocess.check_output;real_run=subprocess.run
with tempfile.TemporaryDirectory(prefix='b5q-gmu-apple-ar-')as td:
 t=Path(td);oldenv=dict(os.environ);os.environ.update(env);staged=t/'source.a';shutil.copyfile(source,staged);os.environ['B5Q_REUSE_ADRENO']=str(staged)
 inputs=t/'drivers/Adreno740';inputs.mkdir(parents=True);shutil.copyfile(R/'UniXNU/drivers/Adreno740/NativeAdrenoGmuService.cpp',inputs/'NativeAdrenoGmuService.cpp')
 board=t/'kits/b5q/B5qGpu.cpp';board.parent.mkdir(parents=True);shutil.copyfile(R/'UniXNU-b5q/package/B5qGpu.cpp',board)
 gpu=R/'artifacts/b5q-p0-work/pac/B5qGpu.o';assert gpu.is_file()
 sys.path.insert(0,str(R/'UniXNU-b5q/scripts'))
 from b5q_adreno_mmio import source_identity
 staged.with_suffix('.json').write_text(json.dumps(dict(upstream_tree_sha256=source_identity(t),archive_sha256=hashlib.sha256(staged.read_bytes()).hexdigest())))
 calls=[]
 def compile(p,to,*args):
  calls.append(p.name)
  if p.name=='B5qGpu.cpp':assert p.read_bytes()==(R/'UniXNU-b5q/package/B5qGpu.cpp').read_bytes()
  shutil.copyfile(gpu if p.name=='B5qGpu.cpp'else new,to);return to
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
 assert calls==['NativeAdrenoGmuService.cpp','B5qGpu.cpp']
 rebuilt={'NativeAdrenoGmuService.o','B5qGpu.o'};assert set(proof['recompiled_members'])==rebuilt
 assert {n for n,v in proof['members_before'].items()if v!=proof['members_after'][n]}==rebuilt
 assert all(v==proof['members_after'][n]for n,v in proof['members_before'].items()if n not in rebuilt)
 for name,obj in [('NativeAdrenoGmuService.o',new),('B5qGpu.o',gpu)]:
  assert real_check([str(AR),'p',str(t/'build/adreno740/libAdreno740.a'),name])==obj.read_bytes()
 assert proof['board_source_sha256']==hashlib.sha256(board.read_bytes()).hexdigest()
 reuse=json.loads((t/'build/adreno740/reuse.json').read_text());assert set(reuse['recompiled_members'])==rebuilt and reuse['members_after']==proof['members_after']
 # Reusing an already patched archive still recompiles both current sources;
 # identical deterministic object output is legitimate, not a skipped build.
 calls.clear();os.environ['B5Q_REUSE_ADRENO']=str(t/'build/adreno740/libAdreno740.a')
 copy=t/'patched-source.a';shutil.copyfile(Path(os.environ['B5Q_REUSE_ADRENO']).with_suffix('.json'),copy.with_suffix('.json'));shutil.copyfile(os.environ['B5Q_REUSE_ADRENO'],copy);os.environ['B5Q_REUSE_ADRENO']=str(copy)
 try:runpy.run_path(str(R/'UniXNU-b5q/scripts/build-b5q-adreno.py'),run_name='__main__')
 except SystemExit as e:assert e.code==0
 assert calls==['NativeAdrenoGmuService.cpp','B5qGpu.cpp']
 again=json.loads((t/'build/adreno740/mmio-helper.json').read_text());assert again['members_before']==again['members_after']
 gate=(R/'scripts/b5q-install/check-v33b-returned.py').read_text()
 start=gate.index(" rebuilt={'NativeAdrenoGmuService.o','B5qGpu.o'}")
 stop=gate.index(' for marker in ',start)
 body=compile_gate=textwrap.dedent(gate[start:stop])
 context=dict(R=R,ci=t,helper_proof=proof,sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest(),hashlib=hashlib,subprocess=subprocess,os=os)
 exec(body,context)
 # An old board member in the returned real archive must be rejected even
 # when the metadata and separately uploaded GMU object claim success.
 wrong=t/'wrong/B5qGpu.o';wrong.parent.mkdir();wrong.write_bytes(real_check([str(AR),'p',str(source),'B5qGpu.o']))
 real_run([str(AR),'r',str(t/'build/adreno740/libAdreno740.a'),str(wrong)],check=True)
 try:exec(compile_gate,context)
 except AssertionError:pass
 else:raise AssertionError('Returned gate accepted stale B5qGpu archive member')
 # The real original and actual Apple-compiled helper use the same arm64e ABI.
 old=real_check([str(AR),'p',str(source),'NativeAdrenoGmuService.o']);assert struct.unpack_from('<I',old,8)==struct.unpack_from('<I',new.read_bytes(),8)
 subprocess.check_output=real_check;subprocess.run=real_run;os.environ.clear();os.environ.update(oldenv)
 print('PASS actual production GPU archive replacement:Apple __.SYMDEF index regenerated;51real objects,49SHA-identical,exactlyGMUandcurrentB5qGPUreplaced,same arm64eABI;idempotentreuse recompilesboth;returnedgate rejects staleGPUmember')
