// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "Wn8030Pointer.h"
// Convert the board's 12-slot touch screen to the unchanged upstream pointer
// codec. This adapter only packs contacts and supplies the missing physical
// click button for short taps; movement/scroll/identity/timeout are upstream.
struct B5qTouchMouse {
 wn8030_pointer pointer={};
 uint32_t began=0;
 unsigned tapCount=0;
 uint8_t tapIds[2]={};
 int startX[2]={},startY[2]={};
 bool tapping=false;
 static unsigned coordinate(int value) {
  return unsigned(value<0?0:value>32767?32767:value)*4095u/32767u;
 }
 template<class Send> void update(unsigned count,const int *ids,const int *xs,const int *ys,
                                  uint32_t now,bool recovered,Send send) {
  uint8_t pad[WN8030_TOUCHPAD_REPORT]={},out[WN8030_POINTER_REPORT]={};
  // More than three contacts temporarily release, never latch a blocked mode.
  const bool valid=count<=WN8030_TOUCHPAD_FINGERS && (!count || (ids&&xs&&ys));
  if(recovered || !valid) {
   tapping=false;tapCount=0;
   pointer={};out[0]=WN8030_POINTER_ID;send(out);
   return;
  }
  for(unsigned i=0;i<count;++i) {
   uint8_t *p=pad+2+6*i;
   p[0]=7;p[1]=uint8_t(ids[i]);
   put_le16(p+2,coordinate(xs[i]));put_le16(p+4,4095-coordinate(ys[i]));
  }
  pad[20]=uint8_t(count);
  if(count && !pointer.fingers) {
   began=now;tapCount=count;tapping=count<=2;
   for(unsigned i=0;tapping&&i<count;++i) {
    tapIds[i]=uint8_t(ids[i]);startX[i]=coordinate(xs[i]);startY[i]=coordinate(ys[i]);
   }
  } else if(count && tapping) {
   if(count!=tapCount || now-pointer.at_ms>WN8030_POINTER_GAP_MS)tapping=false;
   for(unsigned i=0;tapping&&i<count;++i) {
    unsigned j=0;while(j<tapCount && tapIds[j]!=uint8_t(ids[i]))++j;
    if(j==tapCount) {tapping=false;break;}
    const int dx=int(coordinate(xs[i]))-startX[j],dy=int(coordinate(ys[i]))-startY[j];
    if(dx>48||dx< -48||dy>48||dy< -48)tapping=false;
   }
  }
  if(!count && tapping && now-began<=250) {
   pad[1]=tapCount==2?2:1;
   if(wn8030_pointer_report_at(&pointer,pad,now,out))send(out);
   pad[1]=0;
  }
  if(wn8030_pointer_report_at(&pointer,pad,now,out))send(out);
  if(!count)tapping=false;
 }
};
