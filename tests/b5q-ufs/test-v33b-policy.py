#!/usr/bin/env python3
"""Run production pre-launchd migration over a real temporary POSIX filesystem."""
from pathlib import Path
import importlib.util,subprocess,tempfile,re
R=Path(__file__).resolve().parents[2];W=R/'artifacts/b5q-v33b-fix-work';X=W/'xnu/bsd/kern/kern_exec.c'
spec=importlib.util.spec_from_file_location('policy',R/'UniXNU-b5q/scripts/update-b5q-launchd-seed.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
text=X.read_text();a=text.index('static int\nb5q_launchd_policy_prepare(');b=text.index('\nstatic int\nnative_owner_macos_data_prepare',a);body=re.sub(r'\bprintf\(', 'quiet(', text[a:b])
base=r'''
#include <cassert>
#include <cstdio>
#include <cstring>
#include <cstdlib>
#include <string>
#include <vector>
#include <map>
#include <filesystem>
#include <fstream>
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <cerrno>
using namespace std;
map<string,unsigned> owners;
string root;unsigned renames=0,writes=0;int fault=0;
string path(const char *p){return root+p;}
struct Node{string name;int fd;struct stat stat;};using vnode_t=Node*;
#define NULLVP nullptr
using user_addr_t=uintptr_t;using proc_t=int;using vfs_context_t=int;
constexpr int VNODE_LOOKUP_NOFOLLOW=1,VDIR=1,VREG=2,UIO_READ=0,UIO_WRITE=1,UIO_SYSSPACE=0,IO_NOAUTH=0,IO_SYNC=0,MNT_WAIT=0,Z_WAITOK=0,Z_NOFAIL=0;
struct vnode_attr {unsigned va_uid=0,va_gid=0,va_mode=0,va_nlink=0;size_t va_data_size=0;};
#define VATTR_INIT(p) (*(p)={})
#define VATTR_WANTED(p,f) ((void)0)
#define VATTR_SET(p,f,v) ((p)->f=(v))
template<class...A>void quiet(A...){}
int vfs_context_kernel(){return 0;}int vfs_context_ucred(int){return 0;}
int vnode_lookup(const char*p,int,vnode_t *out,int){struct stat s;if(lstat(path(p).c_str(),&s))return errno;*out=new Node{path(p),-1,s};return 0;}
int vnode_getattr(vnode_t p,vnode_attr *a,int){a->va_uid=owners.count(p->name)?owners[p->name]:(p->stat.st_uid==getuid()?0:p->stat.st_uid);a->va_gid=0;a->va_nlink=p->stat.st_nlink;a->va_mode=p->stat.st_mode;a->va_data_size=p->stat.st_size;return 0;}
int vnode_vtype(vnode_t p){return S_ISDIR(p->stat.st_mode)?VDIR:S_ISREG(p->stat.st_mode)?VREG:3;}
void vnode_put(vnode_t p){delete p;}
int vnode_open(const char*p,int flags,int mode,int,vnode_t *out,int){int native=(flags&FWRITE)?O_WRONLY:O_RDONLY;native|=flags&~(FWRITE|FREAD|O_TRUNC); // reproduce XNU non-compound open
int fd=open(path(p).c_str(),native,mode);if(fd<0)return errno;struct stat s;assert(!fstat(fd,&s));*out=new Node{path(p),fd,s};return 0;}
int vnode_close(vnode_t p,int,int){int error=close(p->fd);delete p;return error?errno:0;}
int vnode_setattr(vnode_t p,vnode_attr *a,int){if(fchmod(p->fd,a->va_mode)||ftruncate(p->fd,a->va_data_size))return errno;return 0;}
int VNOP_FSYNC(vnode_t p,int,int){return fsync(p->fd)?errno:0;}
int vn_rdwr(int direction,vnode_t p,caddr_t bytes,int n,int,int,int,int,int *resid,int){
 if(direction==UIO_WRITE&&fault==1)return EIO;
 auto done=direction==UIO_WRITE?write(p->fd,bytes,n):read(p->fd,bytes,n);if(done<0)return errno;
 *resid=n-done;if(direction==UIO_WRITE){writes++;assert(!fsync(p->fd));}return 0;
}
unsigned char *kalloc_data(size_t n,int){return static_cast<unsigned char*>(malloc(n));}void kfree_data(void *p,size_t){free(p);}
int copyout(const void *p,user_addr_t out,size_t n){memcpy((void*)out,p,n);return 0;}
struct unlink_args{user_addr_t path;};int unlink(int,unlink_args *a,int32_t*){return ::unlink(path((const char*)a->path).c_str())?errno:0;}
struct rename_args{user_addr_t from,to;};int rename(int,rename_args *a,int32_t*){if(fault==2)return EIO;renames++;owners.erase(path((const char*)a->to));return ::rename(path((const char*)a->from).c_str(),path((const char*)a->to).c_str())?errno:0;}
BLOB
MIGRATE
vector<unsigned char> readfile(const string &p){ifstream f(p,ios::binary);return {istreambuf_iterator<char>(f),istreambuf_iterator<char>()};}
int main(int argc,char **argv){assert(argc==2);root=argv[1];auto dir=root+"/private/var/db/com.apple.xpc.launchd";filesystem::create_directories(dir);filesystem::create_directories(root+"/private/var/run");chmod(dir.c_str(),0755);
 ofstream(root+"/private/var/run/b5q-wifi-ready")<<"stale";
 for(const char *n:{"disabled.plist","disabled.501.plist"}){ofstream(dir+"/"+n)<<"old-iconservices-disabled";chmod((dir+"/"+n).c_str(),0644);}
 ofstream(dir+"/.b5q-disabled.plist.new")<<string(20000,'X');
 unsigned char memory[4096]{};assert(!b5q_launchd_policy_prepare(1,(uintptr_t)memory));assert(renames==2&&writes==2&&!filesystem::exists(root+"/private/var/run/b5q-wifi-ready"));
 for(unsigned i=0;i<2;i++){const char *n;const unsigned char *data;size_t bytes;assert(b5q_launchd_policy_blob(i,&n,&data,&bytes));auto read=readfile(dir+"/"+n);assert(read==vector<unsigned char>(data,data+bytes));struct stat s;assert(!stat((dir+"/"+n).c_str(),&s)&&(s.st_mode&07777)==0644);}
 assert(!b5q_launchd_policy_prepare(1,(uintptr_t)memory)&&renames==2&&writes==2);
 auto file=dir+"/disabled.plist";filesystem::remove(file);assert(!symlink("outside",file.c_str()));assert(b5q_launchd_policy_prepare(1,(uintptr_t)memory)==EPERM);filesystem::remove(file);
 ofstream(file)<<"old";assert(!link(file.c_str(),(dir+"/hardlink").c_str()));assert(b5q_launchd_policy_prepare(1,(uintptr_t)memory)==EPERM);filesystem::remove(dir+"/hardlink");
 for(int injected:{1,2}){fault=injected;assert(b5q_launchd_policy_prepare(1,(uintptr_t)memory)==EIO);auto old=readfile(file);assert(string(old.begin(),old.end())=="old");}
 fault=0;assert(!b5q_launchd_policy_prepare(1,(uintptr_t)memory));
 auto gui=dir+"/disabled.501.plist";owners[gui]=501;unsigned oldRenames=renames;
 assert(!b5q_launchd_policy_prepare(1,(uintptr_t)memory)&&renames==oldRenames+1&&!owners.count(gui));
 owners[file]=501;assert(b5q_launchd_policy_prepare(1,(uintptr_t)memory)==EPERM);owners.erase(file);
 chmod(dir.c_str(),0777);assert(b5q_launchd_policy_prepare(1,(uintptr_t)memory)==EPERM);chmod(dir.c_str(),0755);
 puts("PASS actual prelaunchd existingData migration:58/25 exactbinaryplists,iconenable,stalesentinelremoved,atomicrename,repeatno-op,symlink/hardlink/refused,write/renamefaultpreservesold ASanUBSan");
}
'''
# Host flag aliases are disjoint from POSIX access-mode bits.
base=base.replace('using namespace std;', 'using namespace std;\n#undef FREAD\n#undef FWRITE\n#define FREAD 0x100000\n#define FWRITE 0x200000')
with tempfile.TemporaryDirectory(prefix='b5q-policy-test-')as td:
 td=Path(td);data='\n'.join('static const unsigned char b5q_policy_'+str(i)+'[]={'+','.join(str(x)for x in m.merge(b'',v))+'};'for i,v in enumerate(m.policies().values()))
 blob=(R/'UniXNU-b5q/package/B5qLaunchdPolicy.c').read_text().replace('#include "B5qLaunchdPolicyData.h"',data)
 src=td/'test.cpp';src.write_text(base.replace('BLOB',blob).replace('MIGRATE',body))
 subprocess.run(['c++','-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-fsanitize=address,undefined',str(src),'-o',str(td/'test')],check=True)
 subprocess.run([str(td/'test'),str(td/'root')],check=True)

# Run the actual call-site fragment: migration errors cannot poison mount/GPU.
start=text.index('\tif (!error) {\n\t\tconst int policy_error = b5q_launchd_policy_prepare')
end=text.index('\n\tif (!error) native_gpu_addon_release()',start)
callsite=text[start:end]
source=r'''
#include <cassert>
#include <cstdio>
using proc_t=int;using user_addr_t=unsigned long;int failure,calls;
int b5q_launchd_policy_prepare(int,unsigned long){return failure;}
void native_owner_macos_gpu_addon(int,unsigned long){calls|=1;}
void native_owner_macos_addon_sbin(int,unsigned long){calls|=2;}
void b5q_wireless_runtime_prepare(int,unsigned long){calls|=4;}
void b5q_media_runtime_prepare(int,unsigned long){calls|=8;}
void native_owner_macos_boot_shims(int,unsigned long){calls|=16;}
int main(){for(int e:{1,5,13}){int error=0,p=1;user_addr_t scratch=0;failure=e;calls=0;CALLSITE;assert(!error&&calls==31);}}
'''.replace('CALLSITE',callsite).replace('#include <cstdio>','#include <cstdio>\n#include <initializer_list>')
with tempfile.TemporaryDirectory(prefix='b5q-policy-boot-')as td:
 td=Path(td);(td/'test.cpp').write_text(source)
 subprocess.run(['c++','-std=c++17','-fsanitize=address,undefined',str(td/'test.cpp'),'-o',str(td/'test')],check=True);subprocess.run([str(td/'test')],check=True)
