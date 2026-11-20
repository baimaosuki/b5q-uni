#!/usr/bin/env python3
"""Exercise the production ArmCpu probe with isolated IOKit/topology fixtures."""
import re
import subprocess
import tempfile
import tomllib
from pathlib import Path

root = Path(__file__).resolve().parents[2]
source = (root / 'sources/UniXNU/drivers/ArmCpu/ArmCpu.cpp').read_text()
probe = re.search(r'IOService \*ArmCpu::probe .*?\n\}\n', source, re.S)[0]
board = tomllib.loads((root / 'UniXNU-b5q/board.toml').read_text())
args = board['payload']['kernel_args']
for key in ['smp=1', 'armcpu-spi-ipi=1', 'armcpu-self-ipi=1', 'no-lc=1']:
    assert args.count(key) == 1
assert len(' '.join(args).encode()) < 1024
harness = r'''
#include <cassert>
#include <cstdint>
#include <cstring>
using SInt32=int;
struct OSData {const void *p; unsigned length;
 unsigned getLength(){return length;} const void* getBytesNoCopy(){return p;}};
struct IOService {OSData *type,*reg;
 OSData* getProperty(const char*key){return !strcmp(key,"reg")?reg:type;}};
#define OSDynamicCast(T,x) (x)
struct IOCPU:IOService {IOService* probe(IOService*,SInt32*){return this;}};
struct ArmCpu:IOCPU {IOService* probe(IOService*,SInt32*);};
constexpr int ARMCPU_SMP_SLOTS=8;
static unsigned smp;
static bool PE_parse_boot_argn(const char*key,void*out,unsigned n){
 assert(!strcmp(key,"smp")&&n==4);memcpy(out,&smp,4);return true;}
static int ml_get_boot_cpu_number(){return 0;}
static int ml_get_cpu_number(uint32_t id){return (id&255)?-1:int(id>>8);}
PROBE
int main(){ArmCpu cpu;uint32_t id=0;OSData type={"cpu",4},reg={&id,4};
 IOService nub={&type,&reg};int score=0;
 for(smp=0;smp<=1;++smp)for(unsigned core=0;core<8;++core){
  id=core<<8;assert((cpu.probe(&nub,&score)!=nullptr)==(core==0||smp==1));}
 smp=1;id=0x800;assert(!cpu.probe(&nub,&score));
 id=1;assert(!cpu.probe(&nub,&score));
 id=0;reg.length=3;assert(!cpu.probe(&nub,&score));reg.length=4;
 type.length=3;assert(!cpu.probe(&nub,&score));type.length=4;
 type.p="gpu";assert(!cpu.probe(&nub,&score));type.p="cpu";
 nub.type=nullptr;assert(!cpu.probe(&nub,&score));nub.type=&type;
 nub.reg=nullptr;assert(!cpu.probe(&nub,&score));
}
'''.replace('PROBE', probe)
with tempfile.TemporaryDirectory(prefix='b5q-cpu-probe-') as tmp:
    tmp = Path(tmp)
    (tmp / 'test.cpp').write_text(harness)
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=address,undefined', str(tmp / 'test.cpp'),
                    '-o', str(tmp / 'test')], check=True)
    subprocess.run([str(tmp / 'test')], check=True)
print('PASS actual ArmCpu probe: boot CPU, seven secondary opt-in cases, invalid affinity/type/reg; complete runtime arguments')
