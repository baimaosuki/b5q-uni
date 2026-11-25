"""Run the actual USB family's explicit load-and-match sequence."""
from pathlib import Path
import subprocess,tempfile
root=Path(__file__).resolve().parents[2];s=(root/'UniXNU-b5q/package/UsbProbe.cpp').read_text()
a=s.index('        const char *families[]=');b=s.index('        void *handle',a);body=s[a:b]
stub=r'''
#include <cassert>
#include <cstdio>
#include <string>
#include <vector>
using OSReturn=int;constexpr int kIOReturnError=-1,kOSReturnSuccess=0;
int fail=-1,loaded=0,matched=0,released=0,logs=0;bool symbolFail=false,catalogueFail=false;
std::vector<std::string> names;
struct OSSymbol{
 static const OSSymbol *withCString(const char *s){if(symbolFail)return nullptr;names.emplace_back(s);return new OSSymbol;}
 void release()const{++released;delete this;}
};
struct Catalogue{bool startMatching(const OSSymbol *){++matched;return !catalogueFail;}}catalogue;
Catalogue *gIOCatalogue=&catalogue;
OSReturn OSKextLoadKextWithIdentifier(const char *){return loaded++==fail?-9:0;}
void IOLog(const char *,const char *,int){++logs;}
'''
test=r'''
int main(){
 for(int test=0;test<10;++test){
  fail=test<7?test:-1;symbolFail=test==7;catalogueFail=test==8;gIOCatalogue=test==9?nullptr:&catalogue;
  loaded=matched=released=logs=0;names.clear();run();
  assert(loaded==7&&logs==7);
  int successes=fail>=0?6:7;
  assert(released==(symbolFail?0:successes));assert(matched==((symbolFail||!gIOCatalogue)?0:successes));
 }
 puts("PASS production USB family loop: all7successful loads explicitly match; load/allocation/catalogue failures do not panic");
}
'''
with tempfile.TemporaryDirectory(prefix='b5q-usb-match-')as td:
 p=Path(td)/'test.cpp';p.write_text(stub+'int run(){\n'+body+'return 0;\n}\n'+test);out=p.with_suffix('')
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(p),'-o',str(out)],check=True)
 subprocess.run([str(out)],check=True)
