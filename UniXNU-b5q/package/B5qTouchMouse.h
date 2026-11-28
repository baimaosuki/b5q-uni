// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "Wn8030Pointer.h"
// Flip5:4095 counts/67mm. 184 counts are3mm; Y is scaled by the
// physical2640/1080 aspect. Synthetic buttons have real32ms down/8ms up
// windows. advance() runs on the HID work-loop timer, never sleeps in IRQ.
struct B5qTouchMouse {
 wn8030_pointer pointer={};
 static constexpr unsigned holdMs=32,upMs=8,tapMs=400,doubleMs=350;
 static constexpr int slopX=184,slopY=76;
 uint32_t began=0,lastTap=0,releaseAt=0,nextPress=0;
 unsigned tapCount=0,tapRemaining=0,queueCount=0;
 uint8_t tapIds[2]={},queue[8]={},held=0;
 int startX[2]={},startY[2]={};
 bool tapping=false,releasePending=false,dragging=false,haveTap=false,dragPressed=false;
 static unsigned coordinate(int value){return unsigned(value<0?0:value>32767?32767:value)*4095u/32767u;}
 static bool due(uint32_t now,uint32_t at){return int32_t(now-at)>=0;}
 template<class Send>void button(uint8_t mask,Send send){
  uint8_t out[WN8030_POINTER_REPORT]={};out[0]=WN8030_POINTER_ID;out[1]=mask;held=mask;send(out);
 }
 template<class Send>void advance(uint32_t now,Send send){
  if(releasePending&&due(now,releaseAt)){button(0,send);releasePending=false;nextPress=now+upMs;}
  if(!held&&due(now,nextPress)){
   if(queueCount){const uint8_t mask=queue[0];for(unsigned i=1;i<queueCount;i++)queue[i-1]=queue[i];--queueCount;
    button(mask,send);releasePending=true;releaseAt=now+holdMs;
   }else if(dragging){button(1,send);dragPressed=true;releasePending=false;releaseAt=now+holdMs;}
  }
 }
 unsigned timeout(uint32_t now)const{
  if(releasePending)return due(now,releaseAt)?1:releaseAt-now;
  if(!held&&(queueCount||dragging))return due(now,nextPress)?1:nextPress-now;
  return 0;
 }
 template<class Send>void cancel(Send send){
  tapping=dragging=releasePending=haveTap=dragPressed=false;queueCount=tapCount=tapRemaining=0;
  pointer={};button(0,send);
 }
 template<class Send>void update(unsigned count,const int *ids,const int *xs,const int *ys,uint32_t now,bool recovered,Send send){
  if(recovered||count>WN8030_TOUCHPAD_FINGERS||(count&&(!ids||!xs||!ys))){cancel(send);return;}
  unsigned buttonEvents=0;auto scheduled=[&](const uint8_t *r){++buttonEvents;send(r);};
  advance(now,scheduled);
  uint8_t pad[WN8030_TOUCHPAD_REPORT]={},out[WN8030_POINTER_REPORT]={};
  for(unsigned i=0;i<count;i++){uint8_t *p=pad+2+6*i;p[0]=7;p[1]=uint8_t(ids[i]);put_le16(p+2,coordinate(xs[i]));put_le16(p+4,4095-coordinate(ys[i]));}
  pad[20]=uint8_t(count);
  if(count&&!pointer.fingers){
   began=now;tapCount=tapRemaining=count;tapping=count<=2;
   // A second single touchdown holds left through movement until lift.
   dragging=count==1&&haveTap&&now-lastTap<=doubleMs;haveTap=false;dragPressed=false;
   if(dragging)tapping=false;
   for(unsigned i=0;i<count&&i<2;i++){tapIds[i]=uint8_t(ids[i]);startX[i]=coordinate(xs[i]);startY[i]=coordinate(ys[i]);}
  }else if(count&&tapping){
   if(count>tapRemaining||(count!=tapCount&&!(tapCount==2&&count==1))||now-began>tapMs)tapping=false;
   tapRemaining=count;
   for(unsigned i=0;tapping&&i<count;i++){
    unsigned j=0;while(j<tapCount&&tapIds[j]!=uint8_t(ids[i]))++j;
    if(j==tapCount){tapping=false;break;}
    const int dx=int(coordinate(xs[i]))-startX[j],dy=int(coordinate(ys[i]))-startY[j];
    if(dx>slopX||dx< -slopX||dy>slopY||dy< -slopY)tapping=false;
   }
  }
  if(count>1&&dragging){dragging=false;if(held==1){releasePending=true;releaseAt=now+holdMs;}}
  if(!count){
   if(dragging){dragging=false;if(dragPressed&&held==1){releasePending=true;if(due(now,releaseAt))releaseAt=now;}
    else if(!dragPressed&&queueCount<sizeof(queue))queue[queueCount++]=1;}
   else if(tapping&&now-began<=tapMs){
    if(queueCount<sizeof(queue))queue[queueCount++]=tapCount==2?2:1;
    haveTap=tapCount==1;lastTap=now;
   }
   tapping=false;
  }
  advance(now,scheduled);
  // The upstream codec owns movement/scroll; its60ms anchor reset must not
  // cancel a stationary contact's independent tap or held button.
  pad[1]=held;
  if(wn8030_pointer_report_at(&pointer,pad,now,out)){out[1]=held;
   bool motion=false;for(unsigned i=2;i<sizeof(out);i++)motion=motion||out[i];
   if(!buttonEvents||motion)send(out);
  }
 }
};
