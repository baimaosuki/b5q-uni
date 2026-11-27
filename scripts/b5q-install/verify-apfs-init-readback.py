#!/usr/bin/env python3
"""Verify accounts, exact launchd policy, inode modes and absentd on readback."""
import argparse,ast,hashlib,importlib.util,json,plistlib,struct,subprocess,tempfile,uuid
from pathlib import Path
R=Path(__file__).resolve().parents[2]
def load(path):
 s=importlib.util.spec_from_file_location(path.stem,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def expected_seed_policy(policy,packed,metadata):
 if (packed is None)!=(metadata is None):raise ValueError('Qualified seed and metadata must be supplied together')
 if packed is None:return policy.policies(),None
 meta=json.loads(metadata.read_text());digest,reusable=policy.checked_seed(packed.read_bytes(),meta,'current')
 if not reusable:raise ValueError('Only the exact hash-qualified existing seed may retain its old on-disk policy')
 return meta['launchd_policy'],dict(packed_sha256=digest,metadata_sha256=hashlib.sha256(metadata.read_bytes()).hexdigest(),runtime_policy_counts={n:len(v)for n,v in policy.policies().items()},runtime_migration_required=meta['launchd_policy']!=policy.policies())
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--image',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
 p.add_argument('--trust-cache',type=Path,help='Also verify actual recovered absentd CodeDirectories against this owner trust bundle')
 p.add_argument('--qualified-seed',type=Path,help='Exact immutable packed seed, qualified with --seed-metadata; its policy is migrated before launchd')
 p.add_argument('--seed-metadata',type=Path)
 a=p.parse_args()
 account=load(R/'scripts/b5q-install/verify-data-account.py');policy=load(R/'UniXNU-b5q/scripts/update-b5q-launchd-seed.py')
 expected,qualified=expected_seed_policy(policy,a.qualified_seed,a.seed_metadata)
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
  account.verify_files(dest,stats);counts={};contents={};trusted_hashes=[]
  for filename,labels in expected.items():
   name=policy.DIRECTORY+'/'+filename;raw=(dest/name).read_bytes();values=plistlib.loads(raw)
   assert raw.startswith(b'bplist00')and values==(dict(labels) if isinstance(labels,dict) else dict.fromkeys(labels,True))
   assert stats[name]['uid']==stats[name]['gid']==0 and stats[name]['mode']==0o100644
   counts[filename]=len(values)
   contents[filename]=values
  assert stats[policy.DIRECTORY+'/disabled.migrated']==dict(uid=0,gid=0,mode=0o100644,bytes=0)
  name='private/var/ngpu/bin/b5q-absentd';assert stats[name]['mode']==0o100755
  assert hashlib.sha256((dest/name).read_bytes()).hexdigest()=='29c52a1b79e53b71022c973a071e1e5dc96830445f742263d68276cee3cb9b72'
  if a.trust_cache:
   helper=R/'scripts/b5q-install/verify-mount-runtime.py'
   functions=[n for n in ast.parse(helper.read_text()).body if isinstance(n,ast.FunctionDef)and n.name in ('modules','codesign')]
   ns=dict(struct=struct,hashlib=hashlib);exec(compile(ast.Module(body=functions,type_ignores=[]),str(helper),'exec'),ns)
   mods=ns['modules'](a.trust_cache.read_bytes());trusted={m[i:i+20]for m in mods for i in range(24,len(m),24)}
   hashes=ns['codesign']((dest/name).read_bytes());assert hashes and all(h in trusted for h in hashes)
   trusted_hashes=[h.hex()for h in hashes]
 result=dict(passed=True,readback_image=str(a.image),APFS_volume_UUID='1552CFEE-78FF-48D8-8A6C-694B867D61AC',account_autologin_password_verified=True,policy_counts=counts,policy_contents=contents,inodes=stats,absentd_SHA256_verified=True,absentd_trusted_CodeDirectories=trusted_hashes,qualified_immutable_seed=qualified)
 a.out.write_text(json.dumps(result,indent=2)+'\n');print('PASS APFS readback: account/autologin, UUID, root-owned binary policies, watchdogd, absentd',flush=True)
if __name__=='__main__':main()
