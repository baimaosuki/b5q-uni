#!/usr/bin/env python3
"""Verify accounts, exact launchd policy, inode modes and absentd on readback."""
import argparse,hashlib,importlib.util,json,plistlib,subprocess,tempfile,uuid
from pathlib import Path
R=Path(__file__).resolve().parents[2]
def load(path):
 s=importlib.util.spec_from_file_location(path.stem,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--image',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
 account=load(R/'scripts/b5q-install/verify-data-account.py');policy=load(R/'UniXNU-b5q/scripts/update-b5q-launchd-seed.py')
 paths=list(account.PATHS)+[policy.DIRECTORY+'/disabled.501.plist',policy.DIRECTORY+'/disabled.migrated','private/var/ngpu/bin/b5q-absentd']
 with tempfile.TemporaryDirectory(prefix='b5q-init-apfs-')as td:
  t=Path(td);exe=t/'read-apfs';src=t/'read-apfs.cpp';build=account.TOOLS/'build'
  code=(R/'scripts/b5q-install/read-seed-apfs.cpp').read_text().replace('if(!container.Init())return 4;',
   'if(!container.Init())return 4; apfs_superblock_t sb; if(!container.GetVolumeInfo(0,sb))return 12; const uint8_t expected[16]={'+','.join(str(x)for x in uuid.UUID('1552CFEE-78FF-48D8-8A6C-694B867D61AC').bytes)+'}; if(memcmp(sb.apfs_vol_uuid,expected,16))return 13;')
  src.write_text('#include <cstring>\n'+code)
  subprocess.run(['c++','-std=c++17','-O2','-I',str(account.TOOLS),str(src),str(build/'libapfs.a'),'-lz','-lbz2',str(build/'liblzfse.a'),str(build/'libcrypto.a'),'-o',str(exe)],check=True)
  dest=t/'files';stats={}
  for line in subprocess.check_output([str(exe),str(a.image),str(dest),*paths],text=True).splitlines():
   name,uid,gid,mode,size=line.split('\t');stats[name]=dict(uid=int(uid),gid=int(gid),mode=int(mode,8),bytes=int(size))
  account.verify_files(dest,stats);counts={}
  for filename,labels in policy.policies().items():
   name=policy.DIRECTORY+'/'+filename;raw=(dest/name).read_bytes();values=plistlib.loads(raw)
   assert raw.startswith(b'bplist00')and values==dict.fromkeys(labels,True)
   assert stats[name]['uid']==stats[name]['gid']==0 and stats[name]['mode']==0o100644
   counts[filename]=len(values)
  assert stats[policy.DIRECTORY+'/disabled.migrated']==dict(uid=0,gid=0,mode=0o100644,bytes=0)
  name='private/var/ngpu/bin/b5q-absentd';assert stats[name]['mode']==0o100755
  assert hashlib.sha256((dest/name).read_bytes()).hexdigest()=='29c52a1b79e53b71022c973a071e1e5dc96830445f742263d68276cee3cb9b72'
 result=dict(passed=True,readback_image=str(a.image),APFS_volume_UUID='1552CFEE-78FF-48D8-8A6C-694B867D61AC',account_autologin_password_verified=True,policy_counts=counts,inodes=stats,absentd_SHA256_verified=True)
 a.out.write_text(json.dumps(result,indent=2)+'\n');print('PASS APFS readback: account/autologin, UUID, root-owned binary59/26 policies, watchdogd, absentd',flush=True)
if __name__=='__main__':main()
