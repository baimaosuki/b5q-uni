#!/usr/bin/env python3
"""Apply the exact resolved patch plan in a disposable clone, without a compiler."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--unixnu',type=Path,required=True)
p.add_argument('--source',type=Path,required=True)
a=p.parse_args()
unixnu=a.unixnu.resolve();device=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(unixnu/'scripts'))
from unixnu.cli import parser
from unixnu.config import Context
from unixnu import feeds,patches
ctx=Context(parser().parse_args(['tree','--device',str(device),'--os','macos-27.3-26C5035r']))
modules=feeds.resolve(ctx);plan=patches.plan(ctx,modules)
def run(cmd):
 r=subprocess.run([str(x) for x in cmd],capture_output=True,text=True)
 if r.returncode:raise RuntimeError(r.stderr.strip() or r.stdout.strip())
 return r.stdout.strip()
source=a.source.resolve();revision=run(['git','-C',source,'rev-parse','HEAD'])
expected=ctx.board['os']['xnu_revision']
if revision!=expected:raise SystemExit('XNU source revision does not match target profile')
report={'os_profile':'macos-27.3-26C5035r','xnu_revision':revision,'scope':'Ordered git apply test only; not source generation, compilation or hardware validation','patches':[],'result':'FAIL'}
try:
 with tempfile.TemporaryDirectory(prefix='b5q-xnu-patch-check-') as temp:
  work=Path(temp)/'xnu'
  run(['git','clone','--quiet','--shared','--no-checkout',source,work])
  run(['git','-C',work,'checkout','--quiet','--detach',revision])
  for patch in plan:
   item={'name':patch.name,'sha256':hashlib.sha256(patch.read_bytes()).hexdigest(),'result':'FAIL'}
   report['patches'].append(item)
   run(['git','-C',work,'apply','--check',patch])
   run(['git','-C',work,'apply',patch]);item['result']='PASS'
 report['result']='PASS'
except RuntimeError as e:
 report['first_error']=str(e)
finally:
 target=device/'reports/xnu-patch-application.json'
 target.write_text(json.dumps(report,indent=2)+'\n')
print(f"Ordered patch application: {report['result']}, {sum(x['result']=='PASS' for x in report['patches'])}/{len(plan)}")
if report['result']!='PASS':raise SystemExit(report.get('first_error','patch check failed'))
