/* SPDX-License-Identifier: GPL-2.0-only */
/* Samsung 4nm-v1.1 PLL, V600 AUX and original b5q voltage tables.
 * Caller serializes the shared USB/DP combo before invoking this owner. */
#pragma once
#include "B5qDpAux.h"
#include "B5qDpPllData.h"
namespace B5qDp {
template<class Io>struct Phy {
 Io &io;uint32_t last=0;unsigned failed=0;
 static constexpr Block txBlocks[]={Block::Tx0,Block::Tx1};
 static constexpr unsigned enableValues[]={1,5,1,9};
 explicit Phy(Io &owner):io(owner){}
 void w(Block b,unsigned off,uint32_t value){io.write(b,off,value);}
 bool wait(Block b,unsigned off,uint32_t bit,unsigned step){
  for(unsigned us=0;us<10000;us+=500){last=io.read(b,off);if(last&bit)return true;if(!io.connected())break;io.delay(500);}
  failed=step;return false;
 }
 void clearAux(){w(Block::Phy,0x58,0x1f);w(Block::Phy,0x58,0x9f);w(Block::Phy,0x58,0);}
 void auxSetup(){
  w(Block::Phy,0x18,0x67);w(Block::Pll,0xdc,0x17);
  constexpr uint8_t values[]={0,0x13,0xa4,0,0x0a,0x26,0x0a,3,0xb7,3};
  for(unsigned i=0;i<10;i++)w(Block::Phy,0x20+4*i,values[i]);
  w(Block::Phy,0x54,0x1f);clearAux();
 }
 bool configure(unsigned rate,unsigned lanes,bool reverse){
  const unsigned index=rate==6?0:rate==10?1:rate==20?2:rate==30?3:4;
  if(index==4||(lanes!=1&&lanes!=2&&lanes!=4)){failed=1;return false;}const auto &p=pllV11[index];
  w(Block::Phy,0xc8,lanes|((reverse?2u:1u)<<4));w(Block::Phy,0x14,0xf);
  w(Block::Phy,0x18,lanes==4?0x7d:reverse?0x6d:0x75);
  constexpr struct{uint16_t off;uint8_t value;} common[]={{0x17c,0x15},{0x110,0x3b},{0xe4,2},{0xe0,0x0c},{0xe8,6},{0x164,0x30}};
  for(auto v:common)w(Block::Pll,v.off,v.value);w(Block::Pll,0xf4,p.pll_ivco);
  w(Block::Pll,0x78,0x36);w(Block::Pll,0x74,0x16);w(Block::Pll,0x70,6);
  w(Block::Pll,0x3c,p.hsclk_sel);w(Block::Pll,0x88,p.dec_start_mode0);
  w(Block::Pll,0x90,p.div_frac_start1_mode0);w(Block::Pll,0x94,p.div_frac_start2_mode0);w(Block::Pll,0x98,p.div_frac_start3_mode0);
  w(Block::Pll,0x80,p.lock_cmp1_mode0);w(Block::Pll,0x84,p.lock_cmp2_mode0);w(Block::Pll,0x120,p.lock_cmp_en);
  w(Block::Phy,0x70,p.phy_vco_div);w(Block::Pll,0x174,0x12);w(Block::Pll,0xa0,p.integloop_gain0_mode0);w(Block::Pll,0xa4,p.integloop_gain1_mode0);
  w(Block::Pll,0x140,0);w(Block::Pll,0xbc,p.bg_timer);w(Block::Pll,0x7c,0x14);w(Block::Pll,0x13c,0);
  w(Block::Pll,0xdc,0x17);w(Block::Pll,0x170,p.core_clk_en);w(Block::Pll,0x58,p.cmp_code1_mode0);w(Block::Pll,0x5c,p.cmp_code2_mode0);
  // Sink training uses downspread=0; explicitly turn off stale SSC.
  w(Block::Pll,0xc0,0);w(Block::Phy,0x1c,reverse?0x4c:0x5c);w(Block::Phy,0x24,0x13);w(Block::Phy,0x28,0xa4);
  for(auto block:txBlocks){
   w(Block::Phy,block==Block::Tx0?0x78:0x9c,5);
   constexpr struct{uint16_t off;uint8_t value;} tx[]={{0xc8,0x40},{0x20,0x30},{0x2c,0x3b},{8,0x0f},{0x1c,3},{0xc0,0x0f},{0x60,0},{0xc4,0}};
   for(auto v:tx)w(block,v.off,v.value);w(block,0x3c,p.lane_offset_tx);w(block,0x40,p.lane_offset_rx);w(block,0x24,4);
  }
  const unsigned div=rate==6||rate==10?1:rate==20?2:0;
  w(Block::Phy,0x70,(io.read(Block::Phy,0x70)&~3u)|div);return true;
 }
 bool enable(){
  failed=0;for(unsigned v:enableValues)w(Block::Phy,0x10,v);w(Block::Pll,0x118,0x20);
  if(!wait(Block::Pll,0x1f8,1,2)||!wait(Block::Pll,0x1d0,1,3)||!wait(Block::Pll,0x1d0,2,4))return false;
  w(Block::Phy,0x10,0x19);return wait(Block::Phy,0xe4,1,5)&&wait(Block::Phy,0xe4,2,6);
 }
 void disable(){w(Block::Phy,0x18,2);}
 bool levels(unsigned voltage,unsigned pre,unsigned rate,uint32_t version){
  if(voltage>3||pre>3||voltage+pre>3)return false;
  constexpr uint8_t swingVm[4][4]={{7,15,20,255},{17,29,31,255},{24,31,255,255},{255,255,255,255}};
  constexpr uint8_t preVm[4][4]={{0,13,21,255},{0,13,21,255},{0,12,255,255},{255,255,255,255}};
  constexpr uint8_t swingHigh[4][4]={{11,18,26,255},{18,26,31,255},{30,31,255,255},{255,255,255,255}};
  constexpr uint8_t preHigh[4][4]={{1,14,23,255},{0,13,22,255},{0,12,255,255},{255,255,255,255}};
  constexpr uint8_t swingLow[4][4]={{9,17,25,255},{18,26,31,255},{29,31,255,255},{255,255,255,255}};
  constexpr uint8_t preLow[4][4]={{0,14,23,255},{0,13,22,255},{8,19,255,255},{255,255,255,255}};
  const bool high=rate>=20,newer=version>=0x10020003;
  uint8_t swing=newer?(high?swingHigh[voltage][pre]:swingLow[voltage][pre]):swingVm[voltage][pre];
  uint8_t emphasis=newer?(high?preHigh[voltage][pre]:preLow[voltage][pre]):preVm[voltage][pre];
  if(swing==255||emphasis==255)return false;
  for(auto block:txBlocks){w(block,0x14,0x2a);w(block,0x0c,0x20);w(block,0x14,swing|32);w(block,0x0c,emphasis|32);}return true;
 }
};
}
