// Hardware-free tests of the production GENI and QUP helpers, not a second driver.
#include "GeniI2c.h"
#include "B5qQupClock.h"
#include "B5qMax77705.h"
#include <cassert>
#include <cstdio>
#include <map>
#include <utility>
#include <vector>

struct Engine {
 std::map<unsigned,uint32_t> regs;
 std::vector<std::pair<unsigned,uint32_t>> writes;
 Engine(){regs[GENI_FW_REVISION]=GENI_PROTO_I2C<<8;regs[GENI_CGC_CTRL]=0x100;
  regs[GENI_DMA_GENERAL_CFG]=0x100;regs[GENI_GSI_EVENT_EN]=15;regs[GENI_SE_IRQ_EN]=0x100;
  regs[GENI_HW_PARAM_0]=16<<16;regs[GENI_HW_PARAM_1]=16<<16;}
 static uint32_t read(void *p,uint32_t off){return static_cast<Engine*>(p)->regs[off];}
 static void write(void *p,uint32_t off,uint32_t value){auto &e=*static_cast<Engine*>(p);e.writes.emplace_back(off,value);e.regs[off]=value;}
 GeniIo io(){return {read,write,this};}
};

void cold(){
 for(unsigned level=0;level<8;++level)for(unsigned hub=0;hub<2;++hub){
  Engine e;e.regs[GENI_CLK_SEL]=level;const GeniIo io=e.io();
  assert(geni_se_init(&io)==0);
  const std::vector<std::pair<unsigned,uint32_t>> expected={{0x28,0x17f},{0xe30,0x10f},{0x24,0x7f},{0x20,1},{0xe18,0},{0xe1c,0x10c}};
  assert(e.writes==expected);assert(e.regs[GENI_CLK_SEL]==level);
  GeniI2c g;uint32_t config=0;
  assert((hub?geni_i2c_prepare_hub_xo(&g,&io,0x66,&config):geni_i2c_prepare_xo(&g,&io,0x3e,&config))==0);
  assert(config==0x03000021 && e.regs[GENI_CLK_SEL]==level);
  assert(e.regs[GENI_SCL_COUNTERS]==0x00702818 && e.regs[GENI_DMA_MODE]==0);
  assert(e.regs[GENI_GSI_EVENT_EN]==0 && e.regs[GENI_OUTPUT_CTRL]==0x7f);
  for(auto w:e.writes){assert(w.first!=GENI_CLK_SEL);assert(w.first<0xc00 || w.first==0xe30 || w.first==0xe18 || w.first==0xe1c);}
  assert(geni_i2c_start_write(&g,0xb0,0x55)==0);
  assert(geni_i2c_event(&g,GENI_M_TX_WATERMARK)==GeniPending);
  assert(e.regs[GENI_TX_FIFO]==0x55b0);
  assert(geni_i2c_event(&g,GENI_M_CMD_DONE)==GeniDone);
 }
 for(unsigned fault=0;fault<3;++fault){
  Engine e;const GeniIo io=e.io();
  if(fault==0)e.regs[GENI_FW_REVISION]=1<<8;
  if(fault==1)e.regs[GENI_IF_DISABLE]=1;
  if(fault==2)e.regs[GENI_STATUS]=GENI_STATUS_M_ACTIVE;
  assert(geni_se_init(&io)==-1 && e.writes.empty());
 }
 // Samsung i2c-msm-geni.c treats every nonzero IF_DISABLE_RO as GSI_ONLY.
 for(uint32_t capability:{1u,2u,3u,0x80000000u,0xffffffffu}){
  Engine e;e.regs[GENI_IF_DISABLE]=capability;const GeniIo io=e.io();
  assert(geni_se_init(&io)==-1 && e.writes.empty());
  GeniI2c g;uint32_t config=0;
  assert(geni_i2c_prepare(&g,&io,0x3e,&config)==-1 && e.writes.empty());
  assert(geni_i2c_prepare_xo(&g,&io,0x3e,&config)==-1 && e.writes.empty());
  assert(geni_i2c_prepare_hub_xo(&g,&io,0x66,&config)==-1 && e.writes.empty());
 }
 assert(geni_se_init(nullptr)==-1);
 Engine e;GeniIo io=e.io();io.write=nullptr;assert(geni_se_init(&io)==-1 && e.writes.empty());
 io=e.io();io.read=nullptr;assert(geni_se_init(&io)==-1 && e.writes.empty());
 puts("PASS production cold GENI: exact six writes/order, rejection without writes, CLK_SEL levels0..7 retained by both XO APIs, FIFO command completes");
}

void clocks(){
 for(uint32_t value:{0x80000002u,0x80000003u,2u,0u}){
  unsigned reads=0,delays=0;uint32_t last=0;
  assert(B5qQupClock::branch([&](unsigned o){assert(o==0x23280);++reads;return value;},[&](unsigned){++delays;},0x23280,last));
  assert(reads==1 && delays==0 && last==value);
 }
 {
  unsigned reads=0,delays=0;uint32_t last=0;
  assert(!B5qQupClock::branch([&](unsigned){++reads;return 0x80000000u;},[&](unsigned us){assert(us==10);++delays;},0x18754,last));
  assert(reads==2000 && delays==2000 && last==0x80000000);
 }
 for(bool gate:{false,true}){
  unsigned reads=0,delays=0;uint32_t last=0;
  assert(B5qQupClock::branch([&](unsigned){return ++reads==5?(gate?0x80000002u:0u):0x80000000u;},[&](unsigned){++delays;},0x23280,last));
  assert(reads==5 && delays==4);
 }
 for(unsigned rcg:{0x184f0u,0x18760u})for(unsigned wanted=0;wanted<8;++wanted)for(unsigned hid:{0u,1u}){
  std::vector<unsigned> reads;unsigned writes=0,delays=0,level=8;uint32_t dfs=0;
  auto rd=[&](unsigned o){reads.push_back(o);if(o==rcg+0x14)return 0xa5u;
   assert(o>=rcg+0x1c && o<=rcg+0x38 && (o-rcg)%4==0);
   return o==rcg+0x1c+4*wanted?0x80000000u|hid:0x102u;};
  assert(B5qQupClock::xo(rd,[&](unsigned,uint32_t){++writes;},[&](unsigned){++delays;},rcg,level,dfs));
  assert(level==wanted && dfs==0xa5 && writes==0 && delays==0);
  assert(reads.size()==wanted+2);
 }
 for(unsigned rcg:{0x184f0u,0x18760u}){
  unsigned writes=0,level=0,reads=0;uint32_t dfs=0;
  assert(!B5qQupClock::xo([&](unsigned o){++reads;return o==rcg+0x14?1u:0x102u;},[&](unsigned,uint32_t){++writes;},[](unsigned){assert(false);},rcg,level,dfs));
  assert(writes==0 && level==8 && dfs==1 && reads==9);
 }
 for(unsigned rcg:{0x184f0u,0x18760u,0x170e8u})for(unsigned fault=0;fault<4;++fault){
  unsigned level=8,delays=0;uint32_t dfs=99;
  std::map<unsigned,uint32_t> regs={{rcg+4,0xa500371f},{rcg,0x80}};
  std::vector<std::pair<unsigned,uint32_t>> writes;
  auto rd=[&](unsigned o){assert(o==rcg || o==rcg+4 || (o==rcg+0x14 && rcg!=0x170e8));return regs[o];};
  auto wr=[&](unsigned o,uint32_t v){writes.emplace_back(o,v);if(!(fault==2 && o==rcg+4))regs[o]=v;};
  auto delay=[&](unsigned us){assert(us==10);++delays;if(fault!=1)regs[rcg]&=~1u;if(fault==3)regs[rcg+4]^=0x100;};
  const bool ok=B5qQupClock::xo(rd,wr,delay,rcg,level,dfs,rcg!=0x170e8);
  assert(ok==(fault==0) && dfs==0 && writes.size()==2);
  assert((writes[0]==std::make_pair(rcg+4,0xa5000001u)) && (writes[1]==std::make_pair(rcg,0x81u)));
  assert(level==(ok?0u:8u) && delays==(fault==1?2000u:1u));
 }
 puts("PASS production clock helpers: HW_CTL skip/transition, bounded non-HW timeout, all SE4/SE6 DFS levels with zero GCC writes, nonDFS faults, dedicated SE8 no DFS reads");
}

void roles(){
 // Official PDIC separates power (CC0 bits2:0) from data (PD1 bit7).
 for(unsigned cc0=0;cc0<256;++cc0)for(unsigned cc1=0;cc1<256;++cc1)for(unsigned pd:{0u,128u}){
  B5qMax77705::Cable c={uint8_t(cc0),uint8_t(cc1),uint8_t(pd),0,true};
  const bool attached=!(cc1&2)&&(cc0%8==1||cc0%8==2);
  assert(c.role()==(attached?(pd?2:1):0));
  assert(c.sourceVbus(c.role())==(attached&&cc0%8==2));
 }
 puts("PASS production Max77705:131072 CC/power/data/water combinations; Sink+DFP and Source+UFP stay independent");
}
int main(){cold();clocks();roles();}
