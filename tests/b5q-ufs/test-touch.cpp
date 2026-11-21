#include "B5qTouchProtocol.h"
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
 std::map<unsigned,unsigned> regs;std::deque<unsigned> rx;std::vector<unsigned> commands,writes;
 static unsigned read(void *v,unsigned off){auto &b=*static_cast<Bus *>(v);if(off==GENI_RX_FIFO_STATUS)return b.rx.size();if(off==GENI_RX_FIFO){assert(!b.rx.empty());unsigned n=b.rx.front();b.rx.pop_front();return n;}return b.regs[off];}
 static void write(void *v,unsigned off,unsigned n){auto &b=*static_cast<Bus *>(v);b.writes.push_back(off);b.regs[off]=n;if(off==GENI_M_CMD0)b.commands.push_back(n);if(off==GENI_M_IRQ_CLEAR)b.regs[GENI_M_IRQ_STATUS]&=~n;}
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
 // Real XO helper: sticky DFS, stuck UPDATE, rejected/changed CFG, already
 // disabled DFS, final-poll completion, and immediate completion. All accesses
 // are confined to Samsung SE4, leaving SE6 and M/N/D registers untouched.
 for(unsigned failure=0;failure<8;++failure){
  constexpr uint32_t initialCfg=0xfeed3300,initialCmd=0x102,dfsOther=0xa5a50002;
  const bool dfsEnabled=failure!=5;
  std::map<unsigned,uint32_t> regs={{0x18504,dfsOther|unsigned(dfsEnabled)},{0x184f4,initialCfg},{0x184f0,initialCmd}};
  unsigned waits=0;std::vector<unsigned> reads,writes;
  auto read=[&](unsigned off){assert(regs.count(off));reads.push_back(off);return regs.at(off);};
  auto write=[&](unsigned off,uint32_t v){
   assert(regs.count(off));writes.push_back(off);
   if((off==0x18504&&failure==1)||(off==0x184f4&&failure==3))return;
   regs.at(off)=v;if(off==0x184f0&&failure==7)regs.at(off)&=~1u;
  };
  auto wait=[&](unsigned us){
   assert(us==10);++waits;
   if(failure!=2&&(failure!=6||waits==1999)){
    regs.at(0x184f0)&=~1u;if(failure==4)regs.at(0x184f4)^=0x100;
   }
  };
  assert(B5qTouchClock::xo(read,write,wait)==(failure==0||failure>=5));
  if(failure==1){
   assert((writes==std::vector<unsigned>{0x18504})&&(reads==std::vector<unsigned>{0x18504,0x18504})&&!waits);
   assert(regs.at(0x184f4)==initialCfg&&regs.at(0x184f0)==initialCmd);continue;
  }
  const std::vector<unsigned> expected=dfsEnabled?std::vector<unsigned>{0x18504,0x184f4,0x184f0}:std::vector<unsigned>{0x184f4,0x184f0};
  assert(writes==expected&&regs.at(0x18504)==dfsOther);
  assert((regs.at(0x184f4)&~0x371fu)==(initialCfg&~0x371fu));
  assert((regs.at(0x184f0)&~1u)==initialCmd);
  assert(waits==(failure==2?2000u:failure==6?1999u:failure==7?0u:1u));
  if(failure==3)assert(regs.at(0x184f4)==initialCfg);
  else assert((regs.at(0x184f4)&0x371fu)==(failure==4?0x101u:1u));
 }
 puts("PASS production SE4 clock helper: locked shared vote/preserved peer votes/early failure/all branch timeouts/delayed enable/DFS and RCG faults/offset isolation");
}
int main(){
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
 secPacket[16]=0x40|60;memcpy(saved,points,sizeof saved);assert(!sec(secPacket,32,points)&&!memcmp(saved,points,sizeof saved));
 secPacket[0]=0xc0|8;assert(sec(secPacket,16,points)&&!points[2].kind);
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
   assert(cold.writes[0]==GENI_CLK_SEL&&cold.writes[1]==GENI_SCL_COUNTERS&&cold.writes[2]==GENI_CLK_CFG);
   assert(cold.regs[0x278]==0x702818&&cold.regs[0x48]==0x21&&proto==0x03000021);
   for(auto off:cold.writes)assert(off!=GENI_IF_DISABLE&&off!=0x28);
  }
 }
 puts("PASS actual TouchComm app-info/config/delta/framing/truncation/fuzz and GENI read-only/NACK/bounded-timeout paths");
}
