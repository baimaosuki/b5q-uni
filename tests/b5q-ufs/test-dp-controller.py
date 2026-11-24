#!/usr/bin/env python3
"""Check original MSA rounding and production DP controller state writes."""
from pathlib import Path
import hashlib,re,subprocess,tempfile
R=Path(__file__).resolve().parents[2]
D=R/'artifacts/b5q-p4-work/samsung-source/full/qcom/opensource/display-drivers/msm/dp'
E=R/'artifacts/b5q-p5-work/source-extra'
def function(text,name):
 start=text.index(name);brace=text.index('{',start);depth=0
 for i in range(brace,len(text)):
  depth+=(text[i]=='{')-(text[i]=='}')
  if not depth:return text[start:i+1]
fixed=(E/'include/drm/drm_fixed.h').read_text()
math='\n'.join(function(fixed,'static inline '+signature)for signature in [
 's64 drm_int2fixp','int drm_fixp2int(','unsigned drm_fixp_msbset','s64 drm_fixp_mul','s64 drm_fixp_from_fraction'])
rational=(E/'lib/math/rational.c').read_text()
assert hashlib.sha256(rational.encode()).hexdigest()=='74319b2f859e77eff7c9123e8606c72b8d269133371ab24d04fc328c89721e06'
ratio=function(rational,'void rational_best_approximation(')
original=(D/'dp_catalog_v420.c').read_text()
assert hashlib.sha256(original.encode()).hexdigest()=='07d1f6f4d98f9c2c5fd35cd7a4ca9ace66565b4cf3ff8f57f9f8f42aafe0e1dc'
msa=function(original,'static void dp_catalog_panel_config_msa_v420(')
# Keep the original arithmetic and writes; replace only catalog/IO plumbing.
msa=msa.replace('dp_catalog = container_of(panel, struct dp_catalog, panel);','dp_catalog = &panel->catalog;')
msa=msa.replace('catalog = container_of(dp_catalog->sub, struct dp_catalog_private_v420, sub);','catalog = dp_catalog->sub;')
ref=r'''
#include <cstdint>
#include <climits>
#include <algorithm>
using s64=int64_t;using u64=uint64_t;using u32=uint32_t;
static inline u64 div64_u64_rem(u64 a,u64 b,u64 *r){*r=a%b;return a/b;}
#define DRM_FIXED_POINT 32
#define DRM_FIXED_ONE (1ULL<<32)
#define DRM_FIXED_EPSILON 1LL
#define DRM_FIXED_ALMOST_ONE (DRM_FIXED_ONE-DRM_FIXED_EPSILON)
#define DP_DEBUG(...) ((void)0)
#define DP_ERR(...) ((void)0)
using std::min;
struct dp_io_data {u32 values[2]{};};
struct Io {dp_io_data *dp_link;};
struct dp_catalog_private_v420 {Io *io;};
struct dp_catalog {dp_catalog_private_v420 *sub;};
struct dp_catalog_panel {unsigned stream_id;dp_catalog catalog;};
enum {DP_STREAM_MAX=2,DP_STREAM_1=1,DP_SOFTWARE_MVID=0x10,DP_SOFTWARE_NVID=0x18,DP1_SOFTWARE_MVID=0x414,DP1_SOFTWARE_NVID=0x418};
#define dp_write(off,val) io_data->values[(off)==DP_SOFTWARE_MVID?0:1]=(val)
'''+math+'\n'+ratio+'\n'+msa+r'''
extern "C" void referenceMsa(unsigned rate,unsigned pixel,uint32_t out[2]){
 dp_io_data data;Io io{&data};dp_catalog_private_v420 sub{&io};dp_catalog_panel panel{0,{&sub}};
 dp_catalog_panel_config_msa_v420(&panel,rate*27000,pixel);out[0]=data.values[0];out[1]=data.values[1];
}
'''
h=r'''
#include <cassert>
#include <cstdio>
#include <map>
#include <tuple>
#include <vector>
#include "B5qDpController.h"
using namespace B5qDp;
extern "C" void referenceMsa(unsigned,unsigned,uint32_t*);
struct Io {
 std::map<std::pair<Block,unsigned>,uint32_t>regs;std::vector<std::tuple<Block,unsigned,uint32_t>>writes;
 bool online=true;unsigned elapsed=0;
 bool connected(){return online;}void delay(unsigned us){elapsed+=us;}
 uint32_t read(Block b,unsigned off){return regs[{b,off}];}
 void write(Block b,unsigned off,uint32_t v){regs[{b,off}]=v;writes.emplace_back(b,off,v);}
};
int main(){unsigned cases=0;
 for(unsigned rate:{6u,10u,20u,30u})for(unsigned pixel=10000;pixel<=675000;pixel+=37){
  uint32_t expected[2];referenceMsa(rate,pixel,expected);Msa m;assert(m.calculate(pixel,rate));assert(m.mvid==expected[0]&&m.nvid==expected[1]);cases++;
 }
 for(unsigned lanes:{1u,2u,4u}){
  Io io;Controller<Io>c(io);io.regs[{Block::Link,0}]=0xa5000100;io.regs[{Block::Link,8}]=0xffabcdef;io.regs[{Block::Link,0x44}]=0xffffffff;
  assert(c.source(lanes));assert(io.read(Block::Link,0)==0xa3000001);assert(io.read(Block::Link,0x38)==0xe4);
  assert((io.read(Block::Link,8)&0x430)==((lanes-1)<<4));assert(io.read(Block::Link,0x44)==(0xfe0|(lanes==1?14u:lanes==2?8u:5u)));
  assert((io.writes[io.writes.size()-4]==std::make_tuple(Block::Link,0u,0xa3000000u)));
  assert((io.writes[io.writes.size()-3]==std::make_tuple(Block::Link,0u,0xa3000002u)));
  for(unsigned p:{1u,2u,3u,7u}){unsigned bit=p==7?3:p-1;io.regs[{Block::Link,0x40}]=1u<<(bit+3);assert(c.pattern(p));assert(io.read(Block::Link,4)==(1u<<bit));}
  io.regs[{Block::Link,0x40}]=0;assert(!c.pattern(1)&&c.failed==1);assert(c.pattern(0)&&io.read(Block::Link,4)==0);
  assert(!c.video()&&c.failed==2&&io.elapsed==10000&&io.read(Block::Link,4)==0);
  io.regs[{Block::Link,0x40}]=1;assert(c.video());c.stop();assert(!(io.read(Block::Link,0)&1)&&!io.read(Block::Link,4));
 }
 Modes modes;assert(modes.advertisedVic(16));const auto mode=modes.values[0];
 for(unsigned rate:{6u,10u,20u,30u})for(unsigned lanes:{1u,2u,4u})for(bool enhanced:{false,true}){
  Io io;Controller<Io> c(io);bool ok=c.stream(mode,rate,lanes,enhanced);
  if(!mode.fits(lanes,rate)){assert(!ok&&io.writes.empty());continue;}assert(ok);
  assert(io.read(Block::Link,0x20)==(41u<<16|192u));assert(io.read(Block::Link,0x24)==(5u<<16|44u));
  assert(io.read(Block::Link,0x1c)==(1125u<<16|2200u));assert(io.read(Block::Link,0x28)==(1080u<<16|1920u));
  assert((io.read(Block::Link,8)&64)==unsigned(enhanced)*64);assert(io.read(Block::Pixel,0x10)==256&&!io.read(Block::Pixel,0x88));
 }
 {Io io;Controller<Io>c(io);Mode m;assert(!c.source(3)&&!c.pattern(4)&&!c.stream(m,20,4,true)&&io.writes.empty());}
 {Io io;io.online=false;Controller<Io>c(io);assert(!c.source(4)&&!c.stream(mode,20,4,true)&&!c.video()&&io.writes.empty());}
 printf("PASS SamsungDPcontroller: %u exact-original MSA outputs,source/SST/reset/TPS1..4/10msvideo/1080pMSA/TU/bandwidth/invalid-inputs ASanUBSan\n",cases);
}
'''
with tempfile.TemporaryDirectory(prefix='b5q-dp-controller-')as td:
 t=Path(td);(t/'ref.cpp').write_text(ref);(t/'test.cpp').write_text(h)
 subprocess.run(['c++','-std=c++17','-O1','-fwrapv','-c',str(t/'ref.cpp'),'-o',str(t/'ref.o')],check=True)
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-Wno-sign-compare','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(R/'UniXNU-b5q/package'),str(t/'test.cpp'),str(t/'ref.o'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test')],check=True)
