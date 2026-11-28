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
// Feed controller counts through the real producer's normalised32767 domain.
static int norm(int v){return (v*32767+4094)/4095;}
static void pointer() {
 B5qTouchMouse s;std::vector<Packet> sent;uint32_t now=0;
 auto send=[&](const uint8_t*r){Packet p;memcpy(p.data(),r,8);sent.push_back(p);assert(p[0]==0x1a&&p[1]==s.held);};
 int ids[]={1,2,3,4,5,6,7,8,9,10},x[]={norm(1000),norm(2000),norm(3000)},y[]={norm(1000),norm(2000),norm(3000)};
 // Required1: real human centroid jitter freezes all movement; exact32ms pulse.
 s.update(1,ids,x,y,10,false,send);x[0]=norm(1100);y[0]=norm(960);
 s.update(1,ids,x,y,70,false,send);assert(sent.empty());
 now=90;s.update(0,nullptr,nullptr,nullptr,now,false,send);assert(sent.size()==1&&sent[0][1]==1);
 for(unsigned i=2;i<8;i++)assert(sent[0][i]==0);
 s.advance(121,send);assert(sent.size()==1);s.advance(122,send);assert(sent.size()==2&&!sent[1][1]);
 // Required2+4: new contact emits no duplicateup; second lift is anotherclick.
 s.update(1,ids,x,y,210,false,send);assert(sent.size()==2&&!s.held);
 s.update(0,nullptr,nullptr,nullptr,250,false,send);s.advance(282,send);
 assert(sent.size()==4&&sent[2][1]==1&&!sent[3][1]&&s.clicks_left==2);
 // Crossing the widened slop anchors; next61X/26Y raw counts ->12/13.
 s={};sent.clear();x[0]=y[0]=norm(1000);s.update(1,ids,x,y,300,false,send);
 x[0]=norm(1300);y[0]=norm(1160);s.update(1,ids,x,y,320,false,send);assert(sent.empty()&&s.mode==B5qTouchMouse::Moving);
 x[0]=norm(1361);y[0]=norm(1186);s.update(1,ids,x,y,340,false,send);
 assert(sent.size()==1&&int16_t(sent[0][2]|sent[0][3]<<8)==12&&int16_t(sent[0][4]|sent[0][5]<<8)==13&&!sent[0][1]);
 s.update(0,nullptr,nullptr,nullptr,360,false,send);assert(sent.size()==1&&!s.clicks_left&&s.taps_cancelled_slop==1);
 // Slow stationaryframe gap does not cancel within300ms. Time crossinganchors.
 s={};sent.clear();s.update(1,ids,x,y,400,false,send);s.update(1,ids,x,y,580,false,send);assert(s.mode==B5qTouchMouse::CandidateTap);
 s.update(1,ids,x,y,701,false,send);assert(sent.empty()&&s.taps_cancelled_time==1);
 s.update(1,ids,x,y,702,false,send);assert(sent.empty());
 // Remainders retain subcount precision in both directions.
 for(unsigned i=1;i<=10;i++){x[0]=norm(1361+int(i));y[0]=norm(1186+int(i));s.update(1,ids,x,y,702+i,false,send);}
 int dx=0,dy=0;for(auto &r:sent){dx+=int16_t(r[2]|r[3]<<8);dy+=int16_t(r[4]|r[5]<<8);}assert(dx==2&&dy==5);
 for(unsigned i=1;i<=10;i++){x[0]=norm(1371-int(i));y[0]=norm(1196-int(i));s.update(1,ids,x,y,720+i,false,send);}
 dx=dy=0;for(auto &r:sent){dx+=int16_t(r[2]|r[3]<<8);dy+=int16_t(r[4]|r[5]<<8);}assert(dx==0&&dy==0);
 // Contact replacement reanchors, no phantomtap; >2contacts recoverto movement.
 int other=9;s.update(1,&other,x,y,740,false,send);auto before=sent.size();
 x[0]+=norm(100);s.update(1,&other,x,y,750,false,send);assert(sent.size()==before+1);
 for(unsigned n=3;n<=10;n++){s.update(n,ids,x,y,800+n*100,false,send);before=sent.size();s.update(1,ids,x,y,813+n*100,false,send);x[0]+=100;s.update(1,ids,x,y,826+n*100,false,send);assert(sent.size()>before);}
 s.cancel(send);assert(!s.timeout(2000)&&!s.held&&!s.fingers);
 // Both staggeredrighttap liftorders preserve tapCount; identityreorder benign.
 for(unsigned last=0;last<2;last++){
  s={};sent.clear();s.update(2,ids,x,y,2000,false,send);s.update(1,ids+last,x+last,y+last,2010,false,send);
  assert(s.mode==B5qTouchMouse::CandidateTap&&s.tapCount==2&&s.tapRemaining==1&&sent.empty());
  s.update(0,nullptr,nullptr,nullptr,2020,false,send);s.advance(2052,send);assert(sent.size()==2&&sent[0][1]==2&&!sent[1][1]);
 }
 for(unsigned failure=0;failure<5;failure++){
  s={};sent.clear();s.update(2,ids,x,y,2100,false,send);int oneId=ids[0],oneX=x[0],oneY=y[0];
  if(failure==0)oneId=9;if(failure==2)oneX+=norm(300);
  s.update(1,&oneId,&oneX,&oneY,2110,false,send);if(failure==1)s.update(2,ids,x,y,2120,false,send);
  s.update(0,nullptr,nullptr,nullptr,failure==3?2500:2130,failure==4,send);for(auto&r:sent)assert(!(r[1]&2));
 }
 // Scrollonlyafter slopand nojump; IDorderchanges cannot create motion.
 s={};sent.clear();x[0]=x[1]=y[0]=y[1]=norm(1000);s.update(2,ids,x,y,2600,false,send);
 x[0]=x[1]=norm(1300);y[0]=y[1]=norm(1200);s.update(2,ids,x,y,2610,false,send);assert(sent.empty());
 x[0]=x[1]=norm(1400);y[0]=y[1]=norm(1240);s.update(2,ids,x,y,2620,false,send);assert(sent.size()==1&&int8_t(sent[0][6])==-1&&int8_t(sent[0][7])==1);
 int flip[]={2,1};s.update(2,flip,x,y,2630,false,send);assert(sent.size()==1);s.update(0,nullptr,nullptr,nullptr,2640,false,send);assert(sent.size()==1);
 // Expanded slop tolerates realistic finger-roll on both phone axes.
 s={};sent.clear();x[0]=y[0]=norm(1000);s.update(1,ids,x,y,2700,false,send);
 x[0]=norm(1220);y[0]=norm(1115);s.update(1,ids,x,y,2740,false,send);
 assert(s.mode==B5qTouchMouse::CandidateTap&&sent.empty());
 s.update(0,nullptr,nullptr,nullptr,2780,false,send);assert(s.held==1);s.advance(2812,send);assert(!s.held);
 // Discontinuities re-anchor and erase both fractional remainders; a normal
 // next frame uses the new anchor, never the pre-jump coordinates.
 for(unsigned cause=0;cause<3;cause++){
  s={};sent.clear();x[0]=y[0]=norm(1000);s.update(1,ids,x,y,3000,false,send);
  x[0]=norm(1300);s.update(1,ids,x,y,3010,false,send);assert(s.mode==B5qTouchMouse::Moving);
  x[0]=norm(1301);y[0]=norm(1001);s.update(1,ids,x,y,3020,false,send);assert(s.remainderX&&s.remainderY);
  const unsigned beforeJump=sent.size();
  if(cause==0)x[0]=norm(2000);if(cause==1)y[0]=norm(1500);if(cause==2){x[0]=norm(1350);y[0]=norm(1020);}
  const uint32_t t=cause==2?3101:3030;s.update(1,ids,x,y,t,false,send);
  assert(sent.size()==beforeJump&&!s.remainderX&&!s.remainderY);
  const int ax=s.anchorX,ay=s.anchorY;x[0]=norm(ax+5);y[0]=norm(ay+2);s.update(1,ids,x,y,t+10,false,send);
  assert(sent.size()==beforeJump+1&&int16_t(sent.back()[2]|sent.back()[3]<<8)==1&&int16_t(sent.back()[4]|sent.back()[5]<<8)==1);
 }
 // Largest allowed same-frame deltas are clamped without delayed overflow.
 s={};sent.clear();x[0]=y[0]=norm(1000);s.update(1,ids,x,y,4000,false,send);
 x[0]=norm(1300);s.update(1,ids,x,y,4010,false,send);
 x[0]=norm(1780);y[0]=norm(1260);s.update(1,ids,x,y,4020,false,send);
 assert(sent.size()==1&&int16_t(sent[0][2]|sent[0][3]<<8)==64&&int16_t(sent[0][4]|sent[0][5]<<8)==64);
 s.update(1,ids,x,y,4030,false,send);assert(sent.size()==1);
 x[0]=norm(1300);y[0]=norm(1000);s.update(1,ids,x,y,4040,false,send);
 assert(int16_t(sent.back()[2]|sent.back()[3]<<8)==-64&&int16_t(sent.back()[4]|sent.back()[5]<<8)==-64);
 // Bounds, malformedinput, recoveryrelease, queuedclicks andunsignedclockwrap.
 for(uint32_t start:{100u,UINT_MAX-50u}){
  s={};sent.clear();s.update(1,ids,x,y,start,false,send);s.update(0,nullptr,nullptr,nullptr,start+10,false,send);
  assert(sent.size()==1&&s.held);s.update(1,ids,x,y,start+11,false,send);s.update(0,nullptr,nullptr,nullptr,start+12,false,send);
  assert(s.queueCount==1);s.advance(start+42,send);assert(sent.size()==2&&!s.held);s.advance(start+49,send);assert(sent.size()==2);s.advance(start+50,send);assert(sent.size()==3&&s.held);s.advance(start+82,send);assert(sent.size()==4&&!s.held);
 }
 s.update(1,ids,x,y,100,false,send);s.update(0,nullptr,nullptr,nullptr,110,false,send);assert(s.held);
 s.update(0,nullptr,nullptr,nullptr,111,true,send);assert(!s.held&&!s.timeout(111));
 s.update(11,nullptr,nullptr,nullptr,120,false,send);s.update(1,nullptr,nullptr,nullptr,130,false,send);
 int extreme[]={INT_MIN,INT_MAX};s.update(2,ids,extreme,extreme,140,false,send);s.cancel(send);
 int duplicate[]={1,1};s.update(2,duplicate,x,y,150,false,send);assert(!s.fingers);
 puts("PASS P0touch:4requestedcases,32msclicks,physicalXY12/13,no-doubletapdrag/no-extra-up,remainder+/-,identity,3..10contacts,staggeredrighttap,scrollfreeze,recovery,bounds,queuedpulses,timewrap");
}
int main(){reports();pointer();}
