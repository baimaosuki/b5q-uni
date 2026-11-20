#!/usr/bin/env python3
"""Read actual packed APFS seed files and original inode owners/modes locally."""
import argparse,hashlib,json,plistlib,subprocess,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
TOOLS=Path('/home/baimao/nabu_macos/out/nabu-27.3-fresh/p016-zeta-pac/tools/apfs-fuse')
PATHS={'private/var/db/.AppleSetupDone':(0,0,0o644),
 'private/var/db/dslocal/nodes/Default/users/baimao.plist':(0,0,0o600),
 'private/var/db/dslocal/nodes/Default/groups/admin.plist':(0,0,0o600),
 'private/var/db/dslocal/nodes/Default/groups/staff.plist':(0,0,0o600),
 'Users/baimao':(501,20,0o750),'Users/baimao/.skipbuddy':(501,20,0o644),
 'Library/Preferences/com.apple.loginwindow.plist':(0,0,0o644),
 'private/etc/kcpassword':(0,0,0o600)}

def verify_files(base,stats):
 for path,expected in PATHS.items():
  actual=stats[path];assert (actual['uid'],actual['gid'],actual['mode']&0o7777)==expected,(path,actual,expected)
 user=plistlib.loads((base/'private/var/db/dslocal/nodes/Default/users/baimao.plist').read_bytes())
 assert user['name']==['baimao'] and user['uid']==['501'] and user['gid']==['20'] and user['home']==['/Users/baimao']
 shadow=plistlib.loads(user['ShadowHashData'][0])['SALTED-SHA512-PBKDF2'];assert shadow['iterations']>=50000
 assert hashlib.pbkdf2_hmac('sha512',b'1234',shadow['salt'],shadow['iterations'],len(shadow['entropy']))==shadow['entropy']
 for group in ['admin','staff']:
  entry=plistlib.loads((base/f'private/var/db/dslocal/nodes/Default/groups/{group}.plist').read_bytes())
  assert 'baimao' in entry['users'] and user['generateduid'][0] in entry['groupmembers']
 login=plistlib.loads((base/'Library/Preferences/com.apple.loginwindow.plist').read_bytes());assert login['autoLoginUser']=='baimao'
 key=bytes.fromhex('7d895223d2bcddeaa3b91f');expected=bytes(c^key[i%len(key)] for i,c in enumerate(b'1234'+bytes(8)))
 assert (base/'private/etc/kcpassword').read_bytes()==expected and len(expected)==12
 return {'administrator':'baimao','uid':501,'gid':20,'groups':['admin','staff'],'PBKDF2_password_verified':True,
         'skip_setup':True,'skipbuddy':True,'autoLoginUser':'baimao','kcpassword_12_bytes_verified':True,
         'actual_APFS_inodes':stats,'hardware_tested':False}

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--seed',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--apfs-tools',type=Path,default=TOOLS);a=p.parse_args()
 sys.path.insert(0,str(ROOT/'sources/UniXNU/drivers/DarwinBoot/Test'));import packed_ramdisk
 logical,regions=packed_ramdisk.regions(a.seed.read_bytes());assert logical==2*2**30
 with tempfile.TemporaryDirectory(prefix='b5q-data-account-') as td:
  tmp=Path(td);raw=tmp/'data.raw'
  with raw.open('wb') as f:
   f.truncate(logical)
   for offset,body in regions:f.seek(offset);f.write(body)
  exe=tmp/'read-apfs';build=a.apfs_tools/'build'
  subprocess.run(['c++','-std=c++17','-O2','-I',str(a.apfs_tools),str(Path(__file__).with_name('read-seed-apfs.cpp')),str(build/'libapfs.a'),'-lz','-lbz2',str(build/'liblzfse.a'),str(build/'libcrypto.a'),'-o',str(exe)],check=True)
  text=subprocess.check_output([str(exe),str(raw),str(tmp/'files'),*PATHS],text=True);stats={}
  for line in text.splitlines():
   path,uid,gid,mode,size=line.split('\t');stats[path]={'uid':int(uid),'gid':int(gid),'mode':int(mode,8),'bytes':int(size)}
  report=verify_files(tmp/'files',stats);report.update(seed_sha256=hashlib.sha256(a.seed.read_bytes()).hexdigest(),logical_bytes=logical,read_only_APFS_parser=True)
  a.out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
