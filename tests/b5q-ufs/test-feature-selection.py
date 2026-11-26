#!/usr/bin/env python3
"""Execute actual feature/override logic and enforce the loader's real line bounds."""
from pathlib import Path
import subprocess,tempfile,tomllib,re
R=Path(__file__).resolve().parents[2];text=(R/'UniXNU-b5q/package/B5qFeatures.h').read_text();begin=text.index('namespace B5qFeatures {')
code=r'''
#include <cstdint>
#include <cstring>
#include <cassert>
#include <cstdio>
unsigned mask,bytes,releases,reads;bool argument,menuArg;unsigned overrideValue,menuValue;
struct OSData {unsigned getLength(){return bytes;}const void*getBytesNoCopy(){return &mask;}}data;
struct IORegistryEntry {static IORegistryEntry *fromPath(const char *p,int plane);void *getProperty(const char*){return &data;}void release(){releases++;}}entry;
IORegistryEntry* IORegistryEntry::fromPath(const char *p,int plane){assert(!strcmp(p,"/chosen")&&plane==1);reads++;return &entry;}
int gIODTPlane=1;
#define OSDynamicCast(T,p) static_cast<T*>(p)
#define OSSafeReleaseNULL(p) do{if(p){p->release();p=nullptr;}}while(0)
bool PE_parse_boot_argn(const char *name,void *out,unsigned n){assert(n==4);if(!strcmp(name,"b5q-f")){if(!menuArg)return false;*(unsigned*)out=menuValue;return true;}if(!argument)return false;*(unsigned*)out=overrideValue;return true;}
SOURCE
int main(){using namespace B5qFeatures;unsigned cases=0;
 for(mask=0;mask<128;mask++)for(unsigned bit=1;bit<=64;bit*=2){
  argument=menuArg=false;bytes=4;unsigned n=reads;assert(option("test",bit,2)==((mask&bit)?2u:0u)&&reads==n+1&&reads==releases);cases++;
  for(bytes=0;bytes<=8;bytes++){assert(option("test",bit,2)==(bytes==4&&(mask&bit)?2u:0u));cases++;}
  for(menuValue=0;menuValue<128;menuValue++){
   menuArg=true;n=reads;assert(option("test",bit,2)==((menuValue&bit)?2u:0u)&&reads==n);cases++;
  }
  for(overrideValue=0;overrideValue<4;overrideValue++){
   argument=true;n=reads;assert(option("test",bit,2)==overrideValue&&reads==n);cases++;
  }
 }
 printf("PASS actual ADT feature-mask/short-menu-mask/independent bootarg precedence+malformed sizes:%u cases ASanUBSan\n",cases);
}
'''.replace('SOURCE',text[begin:])
with tempfile.TemporaryDirectory(prefix='b5q-features-')as td:
 td=Path(td);(td/'test.cpp').write_text(code)
 subprocess.run(['c++','-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(td/'test.cpp'),'-o',str(td/'test')],check=True)
 subprocess.run([str(td/'test')],check=True)
board=tomllib.loads((R/'UniXNU-b5q/board.toml').read_text());args=' '.join(board['payload']['kernel_args']).encode();assert len(args)<=1023
paths=list((R/'UniXNU/drivers/DarwinBoot').rglob('bootargs.h'))
# Physical boot ABI used by XNU/loader:1024-byte CommandLine, trailing NUL.
h=R/'sources/UniXNU/out/feeds/xnu-3199e8bc/pexpert/pexpert/arm64/boot.h';s=h.read_text();assert re.search(r'#define\s+BOOT_LINE_LENGTH\s+1024',s)
loader=(R/'UniXNU/drivers/DarwinBoot/DarwinBootPkg/Driver/DarwinBoot.c').read_text();assert 'CommandLine[1024]'in loader
# The XNU entry now intentionally consumes the full 1023-byte payload budget
# for the requested Bluetooth diagnostics. b5q-f is added only to the
# separately generated daily/safe/ram-fallback menu profiles, not appended to
# the XNU profile at runtime.
assert len(args)+1<=1024
print('PASS current board arguments fit the original 1024-byte command line with NUL; feature-mask tests remain independent')
