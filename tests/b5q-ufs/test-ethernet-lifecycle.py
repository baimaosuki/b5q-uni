#!/usr/bin/env python3
"""Exercise the production Ethernet registration worker and startup gate."""
import re
import subprocess
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[2]
source = (root / 'UniXNU-b5q/package/B5qEthernet.cpp').read_text()
worker = re.search(r'static void ethernetWorker\(.*?\n\}', source, re.S)[0]
gate = re.search(r'extern "C" void b5q_ethernet_start\(.*?\n\}', source, re.S)[0]
harness = r'''
#include <cassert>
#include <cstdint>
using OSReturn=int;using wait_result_t=int;using thread_t=void*;
constexpr int kOSReturnSuccess=0,kOSKextReturnStartStopError=1,KERN_SUCCESS=0;
static int loaded,post,status,logs,terminated,static_init,registered,retains,releases,detaches;
static int thread_calls,argument,thread_error,thread_releases;
static bool handle_ok,allocation_ok,parent_ok,init_ok,attach_ok,start_ok;
static int &b5q_ethernet_state=status;
struct IOService{static IOService*getResourceService(){static IOService p;return parent_ok?&p:nullptr;}};
struct B5qEthernet:IOService{bool init(void*){return init_ok;}bool attach(IOService*){return attach_ok;}
 bool start(IOService*){return start_ok;}void registerService(){++registered;}void retain(){++retains;}
 void release(){++releases;}void detach(IOService*){++detaches;}};
static B5qEthernet object;
static B5qEthernet*allocate(){return allocation_ok?&object:nullptr;}
#define OSTypeAlloc(T) allocate()
#define OSSafeReleaseNULL(p) do{if(p)(p)->release();p=nullptr;}while(0)
static int OSKextLoadKextWithIdentifier(const char*){return loaded;}
struct OSMetaClass{static void*preModLoad(const char*){return handle_ok?(void*)1:nullptr;}
 static int postModLoad(void*){return post;}};
static void b5q_ethernet_static_init(){++static_init;}
static struct{const char*name;}g_kernel_kmod_info={"test"};
static void IOLog(const char*,...){++logs;}
static void thread_terminate(void*){++terminated;}
static void*current_thread(){return nullptr;}
static bool PE_parse_boot_argn(const char*,unsigned*out,unsigned){if(argument<0)return false;*out=argument;return true;}
static int kernel_thread_start(void(*)(void*,int),void*,thread_t*out){++thread_calls;*out=(void*)1;return thread_error;}
static void thread_deallocate(thread_t){++thread_releases;}
WORKER
GATE
int main(){
 for(int test=0;test<9;++test){loaded=post=0;handle_ok=allocation_ok=parent_ok=init_ok=attach_ok=start_ok=true;
  logs=terminated=static_init=registered=retains=releases=detaches=0;
  if(test==1)loaded=-5;if(test==2)handle_ok=false;if(test==3)post=-1;
  if(test==4)allocation_ok=false;if(test==5)init_ok=false;if(test==6)parent_ok=false;
  if(test==7)attach_ok=false;if(test==8)start_ok=false;
  ethernetWorker(nullptr,0);int expected[]={1,-1,-2,-3,-4,-4,-4,-5,-6};
  assert(status==expected[test]&&logs==1&&terminated==1);
  assert(registered==(test==0)&&retains==(test==0));
  assert(detaches==(test==8));
 }
 loaded=kOSKextReturnStartStopError;handle_ok=allocation_ok=parent_ok=init_ok=attach_ok=start_ok=true;
 ethernetWorker(nullptr,0);assert(status==1);
 for(argument=-1;argument<=0;++argument)b5q_ethernet_start();assert(thread_calls==0);
 argument=1;b5q_ethernet_start();b5q_ethernet_start();assert(thread_calls==1&&thread_releases==1);
}
'''.replace('WORKER', worker).replace('GATE', gate)
with tempfile.TemporaryDirectory(prefix='b5q-ethernet-test-') as temp:
    temp = Path(temp)
    (temp / 'test.cpp').write_text(harness)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    '-Wno-misleading-indentation', '-fsanitize=address,undefined',
                    str(temp / 'test.cpp'), '-o', str(temp / 'test')], check=True)
    subprocess.run([str(temp / 'test')], check=True)
print('PASS production Ethernet worker: success, load/pre/post/init/attach/start failures, cleanup and opt-in-once startup')
