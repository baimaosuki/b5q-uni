#!/usr/bin/env python3
"""Verify unchanged firmware build inputs across two actual Git revisions."""
import argparse,hashlib,json,subprocess,tomllib
from pathlib import Path
R=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser();p.add_argument('--receipt',type=Path,required=True);p.add_argument('--fd',type=Path,required=True);p.add_argument('--current',required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
f=json.loads(a.receipt.read_text());assert f['passed']and f['github_digest_verified'];base=f['source_commit'];assert len(base)==len(a.current)==40
assert hashlib.sha256(a.fd.read_bytes()).hexdigest()==f['FD']['sha256']
def git(*args):return subprocess.check_output(['git','-C',str(R),*args])
def files(commit):
 names=git('ls-tree','-r','--name-only',commit,'--','patches/uefi-b5q').decode().splitlines()
 return {n:hashlib.sha256(git('show',commit+':'+n)).hexdigest()for n in names}
old,new=files(base),files(a.current);assert old==new and len(old)>=13,'Firmware patch inputs changed'
for n in ['UniXNU-b5q/unixnu.lock','UniXNU-b5q/scripts/check-b5q-uefi.py']:
 assert git('show',base+':'+n)==git('show',a.current+':'+n),('Changed firmware dependency',n)
for field in ['firmware','device']:
 before=tomllib.loads(git('show',base+':UniXNU-b5q/board.toml').decode()).get(field)
 after=tomllib.loads(git('show',a.current+':UniXNU-b5q/board.toml').decode()).get(field)
 assert before==after,('Changed board firmware input',field)
workflow='.github/workflows/b5q-p0-p5.yml'
before=git('show',base+':'+workflow).decode().split('\n  firmware:\n',1)[1]
after=git('show',a.current+':'+workflow).decode().split('\n  firmware:\n',1)[1]
assert before==after,'Firmware source/toolchain/workflow changed'
result=dict(passed=True,source_firmware_commit=base,current_commit=a.current,FD_sha256=f['FD']['sha256'],patches=old,lock_and_firmware_configuration_unchanged=True,firmware_job_unchanged=True)
a.out.write_text(json.dumps(result,indent=2)+'\n');print('PASS exact original firmware patches,pins,boardfirmware,buildjob andFD SHA unchanged; reuse verified originalFD/boot')
