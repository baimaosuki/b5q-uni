// SPDX-License-Identifier: BSD-2-Clause-Patent
#pragma once
#include "B5qMouseReport.h"
// Flip5 input is normalised to32767 on both axes by B5qTouch. Restore the
// controller's4095 range, with conservative /8X /4Y relative scaling.
// This object is the sole button owner; no wn8030 button/click state exists.
struct B5qTouchMouse {
 enum Mode {Idle,CandidateTap,Moving,Scrolling,Suppressed};
 static constexpr unsigned holdMs=32,upMs=8,tapMs=300,maxFingers=10;
 static constexpr int slopX=260,slopY=140;
 Mode mode=Idle;
 uint32_t began=0,releaseAt=0,nextPress=0,frameAt=0;
 uint32_t clicks_left=0,clicks_right=0,taps_cancelled_slop=0,taps_cancelled_time=0,lifts_seen=0;
 unsigned fingers=0,tapCount=0,tapRemaining=0,queueCount=0;
 int tapIds[2]={},startX[2]={},startY[2]={},activeIds[2]={};
 int anchorX=0,anchorY=0,remainderX=0,remainderY=0,scrollX=0,scrollY=0;
 uint8_t queue[8]={},held=0;
 bool releasePending=false,nextPressValid=false;
 static unsigned coordinate(int value){return unsigned(value<0?0:value>32767?32767:value)*4095u/32767u;}
 static bool due(uint32_t now,uint32_t at){return int32_t(now-at)>=0;}
 template<class Send>void packet(int dx,int dy,int wheel,int pan,Send send)const{
  uint8_t out[8];b5q_mouse_report(out,held,dx,dy,wheel,pan);send(out);
 }
 template<class Send>void button(uint8_t mask,Send send){
  if(held==mask)return;
  held=mask;
  if(mask==1)++clicks_left;else if(mask==2)++clicks_right;
  packet(0,0,0,0,send);
 }
 template<class Send>void advance(uint32_t now,Send send){
  if(releasePending&&due(now,releaseAt)){button(0,send);releasePending=false;nextPress=now+upMs;nextPressValid=true;}
  if(!held&&queueCount&&(!nextPressValid||due(now,nextPress))){
   const uint8_t mask=queue[0];for(unsigned i=1;i<queueCount;i++)queue[i-1]=queue[i];--queueCount;
   button(mask,send);nextPressValid=false;releasePending=true;releaseAt=now+holdMs;
  }
 }
 unsigned timeout(uint32_t now)const{
  if(releasePending)return due(now,releaseAt)?1:releaseAt-now;
  if(!held&&queueCount)return !nextPressValid||due(now,nextPress)?1:nextPress-now;
  return 0;
 }
 void clearMotion(){remainderX=remainderY=scrollX=scrollY=0;}
 template<class Send>void cancel(Send send){
  mode=Idle;fingers=tapCount=tapRemaining=queueCount=0;releasePending=false;nextPressValid=false;nextPress=0;
  clearMotion();button(0,send);
 }
 static int take(int &remainder,int delta,int scale,int limit){
  remainder+=delta;int value=remainder/scale;
  if(value>limit){value=limit;remainder%=scale;}
  else if(value< -limit){value= -limit;remainder%=scale;}
  else remainder-=value*scale;
  return value;
 }
 template<class Send>void update(unsigned count,const int *ids,const int *xs,const int *ys,uint32_t now,bool recovered,Send send){
  if(recovered||count>maxFingers||(count&&(!ids||!xs||!ys))){cancel(send);return;}
  advance(now,send);
  if(!count){
   if(fingers){++lifts_seen;
    if(mode==CandidateTap){
     if(now-began<=tapMs){if(queueCount<sizeof(queue))queue[queueCount++]=tapCount==2?2:1;}
     else ++taps_cancelled_time;
    }
   }
   mode=Idle;fingers=tapCount=tapRemaining=0;clearMotion();advance(now,send);return;
  }
  if(count>2){mode=Suppressed;fingers=count;clearMotion();return;}
  int x[2]={},y[2]={},id[2]={};
  for(unsigned i=0;i<count;i++){x[i]=int(coordinate(xs[i]));y[i]=int(coordinate(ys[i]));id[i]=ids[i];}
  if(count==2){
   if(id[0]==id[1]){cancel(send);return;}
   if(id[0]>id[1]){int t=id[0];id[0]=id[1];id[1]=t;t=x[0];x[0]=x[1];x[1]=t;t=y[0];y[0]=y[1];y[1]=t;}
  }
  const int cx=count==2?(x[0]+x[1])/2:x[0],cy=count==2?(y[0]+y[1])/2:y[0];
  bool same=count==fingers;
  for(unsigned i=0;i<count;i++)same=same&&activeIds[i]==id[i];
  const int rawDx=cx-anchorX,rawDy=cy-anchorY;
  const bool jump=fingers&&same&&(now-frameAt>80||rawDx>480||rawDx< -480||rawDy>260||rawDy< -260);
  frameAt=now;
  if(jump){anchorX=cx;anchorY=cy;clearMotion();}
  if(!fingers){
   began=now;tapCount=tapRemaining=count;mode=CandidateTap;
   for(unsigned i=0;i<count;i++){tapIds[i]=id[i];startX[i]=x[i];startY[i]=y[i];}
   anchorX=cx;anchorY=cy;clearMotion();
  }else if(mode==CandidateTap){
   // Normal two-finger placement and staggered2->1->0 lift are allowed.
   // Adding a finger after a partial lift or replacing an ID cancels the tap.
   if(tapCount==1&&count==2&&fingers==1&&now-began<=tapMs&&
      (id[0]==tapIds[0]||id[1]==tapIds[0])){
    for(unsigned i=0;i<2;i++)if(id[i]!=tapIds[0]){tapIds[1]=id[i];startX[1]=x[i];startY[1]=y[i];break;}
    tapCount=tapRemaining=2;
   }
   bool valid=count<=tapCount&&count<=tapRemaining;
   bool slop=false;
   for(unsigned i=0;i<count;i++){
    unsigned j=0;while(j<tapCount&&tapIds[j]!=id[i])++j;
    if(j==tapCount){valid=false;continue;}
    const int dx=x[i]-startX[j],dy=y[i]-startY[j];
    slop=slop||dx>slopX||dx< -slopX||dy>slopY||dy< -slopY;
   }
   const bool timed=now-began>tapMs;
   if(!valid||slop||timed){
    if(slop)++taps_cancelled_slop;if(timed)++taps_cancelled_time;
    mode=count==1?Moving:Scrolling;
    anchorX=cx;anchorY=cy;clearMotion(); // Crossing packet never jumps.
   }
   tapRemaining=count;
  }else if(!same||mode==Suppressed){
   mode=count==1?Moving:Scrolling;anchorX=cx;anchorY=cy;clearMotion();
  }else if(!jump){
   const int dx=cx-anchorX,dy=cy-anchorY;anchorX=cx;anchorY=cy;
   if(mode==Moving){
    const int mx=take(remainderX,dx,8,48),my=take(remainderY,dy,4,48);
    if(mx||my)packet(mx,my,0,0,send);
   }else if(mode==Scrolling){
    const int pan=take(scrollX,dx,100,127),wheel=take(scrollY,-dy,40,127);
    if(wheel||pan)packet(0,0,wheel,pan,send);
   }
  }
  fingers=count;for(unsigned i=0;i<count;i++)activeIds[i]=id[i];
 }
};
