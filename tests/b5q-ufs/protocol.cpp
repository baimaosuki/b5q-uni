#include "B5qUfsProtocol.h"
#include <assert.h>
#include <string.h>
#include <stdio.h>
#include <vector>
using namespace B5qUfsProtocol;
struct Packet { alignas(8) uint32_t utrd[8]={};alignas(8) uint8_t ucd[2048]={}; };
static void check(uint8_t *rsp,unsigned lun,unsigned expected,unsigned key,unsigned asc,unsigned ascq,bool descriptor=false) {
 memset(rsp,0,512);rsp[0]=0x21;rsp[1]=expected?0x20:0;rsp[2]=lun;rsp[7]=2;putBe32(rsp+12,expected);
 rsp[11]=descriptor?6:20;rsp[33]=descriptor?4:18;uint8_t *sense=rsp+34;
 if(descriptor){sense[0]=0x72;sense[1]=key;sense[2]=asc;sense[3]=ascq;}
 else {sense[0]=0x70;sense[2]=key;sense[7]=10;sense[12]=asc;sense[13]=ascq;}
}
struct Device {
 bool poisoned=false,nopFail=false,queryFail=false,stillAsleep=false,alreadyActive=false,wakeAttention=false;
 unsigned queries=0,wakes=0,turs=0,pauses=0,readyAfter=1;std::vector<unsigned> order;
 bool nop(){order.push_back(1);return !nopFail;}
 bool query(uint32_t &power){order.push_back(2);++queries;if(queryFail)return false;power=(alreadyActive||wakes)&&!stillAsleep?0x11:0x33;return true;}
 int scsi(uint8_t lun,const uint8_t cdb[16],uint32_t bytes,Status &status){
  assert(!poisoned);Packet p;assert(command(p.utrd,p.ucd,0x8ce326000ULL,lun,cdb,bytes));assert(bytes==0);
  assert(p.utrd[0]==0x10000000&&p.utrd[7]==0x01000000&&p.ucd[1]==0&&be32(p.ucd+12)==0);
  uint8_t rsp[512]={};rsp[0]=0x21;rsp[2]=lun;
  if(lun==0xd0){order.push_back(3);++wakes;assert(cdb[0]==0x1b&&cdb[4]==0x10);if(wakeAttention&&wakes==1)check(rsp,lun,0,6,0x29,0);}
  else {order.push_back(4);assert(lun==0&&cdb[0]==0);++turs;if(turs<readyAfter)check(rsp,lun,0,6,0x29,0);}
  bool valid=response(rsp,0,lun,bytes,status);if(!valid){poisoned=true;return -1;}return status.scsi?status.scsi:status.exact?0:-2;
 }
 auto no(){return [&]{return nop();};}auto q(){return [&](uint32_t &p){return query(p);};}
 auto c(){return [&](uint8_t l,const uint8_t *c,uint32_t n,Status &s){return scsi(l,c,n,s);};}
 auto wait(){return [&](unsigned n){assert(n==10||n==50);pauses+=n;};}auto healthy(){return [&]{return !poisoned;};}
};
int main(){
 Packet p;uint8_t cap[16]={0x9e,0x10};putBe32(cap+10,32);
 assert(command(p.utrd,p.ucd,0x8ce326000ULL,0,cap,32));
 assert(p.utrd[0]==0x14000000&&p.utrd[2]==15&&p.utrd[4]==0xce327000&&p.utrd[5]==8&&p.utrd[6]==0x00800080&&p.utrd[7]==0x01000001);
 assert(p.ucd[0]==1&&p.ucd[1]==0x40&&be32(p.ucd+12)==32&&memcmp(p.ucd+16,cap,16)==0);
 uint32_t *prd=reinterpret_cast<uint32_t*>(p.ucd+1024);assert(prd[0]==0xce328000&&prd[1]==8&&prd[3]==31);
 uint8_t read[16];assert(readCdb(read,49692663,32)&&read[0]==0x28&&be32(read+2)==49692663&&read[7]==0&&read[8]==32&&allowed(0,read,32*4096));
 Packet readPacket;assert(command(readPacket.utrd,readPacket.ucd,0x8ce326000ULL,0,read,32*4096));assert(readPacket.ucd[16]==0x28&&be32(readPacket.ucd+18)==49692663&&readPacket.ucd[24]==32);
 assert(readCdb(read,62275574,1)&&read[0]==0x28&&allowed(0,read,4096));
 assert(readCdb(read,UINT32_MAX,1)&&read[0]==0x28);assert(readCdb(read,uint64_t(UINT32_MAX)+1,1)&&read[0]==0x88&&allowed(0,read,4096));
 assert(readCdb(read,UINT32_MAX,2)&&read[0]==0x88);assert(!readCdb(read,UINT64_MAX,2)&&!readCdb(read,0,0)&&!readCdb(read,0,33));
 assert(readCdb(read,1,1));read[8]=2;assert(!allowed(0,read,4096));read[8]=1;read[10]=1;assert(!allowed(0,read,4096));
 uint8_t ssu[16]={0x1b,0,0,0,0x10},tur[16]={};Packet zero;
 assert(command(zero.utrd,zero.ucd,0x8ce326000ULL,0xd0,ssu,0));assert(zero.utrd[0]==0x10000000&&zero.utrd[7]==0x01000000&&zero.ucd[1]==0);
 assert(!allowed(0,ssu,0)&&!allowed(0xd0,tur,0)&&!allowed(0xd0,cap,32));ssu[4]=0x20;assert(!allowed(0xd0,ssu,0));
 for(unsigned op:{0x2aU,0x8aU,0x04U,0x42U}){uint8_t c[16]={};c[0]=op;assert(!allowed(0,c,4096));}
 uint8_t rsp[512];Status status;check(rsp,0,32,6,0x29,0);
 // The old driver's predicate rejects this standards-valid CHECK CONDITION.
 assert((rsp[1]&0x60)&&be32(rsp+12)==32);
 assert(response(rsp,0,0,32,status)&&status.scsi==2&&status.sense==0x062900&&status.senseKnown&&!status.exact&&retryable(status));
 memset(rsp,0,512);rsp[0]=0x21;assert(response(rsp,0,0,32,status)&&status.exact);
 check(rsp,0,32,2,4,1,true);assert(response(rsp,0,0,32,status)&&status.sense==0x020401&&retryable(status));
 check(rsp,0,32,5,0x20,0);assert(response(rsp,0,0,32,status)&&!retryable(status));
 rsp[2]=1;assert(!response(rsp,0,0,32,status));rsp[2]=0;rsp[3]=1;assert(!response(rsp,0,0,32,status));rsp[3]=0;rsp[8]=1;assert(!response(rsp,0,0,32,status));rsp[8]=0;assert(!response(rsp,1,0,32,status));
 rsp[11]=3;rsp[33]=18;assert(!response(rsp,0,0,32,status));
 memset(rsp,0,512);rsp[0]=0x21;rsp[1]=0x20;putBe32(rsp+12,32);assert(response(rsp,0,0,32,status)&&!status.exact);
 Packet control;assert(controlRequest(control.utrd,control.ucd,0x8ce326000ULL,0x16,2,0,true));assert(control.ucd[0]==0x16&&control.ucd[5]==1&&control.ucd[12]==3&&control.ucd[13]==2&&control.utrd[0]==0x10000000&&control.utrd[7]==0x01000000);
 memset(rsp,0,512);rsp[0]=0x36;rsp[12]=3;rsp[13]=2;putBe32(rsp+20,0x33);auto cr=controlResponse(rsp,0x16,2,0,true);assert(cr.valid&&cr.success&&cr.value==0x33);
 rsp[6]=0xf9;cr=controlResponse(rsp,0x16,2,0,true);assert(cr.valid&&!cr.success);rsp[0]=0x21;assert(!controlResponse(rsp,0x16,2,0,true).valid);
 Device sleeping;Power power;assert(wake(power,sleeping.no(),sleeping.q(),sleeping.c(),sleeping.wait(),sleeping.healthy())==Wake::Ready);assert(power.before==0x33&&power.after==0x11&&sleeping.wakes==1&&sleeping.pauses==50);assert((sleeping.order==std::vector<unsigned>{1,2,3,2}));
 sleeping.readyAfter=3;assert(ready(0,sleeping.c(),sleeping.wait(),sleeping.healthy())&&!sleeping.poisoned&&sleeping.turs==3&&sleeping.pauses==70);
 Device active;active.alreadyActive=true;Power ap;assert(wake(ap,active.no(),active.q(),active.c(),active.wait(),active.healthy())==Wake::Ready&&active.wakes==0&&active.pauses==0);
 Device ua;ua.wakeAttention=true;Power up;assert(wake(up,ua.no(),ua.q(),ua.c(),ua.wait(),ua.healthy())==Wake::Ready&&ua.wakes==2&&!ua.poisoned);
 Device stuck;stuck.readyAfter=30;assert(!ready(0,stuck.c(),stuck.wait(),stuck.healthy())&&stuck.turs==20&&stuck.pauses==190&&!stuck.poisoned);
 Device asleep;asleep.stillAsleep=true;Power sp;assert(wake(sp,asleep.no(),asleep.q(),asleep.c(),asleep.wait(),asleep.healthy())==Wake::NotActive);
 Device noPower;noPower.queryFail=true;Power np;assert(wake(np,noPower.no(),noPower.q(),noPower.c(),noPower.wait(),noPower.healthy())==Wake::PowerQuery&&noPower.wakes==0);
 Device bad;bad.nopFail=true;Power bp;assert(wake(bp,bad.no(),bad.q(),bad.c(),bad.wait(),bad.healthy())==Wake::Nop&&bad.queries==0&&bad.wakes==0);
 // Production read retry, including failures that must never be retried.
 for(unsigned transient:{8U,0x28U,2U}){
  unsigned calls=0,delays=0;
  assert(readRetry([&](Status &s){++calls;s.scsi=uint8_t(transient);s.senseKnown=true;s.sense=0x062900;return calls<3?int(transient):0;},
    [&](unsigned n){assert(n==10);++delays;},[]{return true;}));
  assert(calls==3&&delays==2);
 }
 for(unsigned key:{2U,6U}){
  unsigned calls=0;
  assert(readRetry([&](Status &s){++calls;s.scsi=2;s.senseKnown=true;s.sense=key<<16;return calls==1?2:0;},
    [](unsigned n){assert(n==10);},[]{return true;}));assert(calls==2);
 }
 for(int failure:{-1,-2,2}){
  unsigned calls=0,delays=0;
  assert(!readRetry([&](Status &s){++calls;s.scsi=2;s.senseKnown=true;s.sense=0x052000;return failure;},
    [&](unsigned){++delays;},[]{return true;}));assert(calls==1&&delays==0);
 }
 unsigned exhausted=0,delays=0;
 assert(!readRetry([&](Status &s){++exhausted;s.scsi=8;return 8;},[&](unsigned){++delays;},[]{return true;}));
 assert(exhausted==3&&delays==2);
 bool poisoned=false;unsigned attempts=0;
 assert(!readRetry([&](Status &s){++attempts;s.scsi=8;poisoned=true;return 8;},[](unsigned){assert(false);},[&]{return !poisoned;}));
 assert(attempts==1);
 puts("PASS: production UFS wire layouts, CHECK CONDITION/sense without poison, zero-data command policy, wake order, power requery and bounded readiness retries");
}
