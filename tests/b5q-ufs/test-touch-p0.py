from pathlib import Path
import subprocess,tempfile,re
root=Path(__file__).resolve().parents[2]
# Compare every reused upstream function body, not just a few expected results.
up=(root/'sources/UniXNU-sheng/package/Wn8030.c').read_text()
local=(root/'UniXNU-b5q/package/Wn8030Pointer.h').read_text()
for name in ['pointer_take','wn8030_gap_bucket','wn8030_pointer_report','wn8030_pointer_report_at']:
 def body(text):
  match=list(re.finditer(r'\b'+name+r'\([^;{}]*\)\s*\{',text))
  assert len(match)==1,name
  first=match[0].end()-1;depth=1;at=first+1
  while depth:
   depth+=(text[at]=='{')-(text[at]=='}');at+=1
  return text[first:at]
 assert body(up)==body(local),name
assert not (root/'UniXNU-b5q/package/B5qTouchPointer.h').exists()
assert 'digitizerPairGuard' in (root/'UniXNU-b5q/package/HidInputProbe.cpp').read_text()
with tempfile.TemporaryDirectory(prefix='b5q-p0-') as td:
 exe=Path(td)/'p0'
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=address,undefined','-I',str(root/'UniXNU-b5q/package'),str(Path(__file__).with_suffix('.cpp')),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True)
 # Exercise the actual worker's selection helper with only the bus command
 # response boundary supplied by the test; no alternate selection algorithm.
 driver=(root/'UniXNU-b5q/package/B5qTouch.cpp').read_text()
 first=driver.index('bool configureReports(');last=driver.index('\nvoid worker(',first)
 source=r'''
#include "B5qTouchReports.h"
#include <cassert>
#include <vector>
#include <cstdio>
using B5qTouch::Reports;
Reports reports;unsigned configBytes=0,layoutFailures=9;
struct TouchBus {bool app=true,config=true,full=true,delta=true;std::vector<unsigned> commands;};
template<class... T>void IOLog(const char *,T...){}
bool command(TouchBus &b,uint8_t cmd,const uint8_t *p,unsigned n,bool=false){
 b.commands.push_back(unsigned(cmd)<<8|(n?p[0]:0));
 if(cmd==0x20)return b.app;
 if(cmd==0x25){configBytes=b.config?128:0;return b.config;}
 return cmd!=5 || (p[0]==0x11?b.full:b.delta);
}
'''+driver[first:last]+r'''
int main(){
 for(unsigned bits=0;bits<16;++bits){
  TouchBus b;b.app=bits&1;b.config=bits&2;b.full=bits&4;b.delta=bits&8;
  reports.mode=0xc1;reports.reconfigure=true;
  const bool ok=configureReports(b);
  const bool full=b.app&&b.config&&b.full;
  const bool delta=b.app&&!full&&b.delta;
  assert(ok==(delta||full));
  assert(reports.mode==(delta?0xc1:full?0x11:0));
  assert(!reports.reconfigure&&!layoutFailures);
  assert(b.commands[0]==0x2000);
  if(!b.app)assert(b.commands.size()==1);
  if(full){assert(b.commands==std::vector<unsigned>({0x2000,0x2500,0x0511,0x06c1}));assert(configBytes);}
  else if(b.app){assert(b.commands[1]==0x2500);assert(b.commands[b.commands.size()-2]==0x0611&&b.commands.back()==0x05c1);}

 }
 puts("PASS production report-mode selection:16 app/config/0x11/0xc1 outcomes,atomic11first,C1onlyafterfullfailure,reset state");
}
'''
 src=Path(td)/'modes.cpp';src.write_text(source);exe=Path(td)/'modes'
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=address,undefined','-I',str(root/'UniXNU-b5q/package'),str(src),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True)
print('PASS all four reused Wn8030 function bodies match pinned upstream verbatim; old pointer removed; absolute digitizer guard preserved')

subprocess.run(["python3",str(root/"tests/b5q-ufs/test-review6.py")],check=True)
