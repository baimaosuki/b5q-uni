#include "B5qTouchReports.h"
#include "B5qTouchMouse.h"
#include <array>
#include <vector>
#include <cassert>
#include <cstdio>
#include <cstring>
#include <climits>
using namespace B5qTouch;
static void event(uint8_t *p,unsigned id,unsigned action,unsigned type,unsigned x=100,unsigned y=200) {
 memset(p,0,16);p[0]=uint8_t((action<<6)|(id<<2));p[1]=x>>4;p[2]=y>>4;
 p[3]=uint8_t((x<<4)|(y&15));p[6]=uint8_t((type>>2)<<6);p[7]=uint8_t((type&3)<<6);
}
static unsigned contacts(const Reports &s) {unsigned n=0;for(auto p:s.points)n+=p.kind!=0;return n;}
static void reports() {
 const uint8_t cfg[]={0x18,8,1,6,4,7,4,8,12,9,12,3,0};
 const uint8_t full[]={1,0x12,0xff,0x0f,0x08},zero[]={0};
 uint8_t p[160]={};Reports s;s.mode=0x11;
 assert(s.consume(0x11,full,sizeof full,cfg,sizeof cfg,10)==ReportResult::Frame);
 assert(contacts(s)==1&&s.points[2].x==4095);
 assert(s.consume(0x11,zero,1,cfg,sizeof cfg,10)==ReportResult::Frame&&!contacts(s));
 // Full-frame failure is atomic at the parser, then the owner releases all.
 s.points[11]={1,1,1};assert(s.consume(0x11,full,4,cfg,sizeof cfg,10)==ReportResult::Released&&!contacts(s));
 s.mode=0xc1;
 for(unsigned type=0;type<16;++type) {
  event(p,2,1,0);assert(s.consume(0xc1,p,16,nullptr,0,10)==ReportResult::Frame&&contacts(s)==1);
  event(p,2,2,type);assert(s.consume(0xc1,p,16,nullptr,0,10)==ReportResult::Frame);
  assert(contacts(s)==unsigned(type==0||type==3||type==6));
 }
 assert(s.palm==1&&s.invalid==12);
 // All ten wire IDs; release one delta without clearing the other nine.
 for(unsigned id=0;id<10;++id)event(p+16*id,id,1,0,id*100,id*80);
 assert(s.consume(0xc1,p,sizeof p,nullptr,0,10)==ReportResult::Frame&&contacts(s)==10);
 event(p,3,3,0);s.consume(0xc1,p,16,nullptr,0,10);assert(contacts(s)==9&&!s.points[3].kind);
 event(p,2,0,0);s.consume(0xc1,p,16,nullptr,0,10);assert(contacts(s)==8&&!s.points[2].kind);
 for(unsigned code:{0xc2u,0x10u,2u,3u,4u,0xffu}) {
  for(auto &v:s.points)v={100,200,1};
  assert(s.consume(code,p,16,nullptr,0,10)==ReportResult::Released&&!contacts(s));
 }
 assert(s.c2==1&&s.identify==1&&s.reconfigure);
 for(unsigned i=0;i<5;++i){s.points[11]={1,2,1};assert(s.error()==ReportResult::Released&&!contacts(s));}
 for(unsigned id=10;id<16;++id){event(p,id,1,0);s.points[1]={1,1,1};assert(s.consume(0xc1,p,16,nullptr,0,10)==ReportResult::Released&&!contacts(s));}
 for(unsigned n:{0u,1u,15u,17u,4097u}){s.points[0]={1,1,1};assert(s.consume(0xc1,p,n,nullptr,0,10)==ReportResult::Released&&!contacts(s));}
 for(unsigned code:{0u,1u,7u,0x12u})assert(s.consume(code,p,16,nullptr,0,10)==ReportResult::Ignore);
 puts("PASS P0 production reports: full-frame atomic replacement,16types,palm/invalidslotrelease,10IDs,12slotreset,C2/Identify/status/I2C/malformed/unknown");
}
using Packet=std::array<uint8_t,8>;
static void pointer() {
 B5qTouchMouse s;std::vector<Packet> sent;
 auto send=[&](const uint8_t *r){Packet p;memcpy(p.data(),r,8);sent.push_back(p);assert(p[0]==0x1a);};
 int ids[]={1,2,3,4,5,6,7,8,9,10},x[]={8000,16000,24000,100,200,300,400,500,600,700},y[]={8000,16000,24000,100,200,300,400,500,600,700};
 s.update(1,ids,x,y,1,false,send);assert(sent.empty());
 s.update(0,nullptr,nullptr,nullptr,20,false,send);assert(sent.size()==2&&sent[0][1]==1&&!sent[1][1]);
 s.update(1,ids,x,y,45,false,send);s.update(0,nullptr,nullptr,nullptr,65,false,send);
 assert(sent.size()==4&&sent[2][1]==1&&!sent[3][1]); // native double-click pair
 sent.clear();s.update(1,ids,x,y,100,false,send);x[0]+=1000;y[0]+=1000;
 s.update(1,ids,x,y,113,false,send);assert(sent.size()==1&&int16_t(sent.back()[2]|sent.back()[3]<<8)>0&&int16_t(sent.back()[4]|sent.back()[5]<<8)>0);
 s.update(0,nullptr,nullptr,nullptr,126,false,send);assert(sent.size()==1);
 // Contact identity and timeout rebases. Next regular frame still moves.
 s.update(1,ids,x,y,140,false,send);x[0]+=5000;s.update(1,ids,x,y,210,false,send);assert(sent.size()==1&&s.pointer.restarts==1);
 x[0]+=500;s.update(1,ids,x,y,223,false,send);assert(sent.size()==2);
 int replacement[]={9};x[0]+=5000;s.update(1,replacement,x,y,236,false,send);assert(sent.size()==2);
 x[0]+=500;s.update(1,replacement,x,y,249,false,send);assert(sent.size()==3);
 // A third finger never creates a permanent suppressed state; four through
 // ten temporarily release and a returning single finger resumes immediately.
 for(unsigned count=3;count<=10;++count) {
  s.update(count,ids,x,y,300+count*100,false,send);
  const auto before=sent.size();s.update(1,ids,x,y,313+count*100,false,send);
  x[0]+=600;s.update(1,ids,x,y,326+count*100,false,send);assert(sent.size()>before);
 }
 s.update(0,nullptr,nullptr,nullptr,1400,true,send);assert(!sent.back()[1]&&!s.pointer.fingers&&!s.tapping);
 sent.clear();s.update(2,ids,x,y,1500,false,send);s.update(0,nullptr,nullptr,nullptr,1520,false,send);
 assert(sent.size()==2&&sent[0][1]==2&&!sent[1][1]);
 sent.clear();s.update(2,ids,x,y,1600,false,send);x[0]+=1000;x[1]+=1000;y[0]+=1000;y[1]+=1000;
 s.update(2,ids,x,y,1613,false,send);assert(sent.size()==1&&int8_t(sent[0][6])<0&&int8_t(sent[0][7])>0);
 s.update(0,nullptr,nullptr,nullptr,1626,false,send);assert(sent.size()==1);
 // Two-finger set can change ordering without a jump or false click.
 s={};sent.clear();s.update(2,ids,x,y,1700,false,send);
 int flipIds[]={2,1},flipX[]={x[1],x[0]},flipY[]={y[1],y[0]};
 s.update(2,flipIds,flipX,flipY,1713,false,send);assert(sent.empty());
 s.update(0,nullptr,nullptr,nullptr,1726,false,send);assert(sent.size()==2&&sent[0][1]==2);
 // Bounded input sanitation and unsigned clock wrap.
 s.update(11,nullptr,nullptr,nullptr,1800,false,send);assert(!sent.back()[1]);
 s.update(1,nullptr,nullptr,nullptr,1810,false,send);assert(!sent.back()[1]);
 int extreme[]={INT_MIN,INT_MAX};s.update(2,ids,extreme,extreme,1820,false,send);
 s.update(0,nullptr,nullptr,nullptr,1830,true,send);
 s.update(1,ids,x,y,UINT_MAX-10,false,send);s.update(0,nullptr,nullptr,nullptr,10,false,send);assert(sent[sent.size()-2][1]==1&&!sent.back()[1]);
 puts("PASS upstream pointer adapter:tap/doubletap/righttap/scroll/3..10contacts/rebase/identity/order/timeout/recovery/bounds/timewrap");
}
int main(){reports();pointer();}
