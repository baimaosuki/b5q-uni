#!/usr/bin/env python3
"""Run actual runtime.prepare and WiFi merge with an explicit reused GPU base."""
import ast,hashlib,importlib.util,json,os,plistlib,subprocess,sys,tempfile,tomllib,types
from pathlib import Path
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'UniXNU/scripts'))
from unixnu import runtime
spec=importlib.util.spec_from_file_location('addon',R/'UniXNU/scripts/addon-add-dir.py');addon=importlib.util.module_from_spec(spec);spec.loader.exec_module(addon)
production=ast.parse((R/'UniXNU/scripts/build-boot-runtime.py').read_text());main=next(n for n in production.body if isinstance(n,ast.FunctionDef)and n.name=='main')
# Pick the exact, production-level WiFi append branch, not a rewritten model.
branch=next(n for n in ast.walk(main)if isinstance(n,ast.If)and ast.unparse(n.test)=="request.get('wifi_tool')")
producer=ast.parse((R/'UniXNU-b5q/scripts/build-b5q-wifi-userspace.py').read_text());job=next(n for n in producer.body if isinstance(n,ast.Assign)and any(isinstance(v,ast.Name)and v.id=='job'for v in n.targets))
expected=eval(compile(ast.Expression(job.value),'production-wifi-job','eval'),{'plistlib':plistlib})
assert expected['RunAtLoad']is False and expected['KeepAlive']=={'PathState':{'/private/var/run/b5q-wifi-ready':True}}and expected['ThrottleInterval']>=60
with tempfile.TemporaryDirectory(prefix='b5q-reuse-addon-policy-')as td:
 td=Path(td);seed=td/'data.dbr';seed.write_bytes(b'test-seed-boundary');trust=td/'trust';trust.write_bytes(b'test-trust-boundary')
 old=td/'gpu-addon.bin';gpu=('Library/GPUBundles/AdrenoMetal.bundle/Contents/MacOS/AdrenoMetal',0o755,b'unchanged signed GPU boundary')
 target='Library/LaunchDaemons/org.unixnu.wifi.supplicant.plist'
 addon.write(old,[gpu,(target,0o644,plistlib.dumps({'Label':expected['Label'],'KeepAlive':True,'ThrottleInterval':3,'RunAtLoad':True}))])
 builder_calls=[];append_calls=[]
 def execute_wifi(request):
  out=Path(request['output']);out.mkdir(exist_ok=True,parents=True);work=td/'runtime-work';work.mkdir(exist_ok=True)
  def run(*args):
   # Only native macOS compiler/codesign is a test double. The launchd job
   # comes from the real source assignment; the addon codec/merge are real.
   assert Path(args[1]).name=='build-b5q-wifi-userspace.py';builder_calls.append(str(args[1]));dest=Path(args[2])
   for n in ['bin','etc/wifi','daemons']:(dest/n).mkdir(parents=True,exist_ok=True)
   (dest/'daemons/org.unixnu.wifi.supplicant.plist').write_bytes(plistlib.dumps(expected))
   (dest/'report.json').write_text(json.dumps({'daemons_prefix':'Library/LaunchDaemons'}))
  def script(name,*args):
   assert name=='addon-add-dir.py';append_calls.append(name);subprocess.run([sys.executable,str(R/'UniXNU/scripts'/name),*map(str,args)],check=True)
  scope=dict(request=request,work=work,out=out,addon=Path(request['gpu_addon']),bluetooth_report=None,json=json,Path=Path,run=run,script=script,sys=sys)
  exec(compile(ast.Module(body=[branch],type_ignores=[]),'actual-wifi-runtime-branch','exec'),scope)
  final=scope['addon'];(out/'generated.json').write_text(json.dumps(dict(data_ramdisk=str(seed),gpu_addon=str(final),trust_cache=str(trust))))
 board=tomllib.loads((R/'UniXNU-b5q/board.toml').read_text());board['payload']['runtime'].pop('bluetooth_tool',None)
 class Ipsw:
  def __init__(self,ctx):pass
  def disk_image(self,name):return td/'mock-OS-image'
 args=types.SimpleNamespace(data_ramdisk=str(seed),gpu_addon=str(old),owner_trust_cache=str(trust),trust_cache=None)
 ctx=types.SimpleNamespace(board=board,args=args,work=td/'work',tree=R/'UniXNU',device=R/'UniXNU-b5q',logs=td)
 def dispatched(command,**kwargs):
  assert Path(command[1]).name=='build-b5q-media-runtime.py';request=json.loads(Path(command[-1]).read_text());assert request['gpu_addon']==str(old);execute_wifi(request)
 runtime.Ipsw=Ipsw;runtime.run=dispatched;runtime.bind_seed=lambda *args,**kw:'TEST-UUID';runtime.log=lambda *args:None
 runtime.prepare(ctx)
 entries=addon.read(ctx.args.gpu_addon);files={n:(mode,data)for n,mode,data in entries}
 assert files[gpu[0]]==gpu[1:]and len([n for n,_,_ in entries if n==target])==1
 assert plistlib.loads(files[target][1])==expected and len(builder_calls)==len(append_calls)==1
 # Re-applying the production append is idempotent and never duplicates jobs.
 request=json.loads((ctx.work/'runtime/request.json').read_text());request['gpu_addon']=ctx.args.gpu_addon;execute_wifi(request)
 again=addon.read(json.loads((ctx.work/'runtime/generated.json').read_text())['gpu_addon']);assert again==entries
 print('PASS actual explicit--reuse-addon runtime.prepare dispatches WiFi tool; real addon-add-dir replaces oldRunAtLoad/KeepAlive3s job, GPU bytes unchanged, onejob,idempotent')
