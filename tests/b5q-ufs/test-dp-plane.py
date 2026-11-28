#!/usr/bin/env python3
"""Compare owned linear BGRA plane programming with original Samsung bodies."""
from pathlib import Path
import hashlib,re,subprocess,tempfile
R=Path(__file__).resolve().parents[2]
D=R/'artifacts/b5q-p5-work/source-extra/qcom/opensource/display-drivers/msm/sde'
s=(D/'sde_hw_sspp.c').read_text()
assert hashlib.sha256(s.encode()).hexdigest()=='f4458bbd38a8da2d500abd427182bb9cd7c1617d80c4e90ef146d9be61cec75a'
fmt=(D/'sde_formats.c').read_text()
assert hashlib.sha256(fmt.encode()).hexdigest()=='f57e8d30c4155cf4eee79d158b2300a2b6e09fa6edaa4ccf765146cc4c076742'
def function(text,name):
 start=text.index(name);brace=text.index('{',start);depth=0
 for i in range(brace,len(text)):
  depth+=(text[i]=='{')-(text[i]=='}')
  if not depth:return text[start:i+1]
names=['sde_hw_sspp_update_multirect','sde_hw_sspp_setup_format','sde_hw_sspp_setup_rects',
       'sde_hw_sspp_setup_pe_config','sde_hw_sspp_setup_sourceaddress','sde_hw_sspp_setup_secure','sde_hw_sspp_setup_cdp']
bodies='\n'.join(function(s,'static void '+n+'(')for n in names)
macros='\n'.join(line for line in s.splitlines()if line.startswith(('#define SSPP_','#define MDSS_MDP_OP_')))
entry=re.search(r'INTERLEAVED_RGB_FMT\(ARGB8888,.*?\),',fmt,re.S)[0][:-1]
h=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <vector>
#include <utility>
#include <random>
#include "B5qDpPlane.h"
using u32=uint32_t;using u8=uint8_t;
#define BIT(n) (1u<<(n))
#define ARRAY_SIZE(a) (sizeof(a)/sizeof((a)[0]))
#define SDE_REG_READ(c,o) ((c)->read(o))
#define SDE_REG_WRITE(c,o,v) ((c)->write(o,v))
#define SDE_FORMAT_IS_FP16(f) false
#define SDE_FORMAT_IS_YUV(f) false
#define SDE_FORMAT_IS_DX(f) false
#define SDE_FORMAT_IS_UBWC(f) false
#define SDE_MAX_PLANES 4
#define SDE_SSPP_SCALER 0
#define pr_err(...) assert(false)
#define wmb() ((void)0)
enum {C0_G_Y,C1_B_Cb,C2_R_Cr,C3_ALPHA};
enum {SDE_PLANE_INTERLEAVED,SDE_CHROMA_RGB=0,SDE_CHROMA_H2V1,SDE_CHROMA_H1V2};
enum {SDE_FETCH_LINEAR,COLOR_8BIT=3};
enum {SDE_SSPP_CSC=4,SDE_SSPP_CSC_10BIT,SDE_SSPP_INLINE_CONST_CLR=31};
enum {SDE_SSPP_SRC=1,SDE_SSPP_FLIP_LR=1,SDE_SSPP_FLIP_UD=2,
 SDE_SSPP_SOURCE_ROTATED_90=4,SDE_SSPP_ROT_90=8,SDE_SSPP_SOLID_FILL=16};
enum sde_sspp_multirect_index {SDE_SSPP_RECT_SOLO,SDE_SSPP_RECT_0,SDE_SSPP_RECT_1};
enum sde_sspp_multirect_mode {SDE_SSPP_MULTIRECT_TIME_MX};
enum {SDE_SSPP_CDP_PRELOAD_AHEAD_64};
bool test_bit(unsigned n,const unsigned long *v){return (*v>>n)&1;}
struct sde_hw_blk_reg_map {
 std::vector<std::pair<unsigned,uint32_t>> writes;uint32_t op=0;
 uint32_t read(unsigned off){assert(off==0x38||off==0x70);return op;}
 void write(unsigned off,uint32_t val){writes.emplace_back(off,val);}
};
struct Cap {unsigned long features=0;};
struct sde_hw_pipe {sde_hw_blk_reg_map hw;Cap *cap;};
struct sde_rect {u32 x,y,w,h;};
struct sde_hw_pipe_cfg {
 sde_rect src_rect,dst_rect;struct{u32 plane_pitch[4],plane_addr[4];}layout;
 unsigned horz_decimation=0,vert_decimation=0;
};
struct sde_format {
 u32 fetch_planes=0,alpha_enable=0,element[4]{},bits[4]{},chroma_sample=0,
 unpack_align_msb=0,unpack_tight=0,unpack_count=0,bpp=0,fetch_mode=0;
};
struct sde_hw_pixel_ext {
 u32 right_ftch[4]{},right_rpt[4]{},left_ftch[4]{},left_rpt[4]{},btm_ftch[4]{},btm_rpt[4]{},top_ftch[4]{},top_rpt[4]{},
 roi_h[4]{},roi_w[4]{},num_ext_pxls_top[4]{},num_ext_pxls_btm[4]{},num_ext_pxls_left[4]{},num_ext_pxls_right[4]{};
};
struct sde_hw_pipe_cdp_cfg {bool enable,ubwc_meta_enable,tile_amortize_enable;unsigned preload_ahead;};
int _sspp_subblk_offset(sde_hw_pipe *,int id,u32 *v){assert(id==SDE_SSPP_SRC);*v=0;return 0;}
void _sspp_setup_opmode(sde_hw_pipe *,u32,u8){assert(false);}
void _sspp_setup_csc10_opmode(sde_hw_pipe *,u32,u8){assert(false);}
void sde_hw_sspp_setup_ubwc(sde_hw_pipe *,sde_hw_blk_reg_map *,const sde_format *,bool,bool,sde_sspp_multirect_index){assert(false);}
#define VIG_OP_CSC_EN 1
#define VIG_OP_CSC_SRC_DATAFMT 2
#define VIG_CSC_10_EN 1
#define VIG_CSC_10_SRC_DATAFMT 2
#define INTERLEAVED_RGB_FMT(fmt,a,r,g,b,e0,e1,e2,e3,uc,alpha,bp,flg,fm,np) \
 {SDE_PLANE_INTERLEAVED,alpha,{e0,e1,e2,e3},{g,b,r,a},SDE_CHROMA_RGB,0,1,uc,bp,fm}
'''
test=r'''
int main(){using namespace B5qDp;unsigned cases=0;std::mt19937 rng(0x3916);
 const sde_format originalFormat=ORIGINAL_FORMAT;
 auto check=[&](unsigned imageWidth,unsigned height,unsigned x,unsigned width,unsigned stride,uint32_t oldOp){
  const uint64_t bytes=uint64_t(stride)*height;Plane p;
  assert(p.make(0xc0000000,bytes,imageWidth,height,stride,x,width));
  sde_hw_blk_reg_map owned;owned.op=oldOp;
  assert(p.apply([&](unsigned o){return owned.read(o);},[&](unsigned o,u32 v){owned.write(o,v);}));
  Cap cap;sde_hw_pipe original{{{},oldOp},&cap};
  sde_hw_pipe_cfg cfg{{x,0,width,height},{0,0,width,height},{{stride,0,0,0},{0xc0000000,0,0,0}}};
  sde_hw_pixel_ext ext{};for(unsigned i=0;i<4;i++){ext.roi_w[i]=width;ext.roi_h[i]=height;}
  sde_hw_pipe_cdp_cfg cdp{true,false,false,SDE_SSPP_CDP_PRELOAD_AHEAD_64};
  sde_hw_sspp_update_multirect(&original,true,SDE_SSPP_RECT_SOLO,SDE_SSPP_MULTIRECT_TIME_MX);
  sde_hw_sspp_setup_format(&original,&originalFormat,false,0,SDE_SSPP_RECT_SOLO);
  sde_hw_sspp_setup_rects(&original,&cfg,SDE_SSPP_RECT_SOLO);
  sde_hw_sspp_setup_pe_config(&original,&ext);
  sde_hw_sspp_setup_sourceaddress(&original,&cfg,SDE_SSPP_RECT_SOLO);
  sde_hw_sspp_setup_secure(&original,SDE_SSPP_RECT_SOLO,false);
  sde_hw_sspp_setup_cdp(&original,&cdp,SDE_SSPP_RECT_SOLO);
  assert(owned.writes==original.hw.writes);cases++;
 };
 for(unsigned w:{640,1280,1920,2560,3840,4096,5120})for(unsigned h:{480,720,1080,2160}){
  const unsigned left=w>2560?w/2:w;check(w,h,0,left,w*4,0);
  if(left<w)check(w,h,left,w-left,w*4,0);
 }
 for(unsigned i=0;i<10000;i++){
  unsigned w=1+rng()%5120,h=1+rng()%4096,pitch=(w*4+255)&~255u;
  unsigned x=rng()%w,crop=1+rng()%(w-x);if(crop>2560)crop=2560;
  check(w,h,x,crop,pitch,rng());
 }
 unsigned rejects=0;
 auto reject=[&](uint64_t base,uint64_t bytes,unsigned w,unsigned h,unsigned pitch,unsigned x,unsigned crop){
  Plane p;assert(p.make(0xc0000000,8192,32,32,128,0,32));
  assert(!p.make(base,bytes,w,h,pitch,x,crop));unsigned writes=0;
  assert(!p.apply([](unsigned){assert(false);return 0u;},[&](unsigned,u32){writes++;}));
  assert(!writes&&!p.address&&!p.width&&!p.height);rejects++;
 };
 reject(0xc0000000,8191,32,64,128,0,32); // last row included
 reject(0xfffff000,8192,32,64,128,0,32); // 32bit wrap
 reject(~0ULL,8192,32,64,128,0,32);reject(0,8192,32,64,128,0,32);
 reject(0xc0000001,8192,32,64,128,0,32);reject(0xc0000000,8192,32,64,129,0,32);
 reject(0xc0000000,8192,32,64,124,0,32);reject(0xc0000000,1ULL<<32,32,64,65536,0,32);
 reject(0xc0000000,8192,0,64,128,0,32);reject(0xc0000000,8192,32,0,128,0,32);
 reject(0xc0000000,1ULL<<32,5121,64,20484,0,32);reject(0xc0000000,1ULL<<32,32,16384,128,0,32);
 reject(0xc0000000,8192,32,64,128,33,1);reject(0xc0000000,8192,32,64,128,31,2);
 reject(0xc0000000,8192,32,64,128,0,0);reject(0xc0000000,1ULL<<32,5120,64,20480,0,2561);
 // At the last addressable byte there is no unsigned truncation.
 Plane edge;assert(edge.make(0xfffff000,4096,32,32,128,0,32));
 printf("PASS SamsungDPplane %u exact-original BGRA/stride/crop/PE/CDP/register traces and %u bounds failures ASanUBSan\n",cases,rejects);
}
'''.replace('ORIGINAL_FORMAT',entry)
with tempfile.TemporaryDirectory(prefix='b5q-dp-plane-')as td:
 t=Path(td);(t/'test.cpp').write_text(h+'\n'+macros+'\n'+bodies+'\n'+test)
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-Wno-unused-parameter','-Wno-sign-compare','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(R/'UniXNU-b5q/package'),str(t/'test.cpp'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test')],check=True)
