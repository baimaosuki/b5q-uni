#!/usr/bin/env python3
"""Review8 regressions use actual generated ops and production PDIC mailbox."""
from pathlib import Path
import hashlib,importlib.util,re,subprocess,tempfile
R=Path(__file__).resolve().parents[2];P=R/'UniXNU-b5q/package'
spec=importlib.util.spec_from_file_location('ath11k',R/'UniXNU-b5q/scripts/build-b5q-wifi.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
with tempfile.TemporaryDirectory(prefix='b5q-review8-wifi-')as td:
 t=Path(td);gen=module.prepare(R/'sources/UniXNU-sheng/drivers/Ath12kWifi',t)
 s=(gen/'mac.c').read_text();ops=s.split('static const struct ieee80211_ops ath11k_ops = {',1)[1].split('};',1)[0]
 keys=re.findall(r'\.(\w+)\s*=',ops);assert 'bss_info_changed'not in keys and keys.count('link_info_changed')==keys.count('vif_cfg_changed')==1
 main=(R/'sources/UniXNU-sheng/drivers/Ath12kWifi/out/mac80211/main.c').read_text();a=main.index('\tif (WARN_ON(!!ops->link_info_changed');b=main.index('\n\n',a);guard=main[a:b]
 (t/'test.c').write_text('''#include <assert.h>
#include <stddef.h>
struct ops {int link_info_changed,vif_cfg_changed,bss_info_changed;};
#define WARN_ON(x) (x)
void *allocate(struct ops *ops){GUARD\nreturn ops;}
int main(){struct ops actual={1,1,0};assert(allocate(&actual));for(int i=1;i<8;i++){struct ops bad={i&1,i&2,i&4};if(((!!bad.link_info_changed)!=(!!bad.vif_cfg_changed))||(bad.link_info_changed&&bad.bss_info_changed))assert(!allocate(&bad));}return 0;}
'''.replace('GUARD',guard))
 subprocess.run(['cc','-fsanitize=address,undefined',str(t/'test.c'),'-o',str(t/'test')],check=True);subprocess.run([str(t/'test')],check=True)
print('PASS actualgeneratedath11k_ops splitpaironly;originalmac80211mutualexclusionpredicate/allnegativecombinations')
subprocess.run(['python3',str(R/'tests/b5q-ufs/test-touch-wait.py')],check=True)
# All CC control transactions run through the actual shared mailbox. Replies
# are produced only when the model receives the mailbox execute/end write.
body=r'''
#include <cassert>
#include <cstdio>
#include <cstring>
#include <vector>
#include "B5qMax77705.h"
#include "B5qDpPdic.h"
struct Io {
 uint8_t ctrl=0xa0,cc0=0,cc1=0,pd0=7,pd1=7,bc=0,opcode=0,value=0;bool pending=false,reply=false,timeout=false,wrong=false,rejectWrite=false,readFail=false,attachDuringRead=false;
 unsigned writes=0,reads=0,ctrlReads=0;uint64_t time=0;
 std::vector<unsigned>operations;
 bool connected(){return !(cc1&2);}void delay(unsigned us){time+=us;}uint64_t nowUs(){return time;}
 bool read(uint8_t address,uint8_t reg,uint8_t &v){assert(address==0x25);if(readFail)return false;v=reg==0xa?cc0:reg==0xb?cc1:reg==0xc?pd0:reg==0xd?pd1:bc;return true;}
 bool write(uint8_t address,const uint8_t*p,unsigned n){assert(address==0x25&&n>=2);
  if(p[0]==0x21){assert(!pending);opcode=p[1];assert(opcode==0xb||opcode==0xc);assert(n==(opcode==0xc?3u:2u));if(n==3)value=p[2];pending=true;reply=false;}
  else {assert(p[0]==0x41&&n==2&&pending);pending=false;reply=!timeout;operations.push_back(opcode);if(opcode==0xc){writes++;if(!rejectWrite)ctrl=value;}else{ctrlReads++;if(attachDuringRead){cc0=0x49;bc=0x80;}}}
  return true;
 }
 bool read(uint8_t address,uint8_t reg,uint8_t*p,unsigned n){assert(address==0x25&&n==1);reads++;if(readFail)return false;
  if(reg==2){*p=reply?0x80:0;return true;}assert(reply);if(reg==0x51)*p=wrong?0xff:opcode;else{assert(reg==0x52);*p=ctrl;reply=false;}return true;
 }
};
int main(){
 for(unsigned before=0;before<256;before++){
  Io io;io.ctrl=before;B5qDp::Mailbox<Io> m(io);B5qMax77705::DrpState s;
  assert(B5qMax77705::configureDrp(io,m,s));assert(s.stage==5&&io.ctrl==(before|0x19));assert((io.ctrl&0xe0)==(before&0xe0));
  assert(io.writes==unsigned((before&0x19)!=0x19));assert(io.operations==(io.writes?std::vector<unsigned>{0xb,0xc,0xb}:std::vector<unsigned>{0xb}));
 }
 for(unsigned cc:{0x41u,0x81u,0x42u,0x82u}){Io io;io.cc0=cc;io.bc=0x80;B5qDp::Mailbox<Io>m(io);B5qMax77705::DrpState s;assert(B5qMax77705::configureDrp(io,m,s)&&s.deferred&&!io.writes&&io.ctrl==0xa0);}
 {Io io;io.bc=0x80;B5qDp::Mailbox<Io>m(io);B5qMax77705::DrpState s;assert(B5qMax77705::configureDrp(io,m,s)&&s.deferred&&!io.writes);}
 {Io io;io.attachDuringRead=true;B5qDp::Mailbox<Io>m(io);B5qMax77705::DrpState s;assert(B5qMax77705::configureDrp(io,m,s)&&s.deferred&&!io.writes);}
 for(unsigned fail=0;fail<5;fail++){
  Io io;io.timeout=fail==0;io.wrong=fail==1;io.rejectWrite=fail==2;io.readFail=fail==3;io.cc1=fail==4?2:0;
  B5qDp::Mailbox<Io>m(io);B5qMax77705::DrpState s;assert(!B5qMax77705::configureDrp(io,m,s));
  if(fail!=2)assert(!io.writes);if(fail==0)assert(io.time==500000);
 }
 // Source enabled by DRP negotiates the native source role. Own VBUS must
 // retain its already verified stable cable signature across ordinary OTG.
 Io io;B5qDp::Mailbox<Io>m(io);B5qMax77705::DrpState s;assert(B5qMax77705::configureDrp(io,m,s));
 io.cc0=0x4a;io.pd1=0x87;B5qMax77705::Cable c;assert(B5qMax77705::readCable(io,c)&&c.role()==2&&c.sourceVbus(2));auto signature=c.signature();io.bc=0x80;io.cc1=9;assert(B5qMax77705::readCable(io,c)&&c.signature()==signature);
 puts("PASSactualPDICmailbox256CCCTRL1RMW/highcurrentpreserved;read/write/readsequence;liveDevice/Source/VBUS/race/water/timeout/wrongopcode/rejectreadbacknegative;nativeHostVBUSsignaturestable");
}
'''
with tempfile.TemporaryDirectory(prefix='b5q-review8-drp-')as td:
 t=Path(td);(t/'test.cpp').write_text(body)
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=address,undefined','-I'+str(P),str(t/'test.cpp'),'-o',str(t/'test')],check=True);subprocess.run([str(t/'test')],check=True)
# Execute actual board wiring: DRP init owns SE8 across request/response;
# fast VCONN candidates log cached readback without a blocking opcode.
board=(P/'B5qUsbBoard.cpp').read_text()
def function(text,signature):
 a=text.index(signature);b=text.index('{',a)+1;depth=1
 while depth:depth+=(text[b]=='{')-(text[b]=='}');b+=1
 return text[a:b]
start=board.index('struct CcControlIo {');end=board.index('\n}\nextern "C" bool b5q_usb_typec_init',start)
helpers=board[start:end]
fixture=body[:body.index('int main(){')]+r'''
#include <cstdarg>
Io model;bool held=false,maximReady=false;unsigned controls=0,diagnostics=0;uint32_t lastCc[4]={};
void IOLockLock(void*){assert(!held);held=true;}void IOLockUnlock(void*){assert(held);held=false;}
struct Bus{void *lock=this;
 bool read(uint8_t address,uint8_t reg,uint8_t&v){assert(held);if(address==0x66){v=reg?1:0x15;return true;}return model.read(address,reg,v);}
 bool readBuffer(uint8_t a,uint8_t r,uint8_t*p,unsigned n){assert(held);return model.read(a,r,p,n);}
 bool writeBuffer(uint8_t a,const uint8_t*p,unsigned n){assert(held);return model.write(a,p,n);}
}bus,*maxim=&bus;
bool openMaxim(){return true;}
void IOSleep(unsigned ms){model.time+=ms*1000;}void IODelay(unsigned us){model.time+=us;}
uint64_t mach_absolute_time(){return model.time*1000;}void absolutetime_to_nanoseconds(uint64_t v,uint64_t*p){*p=v;}
void IOLog(const char *format,...){
 if(strstr(format," DRP stage="))controls++;
 if(strstr(format,"CC-diag")){
  diagnostics++;va_list ap;va_start(ap,format);
  assert(!va_arg(ap,int));(void)va_arg(ap,unsigned);assert(va_arg(ap,int)==model.ctrl);assert(va_arg(ap,int));
  for(auto &v:lastCc)v=va_arg(ap,int);va_end(ap);
 }
}
HELPERS
INIT
CABLE
bool ensureMaximReady(){return maximReady;}
int main(){
 assert(b5q_usb_typec_init()&&maximReady&&controls==1&&!held&&model.ctrl==0xb9&&model.writes==1);
 const auto queries=model.ctrlReads;const auto began=model.time;model.timeout=true;
 model.cc0=0x48;model.cc1=0;model.pd0=0x5a;model.pd1=7;B5qMax77705::Cable c;
 assert(b5q_usb_cable_state(&c)&&diagnostics==1&&!held);assert(lastCc[0]==0x48&&lastCc[1]==0&&lastCc[2]==0x5a&&lastCc[3]==7);
 assert(b5q_usb_cable_state(&c)&&diagnostics==1);model.cc0=0x88;
 assert(b5q_usb_cable_state(&c)&&diagnostics==2&&lastCc[0]==0x88);
 assert(model.ctrlReads==queries&&model.time==began); // mailbox timeout cannot consume the VBUS window
 model={};model.cc0=0x49;model.bc=0x80;
 assert(b5q_usb_typec_init()&&model.writes==0&&model.ctrl==0xa0&&maximReady); // Device session preserved
 model.timeout=true;assert(b5q_usb_typec_init()&&maximReady&&model.writes==0); // mailbox error never tears down live Device
 puts("PASS actualboardinit/control/mailbox/CC48+88diagnostic underSE8lock;cachedreadback/zeroopcodewaitonVCONNtransition;limitduplicatequeries;liveDevicepreservedincludingopcodefailure");
}
'''
fixture=fixture.replace('HELPERS',helpers).replace('INIT',function(board,'extern "C" bool b5q_usb_typec_init(')).replace('CABLE',function(board,'extern "C" bool b5q_usb_cable_state('))
# The forward declaration matches production call order; no behavior is mocked.
fixture=fixture.replace('\nextern "C" bool b5q_usb_cable_state','\nbool ensureMaximReady();\nextern "C" bool b5q_usb_cable_state')
with tempfile.TemporaryDirectory(prefix='b5q-review8-board-')as td:
 t=Path(td);(t/'test.cpp').write_text(fixture)
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=address,undefined','-I'+str(P),str(t/'test.cpp'),'-o',str(t/'test')],check=True);subprocess.run([str(t/'test')],check=True)
# Ignore logging samples are bounded even for short status payloads; ASan
# guards the front-eight-byte loop against reading beyond a one-byte packet.
touch=(P/'B5qTouch.cpp').read_text()
fixture=r'''
#include <cassert>
#include <cstdio>
#include <cstring>
#include <cstdarg>
#include "B5qTouchReports.h"
B5qTouch::Reports reports;uint8_t *message,config[1]={};unsigned configBytes=0,maxObjects=10,layoutFailures=0;
unsigned samples=0;void publish(bool=true){}
void IOLog(const char*fmt,...){if(strstr(fmt,"ignored-report")){samples++;va_list ap;va_start(ap,fmt);assert(va_arg(ap,unsigned)==samples);auto code=va_arg(ap,unsigned);auto n=va_arg(ap,unsigned);auto hex=va_arg(ap,const char*);assert(code!=0x11&&strlen(hex)==3*(n<8?n:8));va_end(ap);}}
REPORT
int main(){reports.mode=0x11;uint8_t one[]={0x12},many[16]={};message=one;for(unsigned i=0;i<3;i++)report(1,1);message=many;for(unsigned i=0;i<20;i++)report(7,16);assert(samples==5);puts("PASSactualconsumeignorednon11logsfirst5only,payloadlength1and16,front8bounded");}
'''.replace('REPORT',function(touch,'void report('))
with tempfile.TemporaryDirectory(prefix='b5q-review8-ignored-')as td:
 t=Path(td);(t/'test.cpp').write_text(fixture)
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=address,undefined','-I'+str(P),str(t/'test.cpp'),'-o',str(t/'test')],check=True);subprocess.run([str(t/'test')],check=True)
