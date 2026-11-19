// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "B5qRootFormat.h"
namespace B5qUfsProtocol {
using namespace B5qFormat;
constexpr uint32_t commandOffset=0x1000,responseOffset=0x200,prdOffset=0x400,dataOffset=0x2000;
struct Status {
 uint8_t type=0,flags=0,response=0,scsi=0xff;
 uint32_t residual=0,sense=0;
 bool senseKnown=false,exact=false;
};
inline bool allowed(uint8_t lun,const uint8_t cdb[16],uint32_t bytes) {
 // Non-data commands have exact, explicit targets. No block write command.
 if(lun==0xd0){if(bytes||cdb[0]!=0x1b||cdb[4]!=0x10)return false;for(unsigned i=1;i<16;++i)if(i!=4&&cdb[i])return false;return true;}
 if(lun>7)return false;
 if(cdb[0]==0){if(bytes)return false;for(unsigned i=1;i<16;++i)if(cdb[i])return false;return true;}
 if(cdb[0]==0x9e&&cdb[1]==0x10&&bytes==32&&be32(cdb+10)==32){for(unsigned i=2;i<16;++i)if(i<10||i>=14)if(cdb[i])return false;return true;}
 if(cdb[0]==0x25&&bytes==8){for(unsigned i=1;i<16;++i)if(cdb[i])return false;return true;}
 if(cdb[0]==0x28){
  unsigned blocks=(unsigned(cdb[7])<<8)|cdb[8];
  if(!blocks||!bytes||bytes>128*1024||bytes%4096||blocks!=bytes/4096)return false;
  if(cdb[1]||cdb[6]||cdb[9])return false;
  for(unsigned i=10;i<16;++i)if(cdb[i])return false;
  return true;
 }
 return cdb[0]==0x88&&bytes&&bytes<=128*1024&&bytes%4096==0&&be32(cdb+10)==bytes/4096;
}
inline bool readCdb(uint8_t cdb[16],uint64_t lba,uint32_t count) {
 for(unsigned i=0;i<16;++i)cdb[i]=0;
 if(!count||count>128*1024/4096||uint64_t(count)-1>UINT64_MAX-lba)return false;
 if(lba<=UINT32_MAX&&count<=0xffffU&&uint64_t(count)-1<=UINT32_MAX-lba){
  cdb[0]=0x28;putBe32(cdb+2,uint32_t(lba));cdb[7]=uint8_t(count>>8);cdb[8]=uint8_t(count);
 } else {cdb[0]=0x88;putBe64(cdb+2,lba);putBe32(cdb+10,count);}
 return true;
}
inline void descriptor(uint32_t *utrd,uint64_t dma,uint32_t bytes) {
 utrd[0]=0x10000000U|(bytes?(2U<<25):0);utrd[2]=15;
 utrd[4]=uint32_t(dma+commandOffset);utrd[5]=uint32_t((dma+commandOffset)>>32);
 utrd[6]=(512U/4)|((responseOffset/4)<<16);utrd[7]=(bytes?1U:0U)|((prdOffset/4)<<16);
}
inline bool command(uint32_t *utrd,uint8_t *ucd,uint64_t dma,uint8_t lun,const uint8_t cdb[16],uint32_t bytes) {
 if(!allowed(lun,cdb,bytes))return false;
 descriptor(utrd,dma,bytes);ucd[0]=1;ucd[1]=bytes?0x40:0;ucd[2]=lun;ucd[3]=0;
 putBe32(ucd+12,bytes);for(unsigned i=0;i<16;++i)ucd[16+i]=cdb[i];
 if(bytes){auto *prd=reinterpret_cast<uint32_t*>(ucd+prdOffset);prd[0]=uint32_t(dma+dataOffset);prd[1]=uint32_t((dma+dataOffset)>>32);prd[3]=bytes-1;}
 return true;
}
inline bool response(const uint8_t *rsp,uint32_t ocs,uint8_t lun,uint32_t bytes,Status &out) {
 out={};out.type=rsp[0];out.flags=rsp[1];out.response=rsp[6];out.scsi=rsp[7];out.residual=be32(rsp+12);
 unsigned length=(unsigned(rsp[10])<<8)|rsp[11];
 if(ocs||rsp[0]!=0x21||rsp[2]!=lun||rsp[3]||rsp[8]||length>480||rsp[6])return false;
 if(length){
  unsigned senseLength=(unsigned(rsp[32])<<8)|rsp[33];if(length<2||senseLength>length-2)return false;
  const uint8_t *sense=rsp+34;unsigned code=sense[0]&0x7f;
  if(senseLength>=14&&(code==0x70||code==0x71)){out.sense=((sense[2]&15U)<<16)|(unsigned(sense[12])<<8)|sense[13];out.senseKnown=true;}
  else if(senseLength>=4&&(code==0x72||code==0x73)){out.sense=((sense[1]&15U)<<16)|(unsigned(sense[2])<<8)|sense[3];out.senseKnown=true;}
 }
 // A valid CHECK CONDITION may carry underflow and residual. These are not
 // malformed transport headers, and must not poison or suppress retries.
 out.exact=out.scsi==0&&(!bytes||(!(rsp[1]&0x60)&&!out.residual));
 return true;
}
inline bool controlRequest(uint32_t *utrd,uint8_t *ucd,uint64_t dma,uint8_t type,uint8_t idn,uint8_t index,bool attribute) {
 if(type!=0&&type!=0x16)return false;
 descriptor(utrd,dma,0);ucd[0]=type;
 if(type==0x16){ucd[5]=1;ucd[12]=attribute?3:1;ucd[13]=idn;ucd[14]=index;if(!attribute)ucd[19]=0xff;}
 return true;
}
struct Control { bool valid=false,success=false;unsigned length=0;uint32_t value=0; };
inline Control controlResponse(const uint8_t *rsp,uint8_t type,uint8_t idn,uint8_t index,bool attribute) {
 Control out;out.length=(unsigned(rsp[10])<<8)|rsp[11];
 out.valid=rsp[0]==(type==0?0x20:0x36)&&!rsp[2]&&!rsp[3]&&!rsp[8]&&out.length<=480;
 if(!out.valid||rsp[6])return out;
 if(type==0)out.success=out.length==0;
 else if(attribute){out.success=rsp[12]==3&&rsp[13]==idn&&!rsp[14]&&!rsp[15]&&!out.length;out.value=be32(rsp+20);}
 else {unsigned echo=(unsigned(rsp[18])<<8)|rsp[19];out.success=rsp[12]==1&&rsp[13]==idn&&rsp[14]==index&&!rsp[15]&&out.length>=0x13&&out.length<=255&&echo==out.length;}
 return out;
}
inline bool retryable(const Status &s) {
 return s.scsi==8||s.scsi==0x28||(s.scsi==2&&(!s.senseKnown||(s.sense>>16)==6||(s.sense>>16)==2));
}
struct Power { uint32_t before=~0U,after=~0U; };
enum class Wake { Ready,Nop,PowerQuery,StartStop,PowerAfter,NotActive };
template<class Nop,class Query,class Scsi,class Pause,class Healthy>
Wake wake(Power &power,Nop nop,Query query,Scsi scsi,Pause pause,Healthy healthy) {
 if(!nop())return Wake::Nop;
 if(!query(power.before))return Wake::PowerQuery;
 power.after=power.before;
 if((power.before&255)==0x11)return Wake::Ready;
 uint8_t cdb[16]={0x1b,0,0,0,0x10};Status result;bool ready=false;
 for(unsigned attempt=0;attempt<3;++attempt){
  int status=scsi(0xd0,cdb,0,result);if(!status){ready=true;break;}
  if(!healthy()||status<0||!retryable(result))break;
  if(attempt<2)pause(10);
 }
 if(!ready)return Wake::StartStop;
 pause(50);
 if(!query(power.after))return Wake::PowerAfter;
 return (power.after&255)==0x11?Wake::Ready:Wake::NotActive;
}
template<class Scsi,class Pause,class Healthy>
bool ready(uint8_t lun,Scsi scsi,Pause pause,Healthy healthy) {
 uint8_t tur[16]={};Status result;
 for(unsigned attempt=0;attempt<20;++attempt){
  int status=scsi(lun,tur,0,result);if(!status)return true;
  if(!healthy()||status<0||!retryable(result))return false;
  if(attempt<19)pause(10);
 }
 return false;
}
}
