#!/usr/bin/env python3
"""Refresh board launchd/plist policy in an addon; preserve every executable."""
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
update_name='Library/LaunchDaemons/org.unixnu.software-update-policy.plist'
script_name='etc/b5q-software-update-policy.sh'
update_job={'Label':'org.unixnu.software-update-policy','ProgramArguments':['/bin/sh','/private/var/ngpu/etc/b5q-software-update-policy.sh'],
            'RunAtLoad':True,'LaunchOnlyOnce':True,'UserName':'root','ProcessType':'Background','Umask':0o22}
update_script=Path(__file__).resolve().parents[1]/'package/b5q-software-update-policy.sh'
a.out.parent.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='b5q-addon-policy-')as td:
 directory=Path(td);jobs=directory/'jobs';etc=directory/'etc';jobs.mkdir();etc.mkdir()
 for label,value in [(name,job),(update_name,update_job)]:
  dest=jobs/Path(label).name;dest.write_bytes(plistlib.dumps(value));dest.chmod(0o644)
 dest=etc/Path(script_name).name;dest.write_bytes(update_script.read_bytes());dest.chmod(0o644)
 subprocess.run([sys.executable,str(tool),str(a.input),str(a.out),'Library/LaunchDaemons',str(jobs),'etc',str(etc)],check=True)
after=codec.read(a.out);new={n:(mode,b)for n,mode,b in after};assert len(new)==len(after)
allowed={name,update_name,script_name}
assert all(new[n]==v for n,v in old.items()if n not in allowed)
assert new[name]==(0o644,plistlib.dumps(job)) and new.keys()==old.keys()|allowed
assert new[update_name]==(0o644,plistlib.dumps(update_job)) and new[script_name]==(0o644,update_script.read_bytes())
report=dict(passed=True,all_members_outside_explicit_policy_set_identical=True,executable_and_CodeDirectory_bytes_unchanged=True,trustcache_update_required=False,job=job,source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),input_sha256=hashlib.sha256(a.input.read_bytes()).hexdigest(),output_sha256=hashlib.sha256(a.out.read_bytes()).hexdigest())
report.update(only_changed_members=sorted(allowed))
a.out.with_suffix('.policy.json').write_text(json.dumps(report,indent=2)+'\n');print('PASS reused addon explicitly refreshed via addon-add-dir; unchanged executable bytes retain their owner trust')
