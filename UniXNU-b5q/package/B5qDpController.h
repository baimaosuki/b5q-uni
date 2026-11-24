/* SPDX-License-Identifier: GPL-2.0-only */
/* Samsung dp_catalog.c + dp_panel.c RGB24 SST register paths.
 * PHY/power/resource ownership are separate prerequisites. */
#pragma once
#include "B5qDpAux.h"
#include "B5qDpMsa.h"
namespace B5qDp {
template<class Io>struct Controller {
 Io &io;uint32_t last=0;unsigned failed=0;
 explicit Controller(Io &owner):io(owner){}
 uint32_t r(unsigned off){return io.read(Block::Link,off);}
 void w(unsigned off,uint32_t value){io.write(Block::Link,off,value);}
 void reset(){
  const uint32_t old=io.read(Block::Ahb,0x10);
  io.write(Block::Ahb,0x10,old|1);io.delay(1000);io.write(Block::Ahb,0x10,old&~1u);
 }
 bool pattern(unsigned p){
  if(p!=0&&p!=1&&p!=2&&p!=3&&p!=7)return false;
  w(4,0);if(!p)return true;const unsigned bit=p==7?3:p-1;w(4,1u<<bit);
  for(unsigned i=0;i<10;i++){last=r(0x40);if(last&(1u<<(bit+3)))return true;if(!io.connected())return false;}
  failed=1;return false;
 }
 bool source(unsigned lanes){
  if((lanes!=1&&lanes!=2&&lanes!=4)||!io.connected())return false;
  w(0x38,0xe4); // Native logical-to-physical mapping; PHY owns orientation.
  // Original V600 lane polarity values, with zero DT lane-pnswap.
  io.write(Block::Tx0,0x5c,0x0a);io.write(Block::Tx1,0x5c,0x0a);
  w(0,r(0)&~0x04000100u); // SST: original mst_config(false).
  w(8,(r(8)&~((3u<<4)|(1u<<10)))|((lanes-1)<<4));
  w(0,r(0)|(1u<<25));w(0x44,(r(0x44)&0xfe0)|(lanes==1?14u:lanes==2?8u:5u));
  const uint32_t old=r(0);w(0,old&~3u);w(0,old|2);w(0,old&~3u);w(0,old|1);return true;
 }
 bool stream(const Mode &m,unsigned rate,unsigned lanes,bool enhanced){
  Msa msa;TransferUnit tu;
  if(!m.fits(lanes,rate)||!msa.calculate(m.pixelKHz,rate)||!tu.calculate(m,rate,lanes)||!io.connected())return false;
  w(8,(2u<<13)|(1u<<8)|((lanes-1)<<4)|(enhanced?64u:0u)|7);
  io.write(Block::Pixel,0x88,r(0)&(1u<<8)?1:0);
  io.write(Block::Pixel,0x10,io.read(Block::Pixel,0x10)|(1u<<8));
  w(0x10,msa.mvid);w(0x18,msa.nvid);w(0x2c,0x21); // RGB8, synchronous.
  w(0x1c,(m.totalHeight()<<16)|m.totalWidth());
  w(0x20,(uint32_t(m.vBlank-m.vFront)<<16)|(m.hBlank-m.hFront));
  w(0x24,(uint32_t(m.vSync)<<16)|(uint32_t(!m.vPositive)<<31)|m.hSync|(uint32_t(!m.hPositive)<<15));
  w(0x28,(uint32_t(m.height)<<16)|m.width);
  io.write(Block::Pixel,0x14,io.read(Block::Pixel,0x14)&~(1u<<4)); // no widebus.
  w(0x30,tu.boundary);w(0x4c,tu.size);w(0x34,tu.moderation);return true;
 }
 bool video(){
  if(!io.connected())return false;
  w(4,1u<<7);
  for(unsigned us=0;us<10000;us+=1000){last=r(0x40);if(last&1)return true;if(!io.connected())return false;io.delay(1000);}
  failed=2;w(4,0);return false;
 }
 void stop(){w(4,0);w(0,r(0)&~1u);}
};
}
