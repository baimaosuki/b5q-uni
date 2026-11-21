"""Execute the actual worker's bounded delay prefix before any mapping."""
from pathlib import Path
import subprocess,tempfile
root=Path(__file__).resolve().parents[2];s=(root/'UniXNU-b5q/package/B5qUsbHost.cpp').read_text()
a=s.index('static void worker(void *,wait_result_t) {')
b=s.index(' const char *stage=',a)
prefix=s[a:b].replace('static void worker(void *,wait_result_t)','static void worker()')+'}\n'
test=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
bool supplied=false;unsigned requested=0,slept=~0u,logged=~0u;
bool PE_parse_boot_argn(const char *name,void *out,unsigned size){assert(!strcmp(name,"b5q-usb-delay")&&size==4);if(supplied)*static_cast<unsigned *>(out)=requested;return supplied;}
void IOLog(const char *,unsigned seconds){logged=seconds;}
void IOSleep(unsigned ms){slept=ms;}
'''
main=r'''
int main(){
 worker();assert(logged==35&&slept==35000);
 supplied=true;
 for(unsigned input:{0u,1u,35u,300u,301u,0xffffffffu}){requested=input;worker();assert(logged==(input>300?300:input)&&slept==logged*1000);}
 puts("PASS production USB worker delay: default35s, zero/explicit override and300s overflow bound before MMIO");
}
'''
with tempfile.TemporaryDirectory(prefix='b5q-usb-delay-')as td:
 p=Path(td)/'test.cpp';p.write_text('#include <initializer_list>\n'+test+prefix+main);out=p.with_suffix('')
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(p),'-o',str(out)],check=True)
 subprocess.run([str(out)],check=True)
