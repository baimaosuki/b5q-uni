#include "B5qTouchProtocol.h"
#include "B5qTouchPointer.h"
#include "GeniI2c.h"
#include "B5qTouchClock.h"
#include "ThermalProbe.h"
#include <cassert>
#include <cstring>
#include <deque>
#include <map>
#include <vector>
#include <cstdio>
struct Bus {
 std::map<unsigned,unsigned> regs;std::deque<unsigned> rx;std::vector<unsigned> commands,writes;unsigned rejected=~0u;
 static unsigned read(void *v,unsigned off){auto &b=*static_cast<Bus *>(v);if(off==GENI_RX_FIFO_STATUS)return b.rx.size();if(off==GENI_RX_FIFO){assert(!b.rx.empty());unsigned n=b.rx.front();b.rx.pop_front();return n;}return b.regs[off];}
 static void write(void *v,unsigned off,unsigned n){auto &b=*static_cast<Bus *>(v);b.writes.push_back(off);if(off==b.rejected)return;b.regs[off]=n;if(off==GENI_M_CMD0)b.commands.push_back(n);if(off==GENI_M_IRQ_CLEAR)b.regs[GENI_M_IRQ_STATUS]&=~n;}
};
void testClocks(){
 const std::vector<unsigned> halts={0x23294,0x23284,0x2327c,0x23280,0x184e4};
 constexpr uint32_t otherVotes=(1u<<8)|(1u<<28),lateVote=1u<<29;
 // Only the injected locked update can access the shared vote. A vote from
 // another client arriving before that RMW must survive alongside SE6's vote.
 for(unsigned stop:{0u,0x23294u,0x23284u,0x2327cu,0x23280u,0x184e4u}) {
  unsigned failed=0xdead,delays=0,updates=0;uint32_t last=0xdead,votes=otherVotes;
  std::vector<unsigned> reads;
  auto read=[&](unsigned off){
   assert(updates==1);
   // A timed-out branch is the only one repeatedly read; later branches
   // (and all SE MMIO) must remain inaccessible after the first failure.
   reads.push_back(off);return (off==stop?1u<<31:0u)|0x1234u;
  };
  auto update=[&](unsigned off,uint32_t clear,uint32_t set){
   assert(reads.empty()&&off==0x52008&&clear==0&&set==0x043c0000);
   ++updates;votes|=lateVote;votes=(votes&~clear)|set;return true;
  };
  // Track each expected branch without letting repeated polls advance it.
  unsigned branch=0;
  auto poll=[&](unsigned off){
   assert(branch<halts.size()&&off==halts[branch]);
   const uint32_t value=read(off);if(off!=stop)++branch;return value;
  };
  bool ok=B5qTouchClock::enable(poll,update,[&](unsigned us){assert(us==10);++delays;},failed,last);
  assert(ok==!stop&&updates==1&&failed==stop&&delays==(stop?2000u:0u));
  assert(votes==(otherVotes|lateVote|0x043c0000)&&last==((stop?1u<<31:0u)|0x1234u));
  assert(reads.size()==(stop?branch+2000:halts.size()));
 }
 // Lock acquisition or vote readback failure must stop before any CBCR read.
 {
  unsigned failed=0,updates=0;uint32_t last=0xdead;
  auto update=[&](unsigned off,uint32_t clear,uint32_t set){assert(off==0x52008&&!clear&&set==0x043c0000);++updates;return false;};
  assert(!B5qTouchClock::enable([](unsigned)->uint32_t{assert(false);return 0;},update,
   [](unsigned){assert(false);},failed,last));
  assert(updates==1&&failed==0x52008&&last==0);
 }
 // Every branch can come up late; bounded polling must also accept it.
 {
  unsigned failed=0xdead,delays=0,branch=0,polls=0;uint32_t last=0xdead;
  auto read=[&](unsigned off){assert(branch<halts.size()&&off==halts[branch]);if(++polls<4)return 1u<<31;polls=0;++branch;return 0u;};
  assert(B5qTouchClock::enable(read,[](unsigned,uint32_t,uint32_t){return true;},
   [&](unsigned us){assert(us==10);++delays;},failed,last));
  assert(branch==halts.size()&&delays==15&&!failed&&!last);
 }
 // Every branch accepts CLK_OFF+HW_CTL immediately, including the exact v25
 // 0x23280=0x80000002 observation. Observe the production helper's log inputs.
 for(unsigned gated:halts){
  unsigned failed=0xdead,branch=0,observed=0;uint32_t last=0xdead;
  auto read=[&](unsigned off){assert(branch<halts.size()&&off==halts[branch++]);return off==gated?0x80000002u:0u;};
  assert(B5qTouchClock::enable(read,[](unsigned,uint32_t,uint32_t){return true;},
   [](unsigned){assert(false);},failed,last,[&](unsigned off,uint32_t value,bool accepted){
    assert(off==halts[observed++]&&accepted);assert(value==(off==gated?0x80000002u:0u));
   }));
  assert(branch==5&&observed==5&&!failed);
 }
 // Real XO helper: preserve all DFS bits, scan only SE4's table, choose each
 // possible first XO level (HID divider 0 or 1), reject an absent XO level.
 for(unsigned target=0;target<=8;++target)for(unsigned divider:{0u,1u}){
  constexpr uint32_t originalDfs=0xa5a50003u;
  unsigned reads=0,level=99;uint32_t dfsState=0,selected=0;
  auto read=[&](unsigned off){
   if(!reads++){assert(off==0x18504);return originalDfs;}
   const unsigned index=reads-2;assert(index<8&&off==0x1850c+4*index);
   return index>=target?0x80000000u|divider:index%2?0x102u:0x002u;
  };
  const bool ok=B5qTouchClock::xo(read,[](unsigned,uint32_t){assert(false);},
   [](unsigned){assert(false);},dfsState,level,selected);
  assert(ok==(target<8)&&dfsState==originalDfs&&level==target);
  assert(reads==(target<8?target+2:9)&&selected==(target<8?0x80000000u|divider:0u));
 }
 // Non-DFS alone updates CFG/CMD. Stuck UPDATE, rejected/changed CFG,
 // final-poll completion and immediate completion remain bounded failures.
 for(unsigned failure=0;failure<6;++failure){
  constexpr uint32_t initialCfg=0xfeed3300,initialCmd=0x102,dfsOther=0xa5a50002;
  std::map<unsigned,uint32_t> regs={{0x18504,dfsOther},{0x184f4,initialCfg},{0x184f0,initialCmd}};
  unsigned waits=0,level=99;uint32_t dfsState=0,selected=0;std::vector<unsigned> reads,writes;
  auto read=[&](unsigned off){assert(regs.count(off));reads.push_back(off);return regs.at(off);};
  auto write=[&](unsigned off,uint32_t v){
   assert(regs.count(off));writes.push_back(off);
   assert(off!=0x18504);
   if(off==0x184f4&&failure==2)return;
   regs.at(off)=v;if(off==0x184f0&&failure==5)regs.at(off)&=~1u;
  };
  auto wait=[&](unsigned us){
   assert(us==10);++waits;
   if(failure!=1&&(failure!=4||waits==1999)){
    regs.at(0x184f0)&=~1u;if(failure==3)regs.at(0x184f4)^=0x100;
   }
  };
  const bool ok=B5qTouchClock::xo(read,write,wait,dfsState,level,selected);
  assert(ok==(failure==0||failure>=4)&&dfsState==dfsOther&&level==(ok?0u:8u));
  const std::vector<unsigned> expected={0x184f4,0x184f0};
  assert(writes==expected&&regs.at(0x18504)==dfsOther);
  assert((regs.at(0x184f4)&~0x371fu)==(initialCfg&~0x371fu));
  assert((regs.at(0x184f0)&~1u)==initialCmd);
  assert(waits==(failure==1?2000u:failure==4?1999u:failure==5?0u:1u));
  if(failure==2)assert(regs.at(0x184f4)==initialCfg);
  else assert((regs.at(0x184f4)&0x371fu)==(failure==3?0x101u:1u));
 }
 puts("PASS production SE4 clock helper: locked votes/peer preservation/all branch timeouts/HW_CTL 80000002 skip/DFS levels0..7/no DFS writes/no-XO failure/nonDFS RCG faults/offset isolation");
}
int main(){
 {
  B5qTouchPointer::Pointer pointer;
  const int id[]={1,2},zero[]={0,0},move[]={2048,2048};
  assert(!pointer.update(1,id,zero,zero,1,250).click);
  assert(pointer.update(0,nullptr,nullptr,nullptr,10,250).click);
  pointer.update(1,id,zero,zero,20,250);
  assert(pointer.update(1,id,move,move,25,250).dx>0);
  assert(!pointer.update(0,nullptr,nullptr,nullptr,30,250).click);
  pointer.update(1,id,zero,zero,31,250);
  pointer.update(2,id,zero,zero,32,250);
  assert(!pointer.update(0,nullptr,nullptr,nullptr,33,250).click);
  pointer.update(1,id,zero,zero,34,250);
  assert(!pointer.update(0,nullptr,nullptr,nullptr,35,250,true).click);
 }
 using namespace B5qTouch;Point points[12]={};testClocks();
 uint32_t invalid[]={0,0,0};int32_t mc=THERMAL_NONE;assert(!thermal_pick_valid(invalid,3,&mc)&&mc==THERMAL_NONE);
 uint32_t valid[]={0,THERMAL_STATUS_VALID|310u,0};assert(thermal_pick_valid(valid,3,&mc)&&mc==31000);

 assert(hid(0)==0&&hid(4095)==32767&&hid(5000)==32767);
 uint8_t app[38]={};unsigned maximum=0;assert(!appInfo(app,37,maximum));app[36]=10;assert(appInfo(app,38,maximum)&&maximum==10);app[36]=13;assert(!appInfo(app,38,maximum));
 const uint8_t cfg[]={0x18,8,1,6,4,7,4,8,12,9,12,3,0};
 // 1 active object; index2/class1/x4095/y128, little-endian bit fields.
 const uint8_t payload[]={1,0x12,0xff,0x0f,0x08};
 assert(parse(cfg,sizeof cfg,payload,sizeof payload,points,10));assert(points[2].kind==1&&points[2].x==4095&&points[2].y==128);
 Point saved[12];memcpy(saved,points,sizeof saved);assert(!parse(cfg,sizeof cfg,payload,4,points,10));assert(!memcmp(saved,points,sizeof saved));
 const uint8_t zero[]={0};assert(parse(cfg,sizeof cfg,zero,1,points,10));for(auto &p:points)assert(!p.kind);
 const uint8_t all[]={2,7,8,3,0};uint8_t ten[10]={1};assert(parse(all,sizeof all,ten,10,points,10));assert(!parse(all,sizeof all,ten,9,points,10));
 const uint8_t noCount[]={1,6,4,7,4,8,12,9,12,3,0};assert(parse(noCount,sizeof noCount,payload+1,4,points,10));
 uint8_t secPacket[32]={};secPacket[0]=0x40|8;secPacket[1]=0xff;secPacket[2]=8;secPacket[3]=0xf0;
 assert(sec(secPacket,16,points)&&points[2].kind==1&&points[2].x==4095&&points[2].y==128);
 secPacket[0]=0x80|8;secPacket[1]=1;assert(sec(secPacket,16,points)&&points[2].x==31);
 secPacket[16]=0x40|60;memcpy(saved,points,sizeof saved);
 assert(sec(secPacket,32,points)&&!memcmp(saved,points,sizeof saved));
 secPacket[6]=0xc0;assert(sec(secPacket,16,points)&&points[2].x==31);
 secPacket[0]=0xc0|8|3;assert(sec(secPacket,16,points)&&!points[2].kind);
 for(unsigned length:{1u,255u,256u,257u,511u,4096u}){
  std::vector<uint8_t> out(length),expected(length);for(unsigned i=0;i<length;++i)expected[i]=i;
  unsigned at=0;auto read=[&](uint8_t *p,unsigned n){p[0]=0xa5;p[1]=3;for(unsigned i=2;i<n;++i)p[i]=at<length?expected[at++]:0x5a;return true;};
  assert(continuation(read,out.data(),length)&&out==expected);
  assert(!continuation([](uint8_t *p,unsigned){p[0]=0;p[1]=3;return true;},out.data(),length));
 }
 // Bounded malformed configurations, including byte widths equal to END_LOOP.
 unsigned state=1;uint8_t fuzzCfg[64],fuzzData[64];
 for(unsigned round=0;round<20000;++round){for(auto &v:fuzzCfg){state=state*1664525+1013904223;v=state>>24;}for(auto &v:fuzzData){state=state*1664525+1013904223;v=state>>24;}parse(fuzzCfg,round%64+1,fuzzData,(round/64)%64,points,10);}
 Bus b;b.regs={{GENI_FW_REVISION,3u<<8},{GENI_CLK_CFG,1},{GENI_SCL_COUNTERS,1}};GeniIo io={Bus::read,Bus::write,&b};GeniI2c bus;uint32_t proto=0;
 assert(!geni_i2c_prepare(&bus,&io,0x20,&proto));uint8_t bytes[4]={};assert(!geni_i2c_start_read_only(&bus,bytes,4));assert(b.commands.size()==1&&b.commands[0]>>27==GENI_OP_READ);b.rx.push_back(0x04030201);b.regs[GENI_M_IRQ_STATUS]=GENI_M_RX_LAST|GENI_M_CMD_DONE;
 assert(geni_i2c_poll(&bus)==GeniDone&&bytes[0]==1&&bytes[3]==4);
 assert(!geni_i2c_start_read_only(&bus,bytes,4));assert(geni_i2c_event(&bus,GENI_M_CMD_DONE|(1u<<9))==GeniFailed&&bus.error==GeniErrBus);
 assert(!geni_i2c_start_read_only(&bus,bytes,4));assert(geni_i2c_timeout(&bus)==GeniPending);assert(geni_i2c_timeout(&bus)==GeniPending);assert(geni_i2c_timeout(&bus)==GeniFailed&&bus.phase==GeniIdle);
 for(unsigned cmd:b.commands)assert(cmd>>27==GENI_OP_READ);
 for(unsigned failure=0;failure<4;++failure){
  Bus cold;cold.regs[GENI_FW_REVISION]=(failure==1?2u:3u)<<8;
  cold.regs[GENI_IF_DISABLE]=failure==2;cold.regs[GENI_STATUS]=failure==3;
  const GeniIo cio={Bus::read,Bus::write,&cold};
  assert(geni_i2c_prepare(&bus,&cio,0x20,&proto)==-1&&cold.writes.empty());
  assert(geni_i2c_prepare_xo(&bus,&cio,0x20,&proto)==(failure?-1:0));
  if(failure)assert(cold.writes.empty());
  else {
   assert(cold.writes[0]==GENI_SCL_COUNTERS&&cold.writes[1]==GENI_CLK_CFG);
   assert(cold.regs[0x278]==0x702818&&cold.regs[0x48]==0x21&&proto==0x03000021);
   for(auto off:cold.writes)assert(off!=GENI_IF_DISABLE&&off!=0x28);
  }
 }
 // Actual shared cold-init and XO preparation preserve caller-selected DFS
 // levels across all eight choices, without issuing commands or enabling DMA.
 for(unsigned level=0;level<8;++level){
  Bus cold;cold.regs={{GENI_FW_REVISION,3u<<8},{GENI_CLK_SEL,~0u},{GENI_CGC_CTRL,0x800},{GENI_DMA_GENERAL_CFG,0x400},{GENI_SE_IRQ_EN,0x100},{GENI_GSI_EVENT_EN,15}};
  const GeniIo cio={Bus::read,Bus::write,&cold};
  assert(!geni_se_init(&cio));
  assert((cold.writes==std::vector<unsigned>{0x28,0xe30,0x24,0x20,0xe18,0xe1c}));
  assert(cold.regs[0x28]==0x87f&&cold.regs[0xe30]==0x40f&&cold.regs[0x24]==0x7f&&cold.regs[0x20]==1&&cold.regs[0xe18]==0&&cold.regs[0xe1c]==0x10c);
  cold.writes.clear();uint32_t readback=0;
  assert(B5qTouchClock::selectLevel([&](unsigned off){return cio.read(cio.ctx,off);},[&](unsigned off,uint32_t value){cio.write(cio.ctx,off,value);},level,readback));
  assert(readback==level&&(cold.writes==std::vector<unsigned>{GENI_CLK_SEL}));cold.writes.clear();
  assert(!geni_i2c_prepare_xo(&bus,&cio,0x20,&proto)&&cold.regs[GENI_CLK_SEL]==level&&cold.regs[GENI_DMA_MODE]==0);
  assert(cold.commands.empty());for(unsigned off:cold.writes)assert(off!=GENI_CLK_SEL);
 }
 // Level selection rejects an invalid index before MMIO and stops on failed
 // readback, using the same helper called by the touch worker.
 for(unsigned invalid:{8u,9u,~0u}){
  uint32_t readback=0;
  assert(!B5qTouchClock::selectLevel([](unsigned)->uint32_t{assert(false);return 0;},[](unsigned,uint32_t){assert(false);},invalid,readback));
  assert(readback==~0u);
 }
 for(unsigned level=0;level<8;++level){
  unsigned reads=0,writes=0;uint32_t readback=0;
  assert(!B5qTouchClock::selectLevel([&](unsigned off){assert(off==GENI_CLK_SEL);++reads;return 8u;},[&](unsigned off,uint32_t value){assert(off==GENI_CLK_SEL&&value==level);++writes;},level,readback));
  assert(reads==1&&writes==1&&readback==8);
 }
 for(unsigned failure=0;failure<3;++failure){
  Bus cold;cold.regs={{GENI_FW_REVISION,(failure==0?2u:3u)<<8},{GENI_IF_DISABLE,unsigned(failure==1)},{GENI_STATUS,unsigned(failure==2)}};
  const GeniIo cio={Bus::read,Bus::write,&cold};assert(geni_se_init(&cio)==-1&&cold.writes.empty());
 }
 assert(geni_se_init(nullptr)==-1);
 for(unsigned capability:{1u,2u,3u,0x80000000u,~0u}){
  Bus cold;cold.regs={{GENI_FW_REVISION,3u<<8},{GENI_IF_DISABLE,capability}};
  const GeniIo cio={Bus::read,Bus::write,&cold};
  assert(geni_se_init(&cio)==-1&&cold.writes.empty());
  assert(geni_i2c_prepare_xo(&bus,&cio,0x20,&proto)==-1&&cold.writes.empty());
 }
 for(unsigned fault:{GENI_SCL_COUNTERS,GENI_CLK_CFG}){
  Bus cold;cold.regs={{GENI_FW_REVISION,3u<<8},{GENI_CLK_SEL,7}};cold.rejected=fault;
  const GeniIo cio={Bus::read,Bus::write,&cold};
  assert(geni_i2c_prepare_xo(&bus,&cio,0x20,&proto)==-1&&cold.regs[GENI_CLK_SEL]==7&&cold.commands.empty());
  assert((cold.writes==std::vector<unsigned>{GENI_SCL_COUNTERS,GENI_CLK_CFG}));
 }
 puts("PASS shared GENI production cold-init: six exact writes/preserved RMW bits/FIFO routing/levels0..7 preserved/rejected protocol-active-disabled with no writes/timing readback faults");
 puts("PASS actual TouchComm app-info/config/delta/framing/truncation/fuzz and GENI read-only/NACK/bounded-timeout paths");
}
