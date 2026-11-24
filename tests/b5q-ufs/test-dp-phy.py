#!/usr/bin/env python3
"""Compare production PLL writes against the pinned Samsung function body."""
from pathlib import Path
import hashlib,re,subprocess,tempfile
R=Path(__file__).resolve().parents[2]
P=R/'artifacts/b5q-p4-work/samsung-source/full/qcom/opensource/display-drivers/msm/dp'
s=(P/'dp_pll_4nm.c').read_text()
assert hashlib.sha256(s.encode()).hexdigest()=='3f18dd10fe1532c39374f2843deb828df46f0cae6322e22aa8d3ee98578d2f28'
start=s.index('static int dp_config_vco_rate_4nm(');brace=s.index('{',start);depth=0
for i in range(brace,len(s)):
 depth+=(s[i]=='{')-(s[i]=='}')
 if not depth:body=s[start:i+1];break
macros='\n'.join(l for l in (s+'\n'+(P/'dp_pll.h').read_text()).splitlines()if re.match(r'#define (?:DP_PHY_|TXn_|QSERDES_|DP_TRAN|DP_TX_INTERFACE|DP_VMODE)',l)and 'BIT('not in l)
h=r'''
#include <cassert>
#include <cstdio>
#include <map>
#include <tuple>
#include <vector>
#include "B5qDpPhy.h"
using namespace B5qDp;using u32=uint32_t;
struct Io {
 std::map<std::pair<Block,unsigned>,uint32_t>regs;std::vector<std::tuple<Block,unsigned,uint32_t>>writes;
 bool online=true;unsigned elapsed=0;Block failedBlock=Block::Dpu;unsigned failedOff=0;
 bool connected(){return online;}void delay(unsigned us){elapsed+=us;}
 uint32_t read(Block b,unsigned off){if(b==failedBlock&&off==failedOff)return 0;return regs[{b,off}];}
 void write(Block b,unsigned off,uint32_t v){regs[{b,off}]=v;writes.emplace_back(b,off,v);}
};
using dp_pll_params=PllParams;struct dp_pll;
struct dp_pll_db {dp_pll *pll;unsigned lane_cnt,orientation,rate_idx;const PllParams *pll_params;};
struct dp_pll {void *priv;Io *io;bool bonding_en=false,ssc_en=false;};
constexpr unsigned HSCLK_RATE_MAX=4,ORIENTATION_CC2=2;
constexpr Block dp_phy=Block::Phy,dp_pll_block=Block::Pll,dp_ln_tx0=Block::Tx0,dp_ln_tx1=Block::Tx1;
int dp_vco_pll_init_db_4nm(dp_pll_db *p,unsigned rate){p->rate_idx=rate==6?0:rate==10?1:rate==20?2:rate==30?3:4;return p->rate_idx<4?0:-1;}
int set_vco_div(dp_pll *pll,unsigned rate){auto &io=*pll->io;io.write(Block::Phy,0x70,(io.read(Block::Phy,0x70)&~3u)|(rate==6||rate==10?1:rate==20?2:0));return 0;}
#define DP_ERR(...) ((void)0)
#define DP_DEBUG(...) ((void)0)
#define EINVAL 22
#define wmb() ((void)0)
#define dp_pll_write(block,off,value) pll->io->write(block,off,value)
'''
body=body.replace('dp_pll_write(dp_pll,','dp_pll_write(dp_pll_block,').replace('struct dp_pll_params','PllParams')
test=r'''
int main(){unsigned cases=0;
 for(unsigned rate:{6u,10u,20u,30u})for(unsigned lanes:{1u,2u,4u})for(bool reverse:{false,true}){
  Io actual,original;Phy<Io>phy(actual);dp_pll_db db{nullptr,lanes,reverse?2u:1u,0,pllV11};dp_pll pll{&db,&original};db.pll=&pll;
  assert(phy.configure(rate,lanes,reverse));assert(dp_config_vco_rate_4nm(&pll,rate)==0);
  // SPARE0 passes route metadata; SSC disable is explicit because stale USB
  // firmware state cannot be assumed. Both are outside the reference body.
  auto writes=actual.writes;assert(std::get<1>(writes.front())==0xc8);writes.erase(writes.begin());
  auto at=std::find(writes.begin(),writes.end(),std::make_tuple(Block::Pll,0xc0,0u));assert(at!=writes.end());writes.erase(at);
  if(writes!=original.writes){fprintf(stderr,"trace sizes actual=%zu original=%zu\n",writes.size(),original.writes.size());for(unsigned n=0;n<writes.size()&&n<original.writes.size();n++)if(writes[n]!=original.writes[n]){fprintf(stderr,"PLL mismatch %u actual=%x/%x expected=%x/%x\n",n,std::get<1>(writes[n]),std::get<2>(writes[n]),std::get<1>(original.writes[n]),std::get<2>(original.writes[n]));break;}assert(false);}
  cases++;
 }
 for(unsigned fault=0;fault<5;fault++){Io io;io.regs[{Block::Pll,0x1f8}]=1;io.regs[{Block::Pll,0x1d0}]=3;io.regs[{Block::Phy,0xe4}]=3;
  io.failedBlock=fault<3?Block::Pll:Block::Phy;io.failedOff=fault==0?0x1f8:fault<3?0x1d0:0xe4;
  Phy<Io>phy(io);assert(!phy.enable()&&io.elapsed==10000);cases++;}
 {Io io;io.regs[{Block::Pll,0x1f8}]=1;io.regs[{Block::Pll,0x1d0}]=3;io.regs[{Block::Phy,0xe4}]=3;Phy<Io>phy(io);assert(phy.enable());phy.auxSetup();assert(io.regs[std::make_pair(Block::Phy,0x54)]==31&&io.regs[std::make_pair(Block::Phy,0x58)]==0);}
 for(unsigned v=0;v<5;v++)for(unsigned p=0;p<5;p++)for(unsigned rate:{6u,10u,20u,30u}){Io io;Phy<Io>phy(io);bool ok=phy.levels(v,p,rate,0x10020003);if(!ok)assert(io.writes.empty());else assert(v<=2&&p<=2&&v+p<=3);cases++;}
 printf("PASS SamsungPLL %ucases:24exactoriginalfunctiontraces/4x22v11params/5boundedlockfaults/V600AUX/originalDTswing\n",cases);
}
'''
with tempfile.TemporaryDirectory(prefix='b5q-dp-phy-')as td:
 t=Path(td);(t/'test.cpp').write_text('#include <algorithm>\n'+h+macros+'\n'+body+'\n'+test)
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-O1','-g','-fsanitize=address,undefined','-I'+str(R/'UniXNU-b5q/package'),str(t/'test.cpp'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test')],check=True)
