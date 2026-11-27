#!/usr/bin/env python3
"""Exercise the selected real stall monitor without unbuilt diagnostic imports."""
from pathlib import Path
import subprocess,tempfile,sys
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'UniXNU-b5q/scripts'))
from b5q_wifi import prepare
with tempfile.TemporaryDirectory(prefix='b5q-wifi-diag-')as td:
    td=Path(td);source=prepare(R/'sources/UniXNU-sheng',td).read_text()
    assert 'boot_cpu_kick'not in source and 'boot_kthread_report'not in source
    at=source.index('void check_input()');end=source.index('\n}\n',at)+2
    code=r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <cstdarg>
#include <string>
struct ifnet_stats_param {uint64_t packets_in,errors_in,dropped;};
int gIf;const char *ifnet_name(int){return "en";}unsigned ifnet_unit(int){return 1;}
unsigned short ifnet_flags(int){return 0x8863;}unsigned ifnet_eflags(int){return 0x40;}
unsigned ifnet_capabilities_enabled(int){return 0x10;}uint32_t gRxFrames;uint64_t received;unsigned logs;
struct {unsigned count,kicks,cleared,longest;bool kicked;}gStall;
void ifnet_stat(int,ifnet_stats_param *s){s->packets_in=received;}
void log(int,const char *format,...){char line[256];va_list a;va_start(a,format);vsnprintf(line,sizeof(line),format,a);va_end(a);assert(*line);++logs;}
FUNCTION
int main(){
 for(unsigned i=0;i<10;++i)check_input();assert(!gStall.count&&!logs);
 for(unsigned i=0;i<10;++i){++gRxFrames;check_input();}
 assert(gStall.count==1&&gStall.longest==10&&!gStall.kicks&&!gStall.kicked&&logs==3);
 ++received;check_input();assert(logs==4&&!gStall.cleared);
 ++gRxFrames;check_input();assert(gStall.count==2&&logs==5);
 puts("PASS production Wi-Fi monitor: idle is not stall,stalls counted/bounded,recovery retained,no fabricated CPU kicks or unresolved diagnostics");
}
'''.replace('FUNCTION',source[at:end]);(td/'test.cpp').write_text(code)
    subprocess.run(['c++','-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-Wno-misleading-indentation',
        '-fsanitize=address,undefined',str(td/'test.cpp'),'-o',str(td/'test')],check=True)
    subprocess.run([str(td/'test')],check=True)
