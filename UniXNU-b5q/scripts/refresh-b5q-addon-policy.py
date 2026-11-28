#!/usr/bin/env python3
"""Refresh only the WiFi launchd job in a reused addon; preserve every executable."""
import argparse,ast,hashlib,importlib.util,json,plistlib,subprocess,sys,tempfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--unixnu',type=Path,required=True);p.add_argument('--input',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
source=Path(__file__).with_name('build-b5q-wifi-userspace.py')
recipe=ast.parse(source.read_text());assignment=next(n for n in recipe.body if isinstance(n,ast.Assign)and any(isinstance(v,ast.Name)and v.id=='job'for v in n.targets))
job=eval(compile(ast.Expression(assignment.value),str(source),'eval'),{'plistlib':plistlib})
assert job['RunAtLoad']is False and job['ThrottleInterval']>=60 and job['KeepAlive']=={'PathState':{'/private/var/run/b5q-wifi-ready':True}}
tool=a.unixnu/'scripts/addon-add-dir.py';s=importlib.util.spec_from_file_location('addon',tool);codec=importlib.util.module_from_spec(s);s.loader.exec_module(codec)
before=codec.read(a.input);old={n:(mode,b)for n,mode,b in before};assert len(old)==len(before)
name='Library/LaunchDaemons/org.unixnu.wifi.supplicant.plist'
a.out.parent.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='b5q-addon-policy-')as td:
 directory=Path(td);(directory/Path(name).name).write_bytes(plistlib.dumps(job));(directory/Path(name).name).chmod(0o644)
 subprocess.run([sys.executable,str(tool),str(a.input),str(a.out),'Library/LaunchDaemons',str(directory)],check=True)
after=codec.read(a.out);new={n:(mode,b)for n,mode,b in after};assert len(new)==len(after)
assert all(new[n]==v for n,v in old.items()if n!=name)
assert new[name]==(0o644,plistlib.dumps(job)) and new.keys()==old.keys()|{name}
report=dict(passed=True,only_changed_member=name,all_other_members_identical=True,executable_and_CodeDirectory_bytes_unchanged=True,trustcache_update_required=False,job=job,source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),input_sha256=hashlib.sha256(a.input.read_bytes()).hexdigest(),output_sha256=hashlib.sha256(a.out.read_bytes()).hexdigest())
a.out.with_suffix('.policy.json').write_text(json.dumps(report,indent=2)+'\n');print('PASS reused addon explicitly refreshed via addon-add-dir; unchanged executable bytes retain their owner trust')
