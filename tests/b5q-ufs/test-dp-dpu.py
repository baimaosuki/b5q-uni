#!/usr/bin/env python3
"""DPU route trace oracle from original CTL/LM/PP/INTF functions, plus isolation."""
from pathlib import Path
import hashlib,re,subprocess,tempfile
R=Path(__file__).resolve().parents[2]
D=R/'artifacts/b5q-p5-work/source-extra/qcom/opensource/display-drivers/msm/sde'
def checked(name,sha):
 text=(D/name).read_text();assert hashlib.sha256(text.encode()).hexdigest()==sha;return text
ctl=checked('sde_hw_ctl.c','bc3b3322210c44bc1139af30fd69976507e6f23ea58b3bb9b26565f76aeb2b71')
lm=checked('sde_hw_lm.c','2e85b966c12d1628a59d23ffcf81237a642e81ac85ce456de7f98ee6396469aa')
pp=checked('sde_hw_pingpong.c','ea7466a335fdc0f2d910a5107d86f3db0721af4fe89665f64f04788941b46734')
intf=checked('sde_hw_intf.c','e4247b167901b37effe805117947c6483d616576c6dd4e1742461b34b571b900')
def block(text,name):
 start=text.index(name);brace=text.index('{',start);depth=0
 for i in range(brace,len(text)):
  depth+=(text[i]=='{')-(text[i]=='}')
  if not depth:return text[start:i+1]
def macros(text):
 # Keep multiline macro continuations, too.
 values=[];lines=iter(text.splitlines())
 for line in lines:
  if not line.startswith('#define '):continue
  value=line
  while line.endswith('\\'):
   line=next(lines);value+='\n'+line
  values.append(value)
 return '\n'.join(values)
original='\n'.join([
 block(ctl,'struct ctl_sspp_stage_reg_map {')+';',
 block(ctl,'static const struct ctl_sspp_stage_reg_map\nsspp_reg_cfg_tbl')+';',
 block(ctl,'static void _sde_hw_ctl_get_mixer_cfg('),
 block(ctl,'static void sde_hw_ctl_setup_blendstage('),
 block(ctl,'static int sde_hw_ctl_intf_cfg_v1('),
 block(lm,'static void sde_hw_lm_setup_out('),
 block(pp,'static void _sde_hw_merge_3d_setup_blend_mode('),
 block(intf,'static void sde_hw_intf_bind_pingpong_blk('),
])
h=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <vector>
#include <map>
#include <utility>
#include <random>
#include "B5qDpDpu.h"
using u32=uint32_t;
#define BIT(n) (1u<<(n))
#define SDE_REG_READ(c,o) ((c)->read(o))
#define SDE_REG_WRITE(c,o,v) ((c)->write(o,v))
#define CTL_NUM_EXT 5
#define CTL_SSPP_MAX_RECTS 2
#define CTL_MIXER_BORDER_OUT BIT(24)
#define PIPES_PER_STAGE 2
enum sde_sspp {SSPP_NONE,SSPP_VIG0,SSPP_VIG1,SSPP_VIG2,SSPP_VIG3,SSPP_DMA0,SSPP_DMA1,SSPP_DMA2,SSPP_DMA3,SSPP_DMA4,SSPP_DMA5,SSPP_MAX};
enum sde_lm {LM_0=1,LM_1,LM_2,LM_3,LM_4,LM_5};
enum sde_sspp_multirect_index {SDE_SSPP_RECT_SOLO,SDE_SSPP_RECT_0,SDE_SSPP_RECT_1,SDE_SSPP_RECT_MAX};
enum sde_pingpong {PINGPONG_0=1,PINGPONG_1,PINGPONG_2,PINGPONG_3,PINGPONG_4,PINGPONG_5};
enum sde_3d_blend_mode {BLEND_3D_NONE,BLEND_3D_FRAME_INT,BLEND_3D_H_ROW_INT,BLEND_3D_V_ROW_INT,BLEND_3D_COL_INT};
enum {INTF_0=1,INTF_1,INTF_2,INTF_3,WB_0=1,DNSC_BLUR_0=1,MERGE_3D_0=1,CWB_0=1,CDM_0=1,SDE_CTL_MODE_SEL_CMD=1,SDE_MIXER_SOURCESPLIT=0};
bool test_bit(unsigned n,const unsigned long *v){return (*v>>n)&1;}
struct Io {
 std::map<unsigned,u32> regs;std::vector<std::pair<unsigned,u32>> writes;
 bool dma=true,autoLatch=false,stuckTiming=false,runFrame=false;unsigned barriers=0,elapsed=0;
 u32 read(unsigned off){assert(!(off&3)&&off<0x84000);
  if(off==0x3526c&&stuckTiming)return 1;
  if(off==0x3526c&&runFrame)return regs[0x35000]&1;
  if(off==0x350ac&&runFrame&&(regs[0x35000]&1))return ++regs[off];
  if(autoLatch&&off>=0x16000&&off<0x1c000&&(off&0xfff)==0x18)regs[off]=0;
  return regs[off];}
 void write(unsigned off,u32 v){assert(!(off&3)&&off<0x84000);regs[off]=v;writes.emplace_back(off,v);}
 bool dmaAllowed(uint64_t addr,uint64_t bytes){return dma&&addr>=0xc0000000&&addr<=0xc8000000&&bytes<=0xc8000000-addr;}
 void barrier(){barriers++;}
 void delay(unsigned us){elapsed+=us;}
};
struct sde_hw_blk_reg_map {Io *io;unsigned base;u32 read(unsigned o){return io->read(base+o);}void write(unsigned o,u32 v){io->write(base+o,v);}};
struct MixerCaps {unsigned long features=0;};
struct sde_hw_ctl {sde_hw_blk_reg_map hw;MixerCaps *mixer_hw_caps;unsigned mixer_count;};
struct sde_hw_stage_cfg {sde_sspp stage[12][2]{};sde_sspp_multirect_index multirect_index[12][2]{};};
int _mixer_stages(MixerCaps *,unsigned,sde_lm){return 11;}
struct sde_hw_intf_cfg_v1 {
 unsigned intf_count=0,intf[4]{},intf_master=0,wb_count=0,wb[4]{},dnsc_blur_count=0,dnsc_blur[4]{},
 merge_3d_count=0,merge_3d[4]{},cwb_count=0,cwb[4]{},cdm_count=0,cdm[4]{},intf_mode_sel=0;
};
struct sde_hw_mixer {sde_hw_blk_reg_map hw;};
struct sde_hw_mixer_cfg {u32 out_height,out_width;bool right_mixer;};
struct sde_hw_merge_3d {sde_hw_blk_reg_map hw;};
struct sde_hw_intf {sde_hw_blk_reg_map hw;struct{bool split_link_en=false;}cfg;};
'''
# Only definitions used by these original bodies; conflicting block-local
# names are otherwise harmless but unrelated kernel macros need no shim.
defines='\n'.join(macros(text)for text in [ctl,lm,pp,intf])
test=r'''
int main(){using namespace B5qDp;unsigned cases=0,rejected=0;std::mt19937 rng(0xae00000);
 for(unsigned width:{640,1280,1920,2560,2561,3840,4096,5120})for(unsigned ctl=1;ctl<6;ctl++)for(unsigned pair=1;pair<3;pair++){
  Io before;before.regs[0x160f4]=2;before.regs[0x16014]=0xf0000000;
  before.regs[0x16000]=1;before.regs[0x45004]=0xa500438;
  before.regs[0x5000]=0xa500438;before.regs[0x36000]=1;before.regs[0x3625c]=0;
  for(unsigned c=1;c<6;c++)if(c!=ctl)before.regs[DpuResources::ctlBase[c]+0x64]=1;
  for(unsigned m=2;m<6;m++)if(m/2!=pair)before.regs[DpuResources::lmBase[m]+4]=1;
  DpuResources r;r.inspect([&](unsigned off){return before.read(off);});assert(r.choose(width));
  Mode mode{148500,uint16_t(width),1080,280,45,88,44,4,5,true,true};
  Dpu plan;assert(plan.make(r,mode,0xc0000000,uint64_t(width)*4*1080,width*4));
  Dpu prepared=plan;Io actual=before;assert(plan.apply(actual));assert(actual.barriers==1&&plan.active&&plan.savedCount<160);
  // The independent original oracle programs routing blocks. Plane and
  // INTF timing already have their own exact-original full trace tests.
  Io original=before;MixerCaps caps;sde_hw_ctl control{{&original,r.ctlBase[r.ctl]},&caps,6};
  for(unsigned i=0;i<r.count;i++){
   sde_hw_mixer mixer{{&original,r.lmBase[r.lm[i]]}};
   sde_hw_mixer_cfg config{mode.height,plan.planes[i].width,i!=0};sde_hw_lm_setup_out(&mixer,&config);
   sde_hw_stage_cfg stages;stages.stage[0][0]=sde_sspp(r.pipe[i]+1);
   sde_hw_ctl_setup_blendstage(&control,sde_lm(r.lm[i]+LM_0),&stages,true);
  }
  if(r.count==2){sde_hw_merge_3d merge{{&original,r.mergeBase[r.lm[0]/2]}};_sde_hw_merge_3d_setup_blend_mode(&merge,BLEND_3D_H_ROW_INT);}
  sde_hw_intf intf{{&original,0x35000},{}};sde_hw_intf_bind_pingpong_blk(&intf,true,sde_pingpong(r.lm[0]+PINGPONG_0));
  sde_hw_intf_cfg_v1 cfg;cfg.intf_count=1;cfg.intf[0]=INTF_0;
  if(r.count==2){cfg.merge_3d_count=1;cfg.merge_3d[0]=r.lm[0]/2+MERGE_3D_0;}
  assert(!sde_hw_ctl_intf_cfg_v1(&control,&cfg));
  std::vector<std::pair<unsigned,u32>> subset;
  for(auto a:actual.writes){
   bool found=false;for(auto o:original.writes)if(o.first==a.first){found=true;break;}
   if(found)subset.push_back(a);
  }
  assert(subset==original.writes);
  for(auto [address,value]:before.regs){
   bool selected=false;for(auto a:actual.writes)if(a.first==address)selected=true;
   if(!selected)assert(actual.regs[address]==value);
  }
  assert(actual.read(r.ctlBase[r.ctl]+0xfc)==plan.fetch);
  assert(actual.read(r.ctlBase[r.ctl]+0x18)==plan.flush);
  // DMA, a lost CTL/LM/PP/SSPP/MERGE, or an already active INTF must
  // reject the entire transaction before even the first register write.
  std::vector<unsigned> conflicts={0x35000,r.ctlBase[r.ctl]+0x64};
  for(unsigned i=0;i<r.count;i++){conflicts.push_back(r.lmBase[r.lm[i]]+4);conflicts.push_back(r.pipeBase[r.pipe[i]]);}
  if(r.count==2)conflicts.push_back(r.mergeBase[r.lm[0]/2]+4);
  for(unsigned address:conflicts){Io stolen=before;stolen.regs[address]=1;Dpu candidate=prepared;assert(!candidate.apply(stolen)&&stolen.writes.empty());rejected++;}
  Io noDma=before;noDma.dma=false;Dpu denied=prepared;assert(!denied.apply(noDma)&&noDma.writes.empty());rejected++;
  // A new interface taking the selected PP is also an ownership loss.
  Io stolenPp=before;stolenPp.regs[0x38000]=1;stolenPp.regs[0x3825c]=r.lm[0];
  Dpu candidate=prepared;assert(!candidate.apply(stolenPp)&&stolenPp.writes.empty());rejected++;
  // A timed-out stop retains all ownership and saved state; a second
  // attempt can finish, restore original registers, and release resources.
  actual.stuckTiming=true;const unsigned saved=plan.savedCount;
  assert(!plan.quiesce(actual)&&plan.active&&plan.savedCount==saved&&actual.elapsed==80000);
  actual.stuckTiming=false;assert(!plan.quiesce(actual)&&plan.active&&plan.savedCount==saved&&actual.elapsed==160000);
  std::vector<std::pair<unsigned,u32>> old;
  for(unsigned i=0;i<plan.savedCount;i++)old.emplace_back(plan.saved[i].offset,plan.saved[i].value);
  actual.autoLatch=true;assert(plan.quiesce(actual)&&!plan.active&&!plan.prepared&&!plan.savedCount);
  for(auto [off,value]:old)assert(actual.read(off)==value);
  auto writes=actual.writes.size();assert(plan.quiesce(actual)&&actual.writes.size()==writes);
  DpuResources reusable;reusable.inspect([&](unsigned off){return actual.read(off);});assert(reusable.choose(width));
  assert(reusable.ctl==r.ctl&&reusable.lm[0]==r.lm[0]&&reusable.pipe[0]==r.pipe[0]);
  assert(plan.make(reusable,mode,0xc0000000,uint64_t(width)*4*1080,width*4)&&plan.apply(actual)&&plan.quiesce(actual));
  assert(plan.make(reusable,mode,0xc0000000,uint64_t(width)*4*1080,width*4)&&plan.apply(actual));
  actual.runFrame=true;assert(plan.start(actual)&&plan.started);
  actual.runFrame=false;auto count=actual.writes.size();
  assert(!plan.flip(actual,0xc1000000,1,width*4)&&actual.writes.size()==count);
  assert(plan.flip(actual,0xc1000000,uint64_t(width)*4*1080,width*4)&&plan.pending);
  assert(!plan.latched(actual));count=actual.writes.size();
  assert(!plan.flip(actual,0xc0000000,uint64_t(width)*4*1080,width*4)&&actual.writes.size()==count);
  actual.regs[0x350ac]++;assert(plan.latched(actual)&&!plan.pending);
  assert(plan.flip(actual,0xc0000000,uint64_t(width)*4*1080,width*4));actual.regs[0x350ac]++;
  assert(plan.latched(actual)&&plan.quiesce(actual));
  assert(plan.make(reusable,mode,0xc0000000,uint64_t(width)*4*1080,width*4)&&plan.apply(actual));
  actual.regs[0x3526c]=0;assert(!plan.start(actual)&&plan.active&&plan.started);assert(plan.quiesce(actual));
  cases++;
 }
 // Original CTL flush tables are deliberately different from fetch bits.
 assert(Dpu::pipeFlush[8]==13&&Dpu::mixerFlush[4]==10);
 printf("PASS DP DPU %u exact-original CTL/LM/INTF/MERGE route traces and %u zero-write ownership/DMA failures ASanUBSan\n",cases,rejected);
}
'''
with tempfile.TemporaryDirectory(prefix='b5q-dp-dpu-')as td:
 t=Path(td);(t/'test.cpp').write_text(h+'\n'+defines+'\n'+original+'\n'+test)
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-Wno-unused-parameter','-Wno-sign-compare','-O1','-g','-fsanitize=address,undefined','-fno-sanitize-recover=all','-I'+str(R/'UniXNU-b5q/package'),str(t/'test.cpp'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test')],check=True)
