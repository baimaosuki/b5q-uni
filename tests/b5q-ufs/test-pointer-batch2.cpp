#include <cassert>
#include <cstdio>
#include <climits>
#include <cstring>
#include <vector>
#include <string>
#include "B5qTouchPointer.h"
#include "B5qMouseReport.h"
#include "B5qProcTopFormat.h"
using B5qTouchPointer::Pointer;
static void descriptor() {
 unsigned page=0,size=0,count=0,report=0,bits=0,minimum=0,maximum=0;
 std::vector<unsigned> usages;bool buttons=false,xy=false,wheel=false,pan=false;
 for(unsigned i=0;i<sizeof(mouseDescriptor);) {
  unsigned key=mouseDescriptor[i++],n=key&3;if(n==3)n=4;
  assert(key!=0xfe && i+n<=sizeof(mouseDescriptor));unsigned value=0;
  for(unsigned j=0;j<n;++j)value|=unsigned(mouseDescriptor[i++])<<(8*j);
  switch(key&0xfc) {
   case 0x04:page=value;break;case 0x08:usages.push_back(value);break;
   case 0x18:minimum=value;break;case 0x28:maximum=value;break;
   case 0x74:size=value;break;case 0x94:count=value;break;case 0x84:report=value;break;
   case 0xa0:usages.clear();break;
   case 0x80:
    assert(report==0x1a);bits+=size*count;
    if(page==9 && size==1 && count==2) {assert(minimum==1 && maximum==2 && value==2);buttons=true;}
    if(page==1 && size==16 && count==2) {assert(usages.size()==2 && usages[0]==0x30 && usages[1]==0x31 && value==6);xy=true;}
    if(page==1 && size==8 && usages.size()==1 && usages[0]==0x38) {assert(value==6);wheel=true;}
    if(page==0xc && size==8 && usages.size()==1 && usages[0]==0x238) {assert(value==6);pan=true;}
    usages.clear();break;
  }
 }
 assert(bits==56 && buttons && xy && wheel && pan);
 unsigned char r[8];b5q_mouse_report(r,3,-32767,32767,-127,127);
 assert(r[0]==0x1a && r[1]==3 && r[2]==1 && r[3]==0x80 && r[4]==0xff && r[5]==0x7f && r[6]==0x81 && r[7]==0x7f);
}
static void gestures() {
 int ids[]={1,2,3},x[]={0,10000,18000},y[]={0,10000,18000};Pointer p;
 p.update(1,ids,x,y,1,250);assert(p.hasContact);x[0]=1000;assert(p.update(1,ids,x,y,2,250).dx>0);
 auto r=p.update(0,nullptr,nullptr,nullptr,3,250);assert(r.send && !r.click && !r.buttons);
 p={};p.update(1,ids,x,y,1,250);assert(p.update(0,nullptr,nullptr,nullptr,3,250).click);
 r=p.update(1,ids,x,y,20,250);assert(r.send && r.buttons==1);x[0]+=1500;
 assert(p.update(1,ids,x,y,21,250).buttons==1);assert(p.update(0,nullptr,nullptr,nullptr,22,250).buttons==0);
 p={};p.update(1,ids,x,y,1,250);assert(p.update(1,ids,x,y,300,250).buttons==1);
 r=p.update(1,ids,x,y,301,250,true);assert(r.send && r.buttons==0 && !r.click && !p.hasContact);
 p.update(2,ids,x,y,400,250);assert(p.update(0,nullptr,nullptr,nullptr,410,250).rightClick);
 p={};p.update(2,ids,x,y,420,250);assert(p.update(1,ids,x,y,430,250).rightClick);
 assert(!p.update(0,nullptr,nullptr,nullptr,440,250).rightClick);
 p={};p.update(2,ids,x,y,500,250);x[0]+=1000;x[1]+=1000;y[0]+=1000;y[1]+=1000;
 r=p.update(2,ids,x,y,510,250);assert(r.pan>0 && r.wheel<0 && !r.dx && !r.dy);
 r=p.update(1,ids,x,y,520,250);assert(r.send && !r.buttons);assert(!p.update(0,nullptr,nullptr,nullptr,530,250).click);
 p={};p.update(1,ids,x,y,600,250);int changed[]={7};r=p.update(1,changed,x,y,610,250);assert(r.send && !r.click && !r.buttons);
 p.update(0,nullptr,nullptr,nullptr,611,250);p.update(1,ids,x,y,700,250);
 r=p.update(3,ids,x,y,710,250);assert(r.send && !r.buttons);assert(!p.update(0,nullptr,nullptr,nullptr,720,250).click);
 p={};r=p.update(11,nullptr,nullptr,nullptr,0,250);assert(r.send);
 for(unsigned c=1;c<=10;++c) {r=p.update(c,nullptr,nullptr,nullptr,0,250);assert(r.send && !p.hasContact);}
 int limitsX[]={INT_MIN,INT_MAX},limitsY[]={INT_MAX,INT_MIN};
 p.update(2,ids,limitsX,limitsY,800,250);p.update(2,ids,limitsY,limitsX,810,250);p.update(0,nullptr,nullptr,nullptr,820,250);
}
static void formatting() {
 b5q_proc_window w={UINT64_MAX,UINT64_MAX,UINT64_MAX,10};b5q_proc_row rows[10]={};
 for(auto &r:rows) {memset(r.name,'X',sizeof r.name-1);r.count=UINT32_MAX;r.status=UINT16_MAX;}
 std::vector<std::string> lines;
 b5q_proc_print(w,rows,[](const char *s,void *p){assert(strlen(s)<200);static_cast<std::vector<std::string>*>(p)->emplace_back(s);},&lines);
 assert(lines.size()==12 && lines[1].find("TOP1 ")!=std::string::npos && lines[10].find("TOP10 ")!=std::string::npos && lines[11].find("overflow=18446744073709551615")!=std::string::npos);
}
int main(){descriptor();gestures();formatting();puts("PASS mouse descriptor/8B report, edges/tap/doubletap-drag/hold/recovery/right-click/XY-scroll/partial-lift/identity/palms/bounds; maximum ProcTop lines <200B");}
