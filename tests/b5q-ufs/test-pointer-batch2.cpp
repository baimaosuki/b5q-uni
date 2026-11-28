#include <cassert>
#include <cstdio>
#include <climits>
#include <cstring>
#include <vector>
#include <string>
#include "B5qTouchMouse.h"
#include "B5qMouseReport.h"
#include "B5qProcTopFormat.h"

static void descriptor() {
 unsigned page=0,size=0,count=0,report=0,bits=0,minimum=0,maximum=0,unit=0,exponent=0,physicalMin=0,physicalMax=0;
 struct Global{unsigned page,size,count,report,minimum,maximum,unit,exponent,physicalMin,physicalMax;};
 std::vector<Global> stack;
 std::vector<unsigned> usages;bool buttons=false,xy=false,wheel=false,pan=false;
 for(unsigned i=0;i<sizeof(mouseDescriptor);) {
  unsigned key=mouseDescriptor[i++],n=key&3;if(n==3)n=4;
  assert(key!=0xfe && i+n<=sizeof(mouseDescriptor));unsigned value=0;
  for(unsigned j=0;j<n;++j)value|=unsigned(mouseDescriptor[i++])<<(8*j);
  switch(key&0xfc) {
   case 0x04:page=value;break;case 0x08:usages.push_back(value);break;
   case 0x18:minimum=value;break;case 0x28:maximum=value;break;
   case 0x74:size=value;break;case 0x94:count=value;break;case 0x84:report=value;break;
   case 0xa4:stack.push_back({page,size,count,report,minimum,maximum,unit,exponent,physicalMin,physicalMax});break;
   case 0xb4:{assert(!stack.empty());auto g=stack.back();stack.pop_back();page=g.page;size=g.size;count=g.count;report=g.report;minimum=g.minimum;maximum=g.maximum;unit=g.unit;exponent=g.exponent;physicalMin=g.physicalMin;physicalMax=g.physicalMax;}break;
   case 0x64:unit=value;break;case 0x54:exponent=value;break;case 0x34:physicalMin=value;break;case 0x44:physicalMax=value;break;
   case 0xa0:usages.clear();break;
   case 0x80:
    assert(report==0x1a);bits+=size*count;
    if(page==9 && size==1 && count==2) {assert(minimum==1 && maximum==2 && value==2);buttons=true;}
    if(page==1 && size==16 && count==2) {assert(usages.size()==2 && usages[0]==0x30 && usages[1]==0x31 && value==6);assert(unit==0x13&&exponent==0xe&&physicalMin==0xfffff1c7&&physicalMax==0xe39);assert(32767.0/(physicalMax*0.01)>800&&32767.0/(physicalMax*0.01)<1000);xy=true;}
    if(page==1 && size==8 && usages.size()==1 && usages[0]==0x38) {assert(value==6&&unit==0&&exponent==0&&physicalMin==0&&physicalMax==0);wheel=true;}
    if(page==0xc && size==8 && usages.size()==1 && usages[0]==0x238) {assert(value==6&&unit==0&&exponent==0&&physicalMin==0&&physicalMax==0);pan=true;}
    usages.clear();break;
  }
 }
 assert(bits==56 && buttons && xy && wheel && pan);
 unsigned char r[8];b5q_mouse_report(r,3,-32767,32767,-127,127);
 assert(r[0]==0x1a && r[1]==3 && r[2]==1 && r[3]==0x80 && r[4]==0xff && r[5]==0x7f && r[6]==0x81 && r[7]==0x7f);
}
static void gestures() {
 B5qTouchMouse p;unsigned press=0,release=0,move=0;
 int ids[]={1,2,3},x[]={1000,2000,3000},y[]={1000,2000,3000};
 auto send=[&](const uint8_t *r){assert(r[0]==0x1a);if(r[1])++press;else ++release;if(r[2]||r[3]||r[4]||r[5])++move;};
 p.update(1,ids,x,y,1,false,send);p.update(0,nullptr,nullptr,nullptr,20,false,send);p.advance(52,send);
 assert(press==1&&release==1);
 p.update(3,ids,x,y,100,false,send);p.update(1,ids,x,y,113,false,send);
 x[0]+=1000;p.update(1,ids,x,y,126,false,send);assert(move==1);
 p.update(0,nullptr,nullptr,nullptr,140,true,send);assert(!p.fingers);
 // Full lifetime and differential upstream coverage: test-touch-p0.py.
}
static void formatting() {
 b5q_proc_window w={UINT64_MAX,UINT64_MAX,UINT64_MAX,10};b5q_proc_row rows[10]={};
 for(auto &r:rows) {memset(r.name,'X',sizeof r.name-1);r.count=UINT32_MAX;r.status=UINT16_MAX;}
 std::vector<std::string> lines;
 b5q_proc_print(w,rows,[](const char *s,void *p){assert(strlen(s)<200);static_cast<std::vector<std::string>*>(p)->emplace_back(s);},&lines);
 assert(lines.size()==12 && lines[1].find("TOP1 ")!=std::string::npos && lines[10].find("TOP10 ")!=std::string::npos && lines[11].find("overflow=18446744073709551615")!=std::string::npos);
}
int main(){descriptor();gestures();formatting();puts("PASS mouse descriptor/8B report, upstream tap/multifinger recovery/movement; maximum ProcTop lines <200B");}
