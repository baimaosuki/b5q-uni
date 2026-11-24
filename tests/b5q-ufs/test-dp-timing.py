#!/usr/bin/env python3
"""Compare DP INTF writes with the exact original Samsung function body."""
from pathlib import Path
import hashlib,re,subprocess,tempfile
R=Path(__file__).resolve().parents[2]
D=R/'artifacts/b5q-p5-work/source-extra/qcom/opensource/display-drivers/msm/sde'
s=(D/'sde_hw_intf.c').read_text()
assert hashlib.sha256(s.encode()).hexdigest()=='e4247b167901b37effe805117947c6483d616576c6dd4e1742461b34b571b900'
def function(text,name):
 start=text.index(name);brace=text.index('{',start);depth=0
 for i in range(brace,len(text)):
  depth+=(text[i]=='{')-(text[i]=='}')
  if not depth:return text[start:i+1]
body=function(s,'static void sde_hw_intf_setup_timing_engine(')
params=function((D/'sde_hw_intf.h').read_text(),'struct intf_timing_params {')+';'
macros='\n'.join(l for l in s.splitlines()if l.startswith('#define INTF_'))
h=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <vector>
#include <utility>
#include <random>
#include "B5qDpTiming.h"
using u32=uint32_t;
#define BIT(n) (1u<<(n))
#define DIV_ROUND_UP(a,b) (((a)+(b)-1)/(b))
#define SDE_REG_READ(c,off) ((c)->read(off))
#define SDE_REG_WRITE(c,off,val) ((c)->write(off,val))
#define SDE_FORMAT_IS_YUV(fmt) false
enum {INTF_EDP,INTF_DP,INTF_DSI,INTF_HDMI,C0_G_Y=0,C1_B_Cb=1,C2_R_Cr=2,COLOR_8BIT=3,SDE_INTF_TE_ALIGN_VSYNC=1};
struct sde_hw_blk_reg_map {
 std::vector<std::pair<unsigned,uint32_t>> writes;uint32_t config;
 uint32_t read(unsigned off){assert(off==4);return config;}
 void write(unsigned off,uint32_t val){writes.emplace_back(off,val);}
};
struct Cap {unsigned type=INTF_DP,features=0;};
struct sde_hw_intf {sde_hw_blk_reg_map hw;Cap *cap;struct {bool split_link_en=false;}cfg;};
struct sde_format {uint32_t bits[4]={3,3,3,3};};
static void _check_and_set_comp_bit(sde_hw_intf *,bool,bool en,uint32_t *cfg){assert(!en);*cfg&=~BIT(12);}
'''
test=r'''
int main(){using namespace B5qDp;unsigned cases=0;
 auto check=[&](const Mode &m,uint32_t old){
  IntfTiming actual;assert(actual.make(m,old));
  intf_timing_params p{};p.width=p.xres=m.width;p.height=p.yres=m.height;
  // Apply sde_encoder_phys_vid's DP bottom-right transform.
  p.h_back_porch=m.hBlank-m.hSync;p.v_back_porch=m.vBlank-m.vSync;
  p.hsync_pulse_width=m.hSync;p.vsync_pulse_width=m.vSync;
  p.hsync_polarity=!m.hPositive;p.vsync_polarity=!m.vPositive;p.underflow_clr=255;
  Cap cap;sde_hw_intf ctx{{{},old},&cap,{}};sde_format fmt;
  sde_hw_intf_setup_timing_engine(&ctx,&p,&fmt);
  std::vector<std::pair<unsigned,uint32_t>> writes;actual.apply([&](unsigned o,uint32_t v){writes.emplace_back(o,v);});
  assert(writes==ctx.hw.writes);cases++;
 };
 for(auto v:ctaTimings){Modes modes;assert(modes.advertisedVic(v.vic));check(modes.values[0],0xa5000123);}
 std::mt19937 rng(0xae90000);for(unsigned i=0;i<2000;i++){
  Mode m;m.width=320+rng()%3777;m.height=200+rng()%1961;m.hSync=8+rng()%121;m.hFront=1+rng()%240;
  m.hBlank=m.hSync+m.hFront+1+rng()%256;m.vSync=1+rng()%15;m.vFront=1+rng()%15;
  m.vBlank=m.vSync+m.vFront+1+rng()%64;m.pixelKHz=25175;m.hPositive=rng()&1;m.vPositive=rng()&1;check(m,rng());
 }
 {IntfTiming t;Mode m;assert(!t.make(m,0)&&t.count==0);}
 printf("PASS SamsungDPUtiming %u exact-original write traces/DP-bottom-right/negative-sync-polarity/configpreservation/bounds ASanUBSan\n",cases);
}
'''
with tempfile.TemporaryDirectory(prefix='b5q-dp-timing-')as td:
 t=Path(td);(t/'test.cpp').write_text(h+params+'\n'+macros+'\n'+body+'\n'+test)
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-Wno-unused-parameter','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(R/'UniXNU-b5q/package'),str(t/'test.cpp'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test')],check=True)
