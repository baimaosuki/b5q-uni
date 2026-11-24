#!/usr/bin/env python3
"""Compare the bounded production TU helper to original Samsung function bodies."""
from pathlib import Path
import hashlib,subprocess,tempfile
R=Path(__file__).resolve().parents[2]
original=R/'artifacts/b5q-p5-work/tu-original.inc'
fixed=R/'artifacts/b5q-p5-work/source-extra/include/drm/drm_fixed.h'
s=fixed.read_text()
def function(name):
 pos=s.index(name);start=s.rfind('static inline ',0,pos);brace=s.index('{',start);depth=0
 for i in range(brace,len(s)):
  depth+=(s[i]=='{')-(s[i]=='}')
  if not depth:return s[start:i+1]
math='\n'.join(function(n)for n in ['drm_int2fixp','drm_fixp2int','drm_fixp2int_ceil','drm_fixp_msbset','drm_fixp_mul','drm_fixp_div','drm_fixp_from_fraction'])
# A separate TU original is built with original kernel-style wrap semantics;
# production is sanitized and defines the same bit operations explicitly.
reference=r'''
#include <stdint.h>
#include <string.h>
namespace Original {
using s64=int64_t;using u64=uint64_t;using u32=uint32_t;using u8=uint8_t;using uint=unsigned;
static inline s64 div64_s64(s64 a,s64 b){return a/b;}
static inline u64 div64_u64_rem(u64 a,u64 b,u64 *r){*r=a%b;return a/b;}
#define DRM_FIXED_POINT 32
#define DRM_FIXED_ONE (1ULL << DRM_FIXED_POINT)
#define DRM_FIXED_EPSILON 1LL
#define DRM_FIXED_ALMOST_ONE (DRM_FIXED_ONE - DRM_FIXED_EPSILON)
#define DP_DEBUG(...) ((void)0)
#define DP_WARN(...) ((void)0)
'''+math+'\n'+original.read_text()+r'''
}
extern "C" void reference(unsigned pixel,unsigned width,unsigned blank,unsigned rate,unsigned lanes,uint32_t *out){
 Original::dp_tu_calc_input in{};in.lclk=rate*27;in.pclk_khz=pixel;in.hactive=width;in.hporch=blank;in.nlanes=lanes;in.bpp=24;in.pixel_enc=444;
 Original::dp_vc_tu_mapping_table t{};Original::_dp_panel_calc_tu(&in,&t);
 out[0]=t.tu_size_minus1;out[1]=t.valid_boundary_link|(t.delay_start_link<<16);out[2]=(t.valid_lower_boundary_link<<1)|(t.upper_boundary_count<<16)|(t.lower_boundary_count<<20)|uint32_t(t.boundary_moderation_en);
}
'''
test=r'''
#include <cassert>
#include <cstdio>
#include <random>
#include "B5qDpTu.h"
extern "C" void reference(unsigned,unsigned,unsigned,unsigned,unsigned,uint32_t*);
int main(){using namespace B5qDp;unsigned cases=0,rejected=0;
 const unsigned rates[]={6,10,20,30},lanes[]={1,2,4};
 const unsigned widths[]={640,1280,1920,2560,3840,4096},pixels[]={25175,27000,74250,148500,241500,297000,533250,594000};
 for(auto width:widths)for(auto pixel:pixels)for(auto rate:rates)for(auto lane:lanes){
  Mode m;m.width=width;m.height=1080;m.pixelKHz=pixel;m.hBlank=280;m.vBlank=45;m.hFront=88;m.hSync=44;m.vFront=4;m.vSync=5;
  TransferUnit t;if(!m.fits(lane,rate)){assert(!t.calculate(m,rate,lane));rejected++;continue;}
  uint32_t expected[3];reference(pixel,width,280,rate,lane,expected);bool ok=t.calculate(m,rate,lane);
  if(ok){assert(t.size==expected[0]&&t.boundary==expected[1]&&t.moderation==expected[2]);cases++;}else rejected++;
 }
 std::mt19937 rng(0x8550);for(unsigned i=0;i<300;i++){
  Mode m;m.width=320+rng()%3777;m.height=1080;m.pixelKHz=10000+rng()%585001;m.hBlank=80+rng()%921;m.vBlank=45;m.hFront=8;m.hSync=32;m.vFront=4;m.vSync=5;
  unsigned rate=rates[rng()%4],lane=lanes[rng()%3];TransferUnit t;
  if(!m.fits(lane,rate)){assert(!t.calculate(m,rate,lane));rejected++;continue;}
  uint32_t e[3];reference(m.pixelKHz,m.width,m.hBlank,rate,lane,e);if(t.calculate(m,rate,lane)){assert(t.size==e[0]&&t.boundary==e[1]&&t.moderation==e[2]);cases++;}else rejected++;
 }
 printf("PASS SamsungTU %u exact-reference outputs, %u bounded rejections; original adaptive rounding, RGB24, ASanUBSan\n",cases,rejected);
}
'''
with tempfile.TemporaryDirectory(prefix='b5q-dp-tu-')as td:
 t=Path(td);(t/'reference.cpp').write_text(reference);(t/'test.cpp').write_text(test)
 subprocess.run(['c++','-std=c++17','-O1','-fwrapv','-c',str(t/'reference.cpp'),'-o',str(t/'reference.o')],check=True)
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Wno-unused-variable','-Wno-sign-compare','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(R/'UniXNU-b5q/package'),str(t/'test.cpp'),str(t/'reference.o'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test')],check=True)
