#!/usr/bin/env python3
"""Compile the actual public sysctl handler and verify its uint64/read-only ABI."""
import re,subprocess,tempfile,json
from pathlib import Path
r=Path(__file__).resolve().parents[2]
patch=(r/'UniXNU-b5q/patches/xnu/macos-lockdown-public-state.patch').read_text()
s='\n'.join(line[1:] for line in patch.splitlines() if line.startswith('+') and not line.startswith('+++'))
handler=re.search(r'static int\nsysctl_lockdown_mode_state_public SYSCTL_HANDLER_ARGS\n\{.*?\n\}',s,re.S)[0]
assert 'CTLTYPE_QUAD | CTLFLAG_RD | CTLFLAG_LOCKED' in s and 'CTLFLAG_RW' not in s
harness=r'''
#include <assert.h>
#include <stdint.h>
#include <string.h>
static int native_state,reads;
static int get_lockdown_mode_state(void){++reads;return native_state;}
struct request{unsigned char bytes[16];unsigned capacity,length;int error;};
static int sysctl_out(struct request*r,const void*p,unsigned n){r->length=n;if(r->error)return r->error;if(r->capacity<n)return 12;memcpy(r->bytes,p,n);return 0;}
#define SYSCTL_HANDLER_ARGS (void*oidp,void*arg1,int arg2,struct request*req)
#define SYSCTL_OUT(r,p,n) sysctl_out(r,p,n)
HANDLER
int main(void){int states[]={0,1,0,7,-1};for(unsigned i=0;i<5;++i){struct request r={.capacity=8};native_state=states[i];assert(!sysctl_lockdown_mode_state_public(0,0,0,&r));uint64_t value=99;memcpy(&value,r.bytes,8);assert(r.length==8&&value==(uint64_t)(states[i]!=0)&&reads==(int)i+1);}
struct request shortread={.capacity=4};assert(sysctl_lockdown_mode_state_public(0,0,0,&shortread)==12&&shortread.length==8);
struct request fault={.capacity=8,.error=14};assert(sysctl_lockdown_mode_state_public(0,0,0,&fault)==14);}
'''.replace('\nHANDLER\n','\n'+handler+'\n')
with tempfile.TemporaryDirectory(prefix='b5q-lockdown-')as tmp:
 tmp=Path(tmp);(tmp/'test.c').write_text(harness)
 subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(tmp/'test.c'),'-o',str(tmp/'test')],check=True)
 subprocess.run([str(tmp/'test')],check=True)
print('PASS public Lockdown Mode native state uint64 ABI, read-only registration, short-read and copyout errors')
