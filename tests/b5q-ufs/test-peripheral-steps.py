"""Execute the actual worker's delay and before/after probe instrumentation."""
from pathlib import Path
import subprocess,tempfile
root=Path(__file__).resolve().parents[2];s=(root/'UniXNU-b5q/package/LegacyDisplayProbe.cpp').read_text()
a=s.index('void b5qPeripheralWorker(void *,wait_result_t) {');b=s.index('\nvoid startB5qPeripherals()',a);body=s[a:b].replace('void b5qPeripheralWorker(void *,wait_result_t)','void run()')
functions=['sheng_cpufreq_probe','sheng_board_clock_probe','sheng_thermal_probe','sheng_thermal_level_probe','sheng_buttons_probe','native_hid_input_probe','b5q_touch_probe','sheng_dpu_probe']
stub=r'''
#include <cassert>
#include <cstdio>
#include <cstdarg>
#include <string>
#include <vector>
std::vector<std::string> events;
void IOSleep(unsigned ms){assert(ms==3000);events.emplace_back("sleep3000");}
void IOLog(const char *fmt,...){char b[256];va_list ap;va_start(ap,fmt);vsnprintf(b,sizeof(b),fmt,ap);va_end(ap);events.emplace_back(b);}
void *current_thread(){return nullptr;}
void thread_terminate(void *){events.emplace_back("terminated");}
'''
for fn in functions:stub+=f'void {fn}(){{events.emplace_back("{fn}:called");}}\n'
expected=['sleep3000','B5qPeripherals: stage=after-display\n']
for fn in functions:expected += ['B5qPeripherals: step='+fn+':before\n',fn+':called','B5qPeripherals: step='+fn+':after\n']
expected+=['B5qPeripherals: stage=ready\n','terminated']
import json
test='int main(){run();std::vector<std::string> expected={'+','.join(json.dumps(x)for x in expected)+'};assert(events==expected);puts("PASS actual peripheral worker: 3s delay, all8probes with16ordered before/after step logs");}\n'
with tempfile.TemporaryDirectory(prefix='b5q-peripheral-steps-')as td:
 p=Path(td)/'test.cpp';p.write_text(stub+body+test);out=p.with_suffix('')
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(p),'-o',str(out)],check=True)
 subprocess.run([str(out)],check=True)
