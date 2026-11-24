#!/usr/bin/env python3
"""Execute production 16KiB fixup branch and actual UPL commit/abort choice."""
from pathlib import Path
import re,subprocess,tempfile
R=Path(__file__).resolve().parents[2];s=(R/'artifacts/b5q-v33b-fix-work/xnu/osfmk/vm/vm_dyld_pager.c').read_text()
a=s.index('\t\tbcopy((const char *)src_vaddr, (char *)dst_vaddr, PAGE_SIZE);');b=s.index('\ndone:',a)
# The last brace closes the UPL loop; keep its body plus production guard.
processing=s[a:b].rsplit('\n\t}',1)[0]
guard=re.search(r'for \(cur_offset = 0;\s*(retval == KERN_SUCCESS && cur_offset < length);\s*cur_offset \+= PAGE_SIZE\)',s)[1]
a=s.index('\t\t/* abort or commit the UPL */');b=s.index('\n\t\t/* and deallocate',a);decision=s[a:b]
base=r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <cstdlib>
#include <vector>
#include <initializer_list>
using kern_return_t=int;using vm_offset_t=uintptr_t;using vm_object_offset_t=uint64_t;using ppnum_t=unsigned;using boolean_t=bool;
constexpr unsigned PAGE_SIZE=4096,KERN_SUCCESS=0,KERN_FAILURE=5;
#define VM_PAGE_NULL nullptr
constexpr int UPL_COMMIT_CS_VALIDATED=1,UPL_COMMIT_WRITTEN_BY_KERNEL=2;
#define KDBG_TRIAGE_EVENTID(...) 0
#define VM_PAGE_OBJECT(x) src_page_object
#define VM_PAGE_FREE(x) ((void)0)
#define assertf(x,...) assert(x)
unsigned aborts,commits,peeks,fixups,visited,failPage,failPart,failFix;bool panic_on_dyld_issue=false;
unsigned current_page;uint8_t source[12*PAGE_SIZE],destination[8*PAGE_SIZE];
void ktriage_record(...){}unsigned thread_tid(int){return 0;}int current_thread(){return 0;}void panic(...){abort();}
struct Page{bool vmp_busy=true;};
struct Object{unsigned paging_in_progress=1;};void vm_object_lock(Object*){}void vm_object_unlock(Object*){}void vm_page_wakeup_done(Object*,Page*){}void vm_object_paging_end(Object*){}
struct Pager{unsigned dyld_num_range=1;uint64_t dyld_file_offset[1]={0},dyld_size[1]={sizeof(source)},dyld_address[1]={0x100000};};
struct Upl{uint64_t u_offset=0;unsigned u_size=8*PAGE_SIZE;};bool page_aligned(uint64_t x){return !(x&(PAGE_SIZE-1));}
void upl_abort(Upl*,int){aborts++;}void upl_commit_range(Upl*,int,unsigned,int,void*,unsigned,boolean_t*){commits++;}
kern_return_t dyld_pager_peek(Object*,uint64_t off,void *to,void*){peeks++;if(current_page==failPage&&off/PAGE_SIZE%4==failPart)return 17;memcpy(to,source+off,PAGE_SIZE);return 0;}
kern_return_t fixup_page(vm_offset_t data,uint64_t,Pager*){fixups++;if(current_page==failPage&&failFix)return 23;memset((void*)data,0x7c,16384);return 0;}
int request(){int retval=0,kr=0;uint64_t cur_offset=0,offset=0,userVA;unsigned length=8*PAGE_SIZE,r,i,mwli_page_size=16384;int fault_info=0;
 Pager pager_value,*pager=&pager_value;Object object,*src_top_object=&object,*src_page_object=&object;Page page;Page *src_page,*top_page;
 alignas(16384)uint8_t scratch[16384];void *fixup_buffer=scratch;
 Upl u,*upl=&u;void *upl_pl=nullptr;unsigned pl_count=8;
 for(cur_offset=0;GUARD;cur_offset+=PAGE_SIZE){
  current_page=cur_offset/PAGE_SIZE;visited++;src_page=&page;top_page=nullptr;
  uintptr_t src_vaddr=(uintptr_t)(source+cur_offset),dst_vaddr=(uintptr_t)(destination+cur_offset);
  PROCESS
 }
 DECISION
 return retval;
}
int main(){for(unsigned page=0;page<8;page++)for(unsigned part=0;part<4;part++)for(unsigned fix=0;fix<2;fix++){
 if(!fix&&part==page%4)continue;aborts=commits=peeks=fixups=visited=0;failPage=page;failPart=part;failFix=fix;
 memset(source,0x11,sizeof(source));memset(destination,0,sizeof(destination));int e=request();
 assert(e&&aborts==1&&!commits&&visited==page+1); // no later UPL page can clear failure
 }
 aborts=commits=visited=0;failPage=99;assert(!request()&&commits==1&&!aborts&&visited==8);
 for(auto b:destination)assert(b==0x7c);
 puts("PASS production 8pageUPL/16KiBfixups:56peek/parser failures abortentireUPL,no laterpageerrorreset,noCScommit; successcommit8pages ASanUBSan");}
'''.replace('GUARD',guard).replace('PROCESS',processing).replace('DECISION',decision)
with tempfile.TemporaryDirectory(prefix='b5q-dyld-upl-')as td:
 td=Path(td);(td/'test.cpp').write_text(base)
 subprocess.run(['c++','-std=c++17','-O1','-g','-fsanitize=address,undefined',str(td/'test.cpp'),'-o',str(td/'test')],check=True);subprocess.run([str(td/'test')],check=True)
# Every format now forwards the actual chain walk's return value.
fixup=s[s.index('static kern_return_t\nfixup_page('):s.index('static kern_return_t\ndyld_pager_peek(')]
for n in ['fixupPageAuth64','fixupCachePageAuth64','fixupPage64','fixupPage32']:assert 'return '+n+'('in fixup,n
