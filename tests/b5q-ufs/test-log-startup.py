#!/usr/bin/env python3
"""Run actual XNU startup/policy/slab functions against the log registration."""
import hashlib,json,re,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
XNU=ROOT/'sources/UniXNU/out/feeds/xnu-3199e8bc'

def function(text,name):
 match=re.search(r'\n'+re.escape(name)+r'\([^;]*?\)\n\{',text,re.S);assert match,name
 brace=text.index('{',match.start());depth=1;end=brace+1
 while depth:
  depth+=(text[end]=='{')-(text[end]=='}');end+=1
 return text[match.start()+1:end]

startup=(XNU/'osfmk/kern/startup.c').read_text();header=(XNU/'osfmk/kern/startup.h').read_text();memory=(XNU/'osfmk/vm/vm_kern.c').read_text()
enums=re.search(r'__enum_decl\(startup_subsystem_id_t, uint32_t, \{(.*?)\n\}\);',header,re.S)[1]
patch=(ROOT/'UniXNU-b5q/patches/xnu/b5q-console-journal.patch').read_text();added='\n'.join(s[1:]for s in patch.splitlines()if s.startswith('+')and not s.startswith('+++'))
reg=re.search(r'STARTUP\((\w+),\s*(\w+),\s*b5q_console_capture_init\);',added);assert reg and reg.groups()==('OSLOG','STARTUP_RANK_FIRST')
allocator=function(added,'b5q_console_capture_init');harness=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#define __startup_func
#define release_assert(x) do { if(!(x)) throw 1; } while(0)
using startup_subsystem_id_t=uint32_t;
enum : uint32_t { ENUMS };
static startup_subsystem_id_t startup_phase;
static unsigned startup_debug;
constexpr unsigned STARTUP_DEBUG_VERBOSE=1;
static void kprintf(const char*,...){}
static void kernel_startup_log(unsigned){}
struct startup_entry {unsigned subsystem,rank;void(*func)(void*);void*arg;};
static startup_entry *startup_entry_cur,*startup_entries_end;
using vm_map_t=void*;static vm_map_t kernel_map=(void*)1;
using kma_flags_t=unsigned;using kmem_direction_t=unsigned;
using vm_offset_t=uintptr_t;
struct kmem_guard_t {uint16_t kmg_type_hash;};
struct vm_map_kernel_flags_t {unsigned vmkf_range_id;bool vmkf_last_free;};
struct slab {unsigned marker;};using vm_guard_object_slab_t=slab*;
static slab kmem_slabs[8][2];
enum {KMEM_RANGE_ID_NONE=0,KMEM_RANGE_ID_DATA_SHARED=1,KMEM_RANGE_ID_DATA_PRIVATE=2,KMEM_RANGE_ID_IO=3,KMEM_RANGE_ID_MAX=8,KMEM_RANGE_MASK=7,KMEM_DIRECTION_MASK=1,KMEM_DIRECTION_BACKWARDS=1,KMEM_DIRECTION_FORWARDS=0};
enum {KMA_DATA_SHARED=1,KMA_DATA=2,KMA_IO=4,KMA_PERMANENT=8,KMA_KOBJECT=16,KMR_IO=32,VM_KERN_MEMORY_DIAG=18,KERN_SUCCESS=0};
static unsigned kmem_hash_backtrace(void*){return 1;}
static unsigned kmem_adjust_range_id(unsigned){return 1;}
static void POLICY
vm_guard_object_slab_t SLAB
static unsigned allocations,promotions,observed_phase,observed_range;static uint8_t buffer;
static int kmem_alloc(vm_map_t map,vm_offset_t*address,unsigned bytes,unsigned flags,unsigned tag){
 assert(map==kernel_map&&bytes==0x1000000&&tag==VM_KERN_MEMORY_DIAG);
 assert(flags==(KMA_PERMANENT|KMA_KOBJECT|KMA_DATA));++allocations;
 observed_phase=startup_phase;vm_map_kernel_flags_t vmk={};kmem_apply_security_policy(map,flags,{},&vmk);observed_range=vmk.vmkf_range_id;
 (void)kmem_slab(vmk);*address=(uintptr_t)&buffer;return KERN_SUCCESS;
}
static int nabu_capture_expand(uint8_t*p){assert(p==&buffer);++promotions;return 1;}
#define NB_LOG_CAPACITY 0x1000000
static void ALLOCATOR
void SCHEDULER
static void invoke(void*){b5q_console_capture_init();}
static void run(unsigned subsystem){startup_entry entry={subsystem,0,invoke,nullptr};startup_entry_cur=&entry;startup_entries_end=&entry+1;startup_phase=0;kernel_startup_initialize_upto(subsystem);}
int main(){bool reproduced=false;try{run(STARTUP_SUB_KMEM);}catch(int){reproduced=true;}
 assert(reproduced&&allocations==1&&promotions==0&&observed_phase==STARTUP_SUB_KMEM-1&&observed_range==KMEM_RANGE_ID_NONE);
 run(REGISTERED_PHASE);assert(allocations==2&&promotions==1&&observed_phase>=STARTUP_SUB_KMEM&&observed_range==KMEM_RANGE_ID_DATA_PRIVATE);
 printf("old_phase=%u old_range=0 assertion=reproduced new_phase=%u new_range=%u capture_promoted=1\n",STARTUP_SUB_KMEM-1,observed_phase,observed_range);
}
'''
for key,value in {'ENUMS':enums,'POLICY':function(memory,'kmem_apply_security_policy'),'SLAB':function(memory,'kmem_slab'),'ALLOCATOR':allocator,'SCHEDULER':function(startup,'kernel_startup_initialize_upto'),'REGISTERED_PHASE':'STARTUP_SUB_'+reg[1]}.items():harness=harness.replace(key,value)
with tempfile.TemporaryDirectory(prefix='b5q-log-startup-')as temp:
 temp=Path(temp);(temp/'test.cpp').write_text(harness);exe=temp/'test'
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-fsanitize=address,undefined',str(temp/'test.cpp'),'-o',str(exe)],check=True)
 result=subprocess.run([str(exe)],check=True,capture_output=True,text=True);print(result.stdout.strip())
report={'result':'PASS','scope':'Production startup dispatcher, security policy, slab assertion and board allocator; allocation/locks/platform types are host stubs, no kernel boot or hardware claim','old_KMEM_registration_reproduces_assertion':True,'new_OSLOG_registration_selects_DATA_PRIVATE':True,'promotion_after_allocation':True,'inputs_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()for p in [XNU/'osfmk/kern/startup.c',XNU/'osfmk/kern/startup.h',XNU/'osfmk/vm/vm_kern.c',ROOT/'UniXNU-b5q/patches/xnu/b5q-console-journal.patch']}}
out=ROOT/'artifacts/b5q-log-v13-work';out.mkdir(parents=True,exist_ok=True);(out/'startup-regression.json').write_text(json.dumps(report,indent=2)+'\n')
