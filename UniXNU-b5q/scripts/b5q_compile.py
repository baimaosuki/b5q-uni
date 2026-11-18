#!/usr/bin/env python3
"""Replay pinned XNU compile records without importing any board's build pipeline."""
import hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OBJ=ROOT/'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837'

def record(cpp=True):
 p=OBJ/('iokit/DEVELOPMENT/IOPlatformExpert.cpo.json' if cpp else 'osfmk/DEVELOPMENT/startup.o.json')
 return json.loads(p.read_text().strip().rstrip(','))

def compile(source,output,includes=(),flags=()):
 source,output=Path(source),Path(output);r=record(source.suffix!='.c');args=r['arguments'];cmd=[args[0],*includes];i=1;replaced=False
 while i<len(args):
  v=args[i]
  if v==r['file']:cmd.append(str(source));replaced=True
  elif v=='-o':cmd+=['-o',str(output)];i+=1
  elif v in ('-MF','-MT','-MQ','-MJ'):i+=1
  elif v in ('-MD','-MMD','-MP'):pass
  elif v=='-Xclang' and i+1<len(args) and args[i+1].startswith('-W'):i+=1
  elif not v.startswith('-W'):cmd.append(v)
  i+=1
 if not replaced:raise SystemExit('Actual source absent from XNU compile record')
 cmd+=['-Wall','-Wextra','-Werror','-Wno-unused-parameter','-mgeneral-regs-only',*flags]
 if source.suffix!='.c':cmd+=['-Wno-c99-designator','-Wno-reorder-init-list','-Wno-deprecated-enum-enum-conversion','-Wno-unnecessary-virtual-specifier']
 output.parent.mkdir(parents=True,exist_ok=True);output.with_suffix('.command.json').write_text(json.dumps(cmd,indent=2)+'\n')
 p=subprocess.run(cmd,cwd=r['directory'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
 output.with_suffix('.log').write_text(p.stdout)
 if p.returncode:raise SystemExit(str(source)+':\n'+p.stdout[-10000:])
 return output

def archive(path,objects):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.unlink(missing_ok=True)
 subprocess.run(['xcrun','ar','rcs',str(path),*[str(p) for p in objects]],check=True)
 return path

def late(source,obj):
 tool=Path(subprocess.check_output(['brew','--prefix','llvm'],text=True).strip())/'bin/llvm-objcopy';out=obj.with_suffix('.late.o')
 subprocess.run([str(tool),'--remove-section=__DATA,__mod_init_func','--globalize-symbol=__GLOBAL__sub_I_'+Path(source).name,str(obj),str(out)],check=True)
 return out

def report(path,objects,sources,extra=None):
 data=dict(source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},objects=[str(p.relative_to(ROOT)) for p in objects],archive_sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),hardware_tested=False)
 data.update(extra or {});Path(path).with_suffix('.json').write_text(json.dumps(data,indent=2)+'\n')
