/* SPDX-License-Identifier: GPL-2.0-only */
/* Source-qualified dp_aux.c151..280/catalog.c275..306,470..491.
 * One serialized worker owns this FIFO; no DMA or external SMMU registers. */
#pragma once
#include <stdint.h>
#include <stddef.h>
namespace B5qDp {
enum class Block:unsigned {Ahb,Aux,Phy,Pll,Tx0,Tx1,Combo,Link,DispCc,Gcc,Pixel,Dpu};
enum class AuxError:unsigned {None,Bounds,Detached,Timeout,Nack,Defer,Address,Count,Phy,Index};
constexpr uint32_t auxDone=1u<<3,auxAddress=1u<<6,auxTimeout=1u<<9,auxNackDefer=1u<<12,auxCount=1u<<15,
 auxNack=1u<<18,auxDefer=1u<<21,auxPll=1u<<24,auxPhy=1u<<27;
constexpr uint32_t auxInterrupts=auxDone|auxAddress|auxTimeout|auxNackDefer|auxCount|auxNack|auxDefer|auxPll|auxPhy;
template<class Io> struct Aux {
 Io &io;AuxError error=AuxError::None;uint32_t lastStatus=0;unsigned transactions=0;bool segmentUsed=false;
 explicit Aux(Io &owner):io(owner){}
 void ack(){const uint32_t status=io.read(Block::Ahb,0x20)&auxInterrupts;io.write(Block::Ahb,0x20,status<<1);}
 void cancel(){
  io.write(Block::Aux,0x38,0);const uint32_t control=io.read(Block::Aux,0x30);
  io.write(Block::Aux,0x30,control|2);io.delay(1000);io.write(Block::Aux,0x30,control&~2u);ack();
 }
 bool once(bool native,bool read,uint32_t address,uint8_t *bytes,unsigned length,bool mot){
  error=AuxError::None;lastStatus=0;
  if(!bytes||!length||length>16||address>0xfffff||(!native&&address>127)){error=AuxError::Bounds;return false;}
  if(!io.connected()){error=AuxError::Detached;return false;}
  ack();const unsigned count=read?4:4+length;
  const uint8_t header[]={uint8_t(((address>>16)&15)|(uint32_t(read)<<4)),uint8_t(address>>8),uint8_t(address),uint8_t(length-1)};
  for(unsigned i=0;i<count;i++)io.write(Block::Aux,0x34,(uint32_t(i<4?header[i]:bytes[i-4])<<8)|(i?0u:1u<<31));
  io.write(Block::Aux,0x38,0);
  // V600 AUX hardware interrupts are cleared by its source-specific PHY
  // owner before this call; do not access oldV200 PHY offsets here.
  io.write(Block::Aux,0x38,(native?0u:(1u<<8)|(mot?1u<<11:0u))|(1u<<9));++transactions;
  bool completed=false;const uint64_t started=io.nowUs();
  for(unsigned polls=0;polls<25000;polls++){
   if(io.nowUs()-started>=250000)break;
   if(!io.connected()){error=AuxError::Detached;break;}
   if(io.nowUs()-started>=250000)break;
   lastStatus=io.read(Block::Ahb,0x20)&auxInterrupts;
   if(io.nowUs()-started>=250000)break;
   if(lastStatus){completed=true;break;}io.delay(10);
  }
  ack();
  if(error==AuxError::Detached){cancel();return false;}
  if(!completed||lastStatus&auxTimeout)error=AuxError::Timeout;
  else if(lastStatus&(auxPhy|auxPll))error=AuxError::Phy;
  else if(lastStatus&auxAddress)error=AuxError::Address;
  else if(lastStatus&auxCount)error=AuxError::Count;
  else if(lastStatus&auxNack)error=AuxError::Nack;
  else if(lastStatus&(auxNackDefer|auxDefer))error=AuxError::Defer;
  else if(!(lastStatus&auxDone))error=AuxError::Timeout;
  if(error!=AuxError::None){cancel();return false;}
  io.write(Block::Aux,0x38,io.read(Block::Aux,0x38)&~(1u<<9));
  if(read){
   uint8_t result[16];io.write(Block::Aux,0x34,(1u<<31)|1u);(void)io.read(Block::Aux,0x34);
   for(unsigned i=0;i<length;i++){const uint32_t value=io.read(Block::Aux,0x34);if(((value>>16)&255)!=i){error=AuxError::Index;cancel();return false;}result[i]=uint8_t(value>>8);}
   for(unsigned i=0;i<length;i++)bytes[i]=result[i];
  }
  return true;
 }
 bool transfer(bool native,bool read,uint32_t address,uint8_t *bytes,unsigned length,bool mot=false){
  for(unsigned attempt=0;attempt<7;attempt++){
   if(once(native,read,address,bytes,length,mot))return true;
   if(error!=AuxError::Defer)return false;io.delay(400);
  }return false;
 }
 bool dpcd(bool read,uint32_t address,uint8_t *bytes,unsigned length){
  if(!bytes||!length||address>0xfffff||length>0x100000-address){error=AuxError::Bounds;return false;}
  for(unsigned at=0;at<length;){const unsigned n=length-at>16?16:length-at;if(!transfer(true,read,address+at,bytes+at,n))return false;at+=n;}return true;
 }
 bool edidBlock(unsigned block,uint8_t out[128]){
  if(!out||block>7){error=AuxError::Bounds;return false;}
  uint8_t segment=uint8_t(block/2),buffer[128];
  // Samsung dp_aux_transfer_helper restores segment/offset before each
  // chunk for sinks which lose the pointer at an AUX read STOP. Keep the
  // two address writes in the same I2C transaction as the following read.
  // Do not probe segment-address 0x30 on an old one-block EDID sink; after
  // reading a high block, explicitly reset it when returning to block 0/1.
  for(unsigned at=0;at<128;at+=16){
   uint8_t offset=uint8_t((block&1)*128+at);
   if(block>=2||segmentUsed){
    segmentUsed=true;
    if(!transfer(false,false,0x30,&segment,1,true))return false;
   }
   if(!transfer(false,false,0x50,&offset,1,true)||
      !transfer(false,true,0x50,buffer+at,16,false))return false;
  }
  uint8_t sum=0;for(unsigned i=0;i<128;i++)sum+=buffer[i];if(sum){error=AuxError::Count;return false;}
  for(unsigned i=0;i<128;i++)out[i]=buffer[i];return true;
 }
};
}
