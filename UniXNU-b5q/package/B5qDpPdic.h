/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Samsung max77705_alternate.c and max77705_usbc.c1931..2020.
 * The caller owns the mailbox and the existing physical SE8 bus lock. */
#pragma once
#include <stdint.h>
#include <stddef.h>
namespace B5qDp {
inline uint32_t le32(const uint8_t *b){return uint32_t(b[0])|uint32_t(b[1])<<8|uint32_t(b[2])<<16|uint32_t(b[3])<<24;}
inline void put32(uint8_t *b,uint32_t v){for(unsigned i=0;i<4;i++)b[i]=uint8_t(v>>(8*i));}
enum class PdError:unsigned {None,Bounds,Io,Timeout,Opcode,Packet,Rejected,Sequence,Unsupported,Detached};
template<class Io> struct Mailbox {
 Io &io;PdError error=PdError::None;uint8_t lastInterrupt=0;unsigned commands=0;
 explicit Mailbox(Io &owner):io(owner){}
 bool command(uint8_t opcode,const uint8_t *input,unsigned bytes,uint8_t *output,unsigned response){
  error=PdError::None;
  if(bytes>32||response>32||(bytes&&!input)||!output){error=PdError::Bounds;return false;}
  if(!io.connected()){error=PdError::Detached;return false;}
  uint8_t ignored=0,buffer[34]={0x21,opcode};
  if(!io.read(0x25,0x02,&ignored,1)){error=PdError::Io;return false;}
  for(unsigned i=0;i<bytes;i++)buffer[i+2]=input[i];
  if(!io.write(0x25,buffer,bytes+2)){error=PdError::Io;return false;}
  if(bytes<32){const uint8_t end[]={0x41,0};if(!io.write(0x25,end,2)){error=PdError::Io;return false;}}
  ++commands;bool complete=false;const uint64_t began=io.nowUs();
  for(unsigned poll=0;poll<500&&io.nowUs()-began<500000;poll++){
   if(!io.connected()){error=PdError::Detached;return false;}
   if(!io.read(0x25,0x02,&lastInterrupt,1)){error=PdError::Io;return false;}
   if(lastInterrupt&0x80){complete=true;break;}io.delay(1000);
  }
  if(!complete){error=PdError::Timeout;return false;}
  uint8_t result[33]={};
  if(!io.read(0x25,0x51,result,1)||(response&&!io.read(0x25,0x52,result+1,response))){error=PdError::Io;return false;}
  if(result[0]!=opcode){error=PdError::Opcode;return false;}
  for(unsigned i=0;i<=response;i++)output[i]=result[i];return true;
 }
 bool enable(bool on){const uint8_t value=on?3:1;uint8_t response[2];return command(0x55,&value,1,response,1);}
 bool request(unsigned cmd,unsigned position=0,uint32_t vdo=0,bool data=false){
  if(cmd>31||position>7){error=PdError::Bounds;return false;}
  uint8_t message[9]={uint8_t((data?2:1)|(1u<<3))},response[33];
  const uint32_t svid=cmd<=2?0xff00:0xff01;
  put32(message+1,(svid<<16)|0x8000|(position<<8)|cmd);
  if(data)put32(message+5,vdo);
  return command(0x48,message,data?9:5,response,data?14:10);
 }
 bool get(uint8_t id,uint8_t out[33]){
  const unsigned bytes=(id==1||id==2)?31:id==4||id==5?7:11;
  for(unsigned i=0;i<33;i++)out[i]=0;
  return command(0x4b,&id,1,out,bytes);
 }
};
struct AltMode {
 enum class Phase:unsigned {Off,Identity,Svid,Modes,Enter,Status,Configure,Active,Failed};
 Phase phase=Phase::Off;PdError error=PdError::None;uint8_t supported=0,pin=0;bool hpd=false,hpdIrq=false,multi=false;uint32_t status=0,generation=0;
 void reset(){const auto next=generation+1;*this={};generation=next;}
 unsigned lanes()const{return pin==8?2:(pin==4||pin==16)?4:0;}
 static uint8_t choose(uint8_t pins,bool preferUsb){
  // Only the b5q USB-C C/D/E routes are selected, never unimplemented A/B/F.
  const uint8_t order0[]={4,16,8},order1[]={8,4,16};const uint8_t *order=preferUsb?order1:order0;
  for(unsigned i=0;i<3;i++)if(pins&order[i])return order[i];return 0;
 }
 template<class M>bool start(M &m,bool sinkDfp=false){
  // MAX77705 0x55 enables its automatic identity/SVID/mode discovery.
  // The original driver explicitly requests Identity only for Sink+DFP
  // (a hub supplying this phone), not in parallel with every firmware step.
  reset();if(!m.enable(true)||(sinkDfp&&!m.request(1))){error=m.error;phase=Phase::Failed;return false;}phase=Phase::Identity;return true;
 }
 bool reject(PdError why){error=why;phase=Phase::Failed;hpd=false;return false;}
 template<class M>bool event(M &m,uint8_t id,const uint8_t *reply,size_t bytes){
  hpdIrq=false;if(!reply||bytes<8||bytes>33||reply[0]!=0x4b||reply[1]!=id)return reject(PdError::Packet);
  const uint32_t header=le32(reply+4);const unsigned cmd=header&31,type=(header>>6)&3,svid=header>>16;
  const unsigned expected=id==0x10?16:id==0x11?17:id;
  if(cmd!=expected||!(header&0x8000)||svid!=(id<=2?0xff00u:0xff01u))return reject(PdError::Packet);
  if(id!=6&&type!=1)return reject(PdError::Rejected);
  if(id==6&&type!=0)return reject(PdError::Packet);
  /* Samsung counts its message header and VDM header as two objects. */
  const unsigned objects=reply[2]&7;if(objects<2||bytes<objects*4)return reject(PdError::Packet);
  bool ok=true;
  switch(id){
  case 1:
   if(phase!=Phase::Identity||objects<3)return reject(PdError::Sequence);
   phase=Phase::Svid;break;
  case 2:{
   if(phase!=Phase::Svid||objects<3)return reject(PdError::Sequence);bool found=false;
   for(unsigned at=8;at+1<objects*4;at+=2)if((reply[at]|uint16_t(reply[at+1])<<8)==0xff01)found=true;
   if(!found)return reject(PdError::Unsupported);phase=Phase::Modes;break;}
  case 3:{
   if(phase!=Phase::Modes||objects<3)return reject(PdError::Sequence);const uint32_t cap=le32(reply+8);
   const unsigned port=cap&3;if(!(port&1)||!(cap&4))return reject(PdError::Unsupported);
   supported=uint8_t(cap>>((cap&64)?16:8))&0x1c;if(!supported)return reject(PdError::Unsupported);
   phase=Phase::Enter;ok=m.request(4,1);break;}
  case 4:
   if(phase!=Phase::Enter||((header>>8)&7)!=1)return reject(PdError::Sequence);
   phase=Phase::Status;break;
  case 6:case 0x10:
   if((phase!=Phase::Status&&phase!=Phase::Active&&phase!=Phase::Configure)||objects<3)return reject(PdError::Sequence);
   status=le32(reply+8);hpd=status&128;hpdIrq=status&256;multi=status&16;
   if((status&(32|64))||!(status&3)){reset();return true;}
   if(phase==Phase::Status){pin=choose(supported,multi);if(!pin)return reject(PdError::Unsupported);phase=Phase::Configure;ok=m.request(17,1,6|(uint32_t(pin)<<8),true);}break;
  case 0x11:
   if(phase!=Phase::Configure||((header>>8)&7)!=1)return reject(PdError::Sequence);
   phase=Phase::Active;++generation;break;
  case 5:reset();break;
  default:return reject(PdError::Unsupported);
  }
  if(!ok)return reject(m.error);return true;
 }
};
}
