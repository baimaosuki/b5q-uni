#include "B5qTouchProtocol.h"
#include "GeniI2c.h"
#include <cassert>
#include <cstring>
#include <deque>
#include <map>
#include <vector>
#include <cstdio>
struct Bus {
 std::map<unsigned,unsigned> regs;std::deque<unsigned> rx;std::vector<unsigned> commands;
 static unsigned read(void *v,unsigned off){auto &b=*static_cast<Bus *>(v);if(off==GENI_RX_FIFO_STATUS)return b.rx.size();if(off==GENI_RX_FIFO){assert(!b.rx.empty());unsigned n=b.rx.front();b.rx.pop_front();return n;}return b.regs[off];}
 static void write(void *v,unsigned off,unsigned n){auto &b=*static_cast<Bus *>(v);b.regs[off]=n;if(off==GENI_M_CMD0)b.commands.push_back(n);if(off==GENI_M_IRQ_CLEAR)b.regs[GENI_M_IRQ_STATUS]&=~n;}
};
int main(){
 using namespace B5qTouch;Point points[12]={};
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
 puts("PASS actual TouchComm app-info/config/delta/framing/truncation/fuzz and GENI read-only/NACK/bounded-timeout paths");
}
