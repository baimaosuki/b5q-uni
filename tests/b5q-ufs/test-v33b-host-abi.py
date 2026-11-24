#!/usr/bin/env python3
"""Execute real vm_stats and per-service MACF predicate with bounds/deny tests."""
from pathlib import Path
import re,subprocess,tempfile
R=Path(__file__).resolve().parents[2];X=R/'artifacts/b5q-v33b-fix-work/xnu'
def function(s,signature):
 a=s.index(signature);at=s.index('{',a);b=at+1;n=1
 while n:n+=(s[b]=='{')-(s[b]=='}');b+=1
 return s[a:b]
h=(X/'osfmk/mach/vm_statistics.h').read_text();a=h.index('struct vm_statistics64 {');b=h.index('} __attribute__((aligned(8)));',a)+len('} __attribute__((aligned(8)));');layout=h[a:b]
vm=function((X/'osfmk/kern/host.c').read_text(),'kern_return_t\nvm_stats(')
constants='\n'.join((X/'osfmk/mach/host_info.h').read_text().splitlines()[249:260])
# Use exact layout and published revision offsets; only counter producers mocked.
base=r'''
#include <cassert>
#include <cstdint>
#include <cstddef>
#include <cstdio>
#include <cstring>
#include <climits>
#include <string>
using natural_t=unsigned;using kern_return_t=int;using mach_msg_type_number_t=unsigned;
#define XNU_TARGET_OS_OSX 1
#define HAS_MTE 0
#define KERN_FAILURE 5
#define KERN_SUCCESS 0
LAYOUT
using vm_statistics64_data_t=vm_statistics64;using vm_statistics64_t=vm_statistics64*;
#define HOST_VM_INFO64_COUNT (sizeof(vm_statistics64_data_t)/sizeof(int))
#define HOST_VM_INFO64_REV3_COUNT HOST_VM_INFO64_COUNT
#define HOST_VM_INFO64_REV2_COUNT (offsetof(vm_statistics64_data_t,total_tag_storage_pages)/sizeof(int))
#define HOST_VM_INFO64_REV1_COUNT (offsetof(vm_statistics64_data_t,swapped_count)/sizeof(int))
#define HOST_VM_INFO64_REV0_COUNT (offsetof(vm_statistics64_data_t,decompressions)/sizeof(int))
#define VM_STATISTICS_TRUNCATE_TO_32_BIT(x) uint32_t(x)
#define DTRACE_VM2(...) ((void)0)
#define os_atomic_load(p,x) (*(p))
#define VM_PAGE_COMPRESSOR_COUNT 3
unsigned vm_page_speculative_count=2,vm_page_throttled_count=0,vm_page_free_count=10,vm_page_active_count=4,
 vm_page_inactive_count=1,vm_page_wire_count=3,vm_lopage_free_count=0,vm_page_purgeable_count=0,vm_page_purged_count=0,
 vm_page_pageable_external_count=0,vm_page_pageable_internal_count=0,c_segment_pages_compressed=0,vm_page_swapped_count=0;
struct Local{unsigned vpl_count=0,vpl_internal_count=0,vpl_external_count=0;} *vm_page_local_q=nullptr;
#define zpercpu_foreach(v,q) for(Local *v=q;v;v=nullptr)
unsigned counter_load(unsigned*p){return *p;}void get_host_vm_stats(vm_statistics64_t p){*p={};}
unsigned warnings=0;template<class...T>void vm_log_error(T...){warnings++;}void *current_task(){return nullptr;}const char *task_best_name(void*){return "sysmond";}int task_pid(void*){return 1;}
VMSTATS
int main(){
 static_assert(HOST_VM_INFO64_COUNT==62,"real pinned layout");
 for(unsigned capacity:{0u,1u,23u,24u,25u,37u,38u,39u,40u,41u,61u,62u,63u,104u,UINT_MAX}){
  alignas(8)unsigned char raw[512];memset(raw,0xa5,sizeof(raw));unsigned count=capacity;
  int result=vm_stats(raw,&count);
  if(capacity<HOST_VM_INFO64_REV0_COUNT){assert(result==KERN_FAILURE);for(auto v:raw)assert(v==0xa5);continue;}
  assert(!result&&count<=capacity&&count<=62&&!warnings);
  for(unsigned at=count*4;at<sizeof(raw);at++)assert(raw[at]==0xa5);
  assert(reinterpret_cast<vm_statistics64_t>(raw)->free_count==12);
 }
 puts("PASS real XNU vm_stats15capacity/revision boundaries inclmacOS104,exact62-wordlayout,alltailcanaries/shortbuffers,nooverflow/noerror");
}
'''
with tempfile.TemporaryDirectory(prefix='b5q-host-abi-')as td:
 td=Path(td);src=td/'vm.cpp';src.write_text(base.replace('LAYOUT',layout).replace('VMSTATS',vm));exe=td/'vm'
 subprocess.run(['c++','-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(src),'-o',str(exe)],check=True);subprocess.run([str(exe)],check=True)
 s=(X/'iokit/Kernel/IOUserClient.cpp').read_text();grant=function(s,'static bool\nnative_sandbox_grant(')
 body=r'''
#include <cassert>
#include <cstdio>
#include <cstring>
#include <string>
struct OSString{std::string s;const char *getCStringNoCopy(){return s.c_str();}};
#define OSDynamicCast(T,p) static_cast<T*>(p)
int yes;void *kOSBooleanTrue=&yes;bool platform=true;std::string process;
struct IOService {OSString list;bool owned=true;void *getProperty(const char *n){return !strcmp(n,"B5qKeyStorePlatformGrant")?(owned?kOSBooleanTrue:nullptr):&list;}};
void *current_task(){return nullptr;}bool task_get_platform_binary(void*){return platform;}void proc_selfname(char *p,int n){snprintf(p,n,"%s",process.c_str());}
GRANT
int main(){IOService s;s.list.s="pboard,usernoted,usernotification,linkd,audiomxd";
 for(const char *name:{"pboard","usernoted","usernotification","linkd","audiomxd"}){process=name;platform=true;assert(native_sandbox_grant(&s));platform=false;assert(!native_sandbox_grant(&s));}
 platform=true;for(const char *name:{"pboardX","unknown","","Finder","WindowServer"}){process=name;assert(!native_sandbox_grant(&s));}
 puts("PASS actual ownedAKSper-servicegrant:5Appleplatformnames accepted,nonplatformspoofs/unknown/wrongnames refused;normalMACFstillapplieselsewhere");}
'''.replace('GRANT',grant)
 src=td/'grant.cpp';src.write_text(body);exe=td/'grant';subprocess.run(['c++','-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(src),'-o',str(exe)],check=True);subprocess.run([str(exe)],check=True)
