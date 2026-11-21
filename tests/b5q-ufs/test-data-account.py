"""Exercise the pinned official account/autologin writers before macOS CI."""
import importlib.util,json,os,plistlib,sys,tempfile
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root/'sources/UniXNU/drivers/DarwinBoot/Test'))
sys.path.insert(0,str(root/'sources/UniXNU/scripts'))
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
seed=load('official_seed',root/'sources/UniXNU/scripts/make-macos-data-seed.py')
check=load('account_check',root/'scripts/b5q-install/verify-data-account.py')
with tempfile.TemporaryDirectory(prefix='b5q-account-writers-') as td:
 base=Path(td);dslocal=base/'private/var/db/dslocal/nodes/Default'
 (dslocal/'groups').mkdir(parents=True)
 for name in ['admin','staff']:(dslocal/f'groups/{name}.plist').write_bytes(plistlib.dumps({'users':[],'groupmembers':[]}))
 with patch.object(os,'chown'):
  seed.add_user(dslocal,'baimao','1234',real_name='baimao');seed.add_auto_login(base,'baimao','1234')
  seed.write_root(base/'private/var/db/com.apple.xpc.launchd/disabled.plist',plistlib.dumps({'com.apple.watchdogd':True}),0o644)
 (base/'Users/baimao').mkdir(parents=True);(base/'Users/baimao/.skipbuddy').touch();(base/'private/var/db/.AppleSetupDone').touch()
 stats={path:dict(uid=uid,gid=gid,mode=mode,bytes=(base/path).stat().st_size) for path,(uid,gid,mode) in check.PATHS.items()}
 check.verify_files(base,stats)
 assert (base/'private/etc/kcpassword').stat().st_mode&0o777==0o600
 print('PASS pinned official PBKDF2/group/autologin/kcpassword writers; real APFS owners checked separately after CI')
