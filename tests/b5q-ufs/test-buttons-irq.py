"""Execute the actual shared-line handler with W1C registers modeled locally."""
from pathlib import Path
import re,subprocess,tempfile
root=Path(__file__).resolve().parents[2]
source=(root/'UniXNU-b5q/package/ButtonProbe.cpp').read_text()
body=source[source.index('void buttonsIrq(void *)'):source.index('uint32_t pressed()')]
body=body.replace('__asm__ volatile("dsb sy" ::: "memory");','')
stub=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
using event_t=void *;
unsigned irqWords[1],pdcWords[512],registers[32][3];
struct Window{unsigned *va;};Window gIntr={irqWords},gPdc={pdcWords};
constexpr unsigned kIrqStatus=0x104,kIrqClear=0x108,kLatchedClr=0x14,kPdcCfg=0x110,kPdcPin=1;
unsigned gApids=32,gEvents,reads,writes,wakes;int gPon=3,gGpio=5,gArb;Window gChn={nullptr};
int32_t native_buttons_stats[10];
unsigned *apidReg(int apid,unsigned reg){
 assert(apid>=0&&apid<32);
 if(reg==kIrqStatus){assert(apid==gPon||apid==gGpio);++reads;return &registers[apid][0];}
 assert(reg==kIrqClear);return &registers[apid][1];
}
int br_write8(unsigned *,int apid,unsigned reg,uint8_t value){assert(apid==gPon||apid==gGpio);assert(reg==kLatchedClr);registers[apid][2]=value;++writes;return 0;}
void thread_wakeup(void *){++wakes;}
'''
test=r'''
int main(){
 irqWords[0]=(1u<<3)|(1u<<5)|(1u<<7)|(1u<<29);registers[3][0]=0x80;registers[5][0]=1;
 buttonsIrq(nullptr);
 assert(registers[3][1]==0x80&&registers[3][2]==0x80&&registers[5][1]==1&&registers[5][2]==1);
 assert(registers[7][1]==0xff&&registers[29][1]==0xff&&reads==2&&writes==2);
 assert(gEvents==1&&wakes==1&&native_buttons_stats[6]==2&&native_buttons_stats[0]!=-9);
 // Apply the arbiter's write-one-clear behavior: the shared line deasserts.
 for(unsigned i=0;i<32;++i)if(registers[i][1])irqWords[0]&=~(1u<<i);
 assert(irqWords[0]==0);
 puts("PASS production shared SPMI IRQ: own status/peripheral ack, foreign arbiter-only clear, shared line deasserted");
}
'''
with tempfile.TemporaryDirectory(prefix='b5q-buttons-')as td:
 p=Path(td)/'test.cpp';p.write_text(stub+body+test);out=p.with_suffix('')
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(p),'-o',str(out)],check=True)
 subprocess.run([str(out)],check=True)
