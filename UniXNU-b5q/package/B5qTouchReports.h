// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "B5qTouchProtocol.h"
namespace B5qTouch {
enum class ReportResult {Ignore,Frame,Released};
// Own the complete contact set. Error/status packets cannot bypass release
// by arriving with a code different from the selected coordinate report.
struct Reports {
 Point points[12]={};
 uint8_t mode=0;
 unsigned palm=0,invalid=0,c2=0,identify=0,errors=0,releases=0;
 bool reconfigure=false;
 void release() {releaseAll(points);++releases;}
 ReportResult error() {++errors;release();return ReportResult::Released;}
 ReportResult consume(uint8_t code,const uint8_t *data,size_t n,
                      const uint8_t *cfg,size_t cn,unsigned maximum) {
  if(code==0xc2) {++c2;release();return ReportResult::Released;}
  if(code==0x10) {++identify;reconfigure=true;release();return ReportResult::Released;}
  // OK, IDLE and BUSY may be interleaved with reports during commands.
  if(code<0x10 || code==0xff) {
   if(code==0 || code==1 || code==7)return ReportResult::Ignore;
   return error();
  }
  if(!mode || code!=mode)return ReportResult::Ignore;
  DeltaStats stats;
  const bool ok=code==0x11?parse(cfg,cn,data,n,points,maximum):
                code==0xc1?sec(data,n,points,&stats):false;
  if(!ok)return error();
  palm+=stats.palm;invalid+=stats.invalid;
  return ReportResult::Frame;
 }
};
}
