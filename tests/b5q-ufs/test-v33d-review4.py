#!/usr/bin/env python3
"""Production-path host regressions for the four v33d hardware-log repairs."""
from pathlib import Path
import json,subprocess,tempfile,re
R=Path(__file__).resolve().parents[2];P=R/'UniXNU-b5q/package'
ns={'__file__':str(R/'tests/b5q-ufs/test-v33d-review2.py')};s=(R/'tests/b5q-ufs/test-v33d-review2.py').read_text();exec(compile(s[:s.index("run('BCM-ARC'")],'<host-runner>','exec'),ns)
f,run,base=ns['function'],ns['run'],ns['base']
touch=(P/'B5qTouch.cpp').read_text();worker=f(touch,'void worker(')
a=worker.index('  for(unsigned drained=0;');b=worker.index('  stage="enable-report";',a);identify=worker[a:b]
run('touch-identify-log',base+r'''
#include <tuple>
#include "B5qTouchProtocol.h"
uint8_t message[4096],config[512];size_t configBytes;unsigned maxObjects;
struct Packet{unsigned code,mode,bytes;};
std::deque<Packet> pending;unsigned writes=0,readPackets=0,reports=0,sleeps=0;
bool failPacket=false;
struct TouchBus{bool write(uint8_t*,unsigned){writes++;return true;}int error(){return 0;}int stopError(){return 0;}};
namespace B5qTouchBus{const char*name(int){return "none";}}
void IOLog(const char*,...){}void IOSleep(unsigned){sleeps++;}bool lowAttention(){return !pending.empty();}
bool packet(TouchBus&,uint8_t &c,unsigned &n){readPackets++;if(failPacket)return false;auto p=pending.front();pending.pop_front();c=p.code;n=p.bytes;message[1]=p.mode;return true;}
void report(uint8_t,unsigned){reports++;}
COMMAND
void bootIdentify(TouchBus &bus){const char *stage="identify";do{DRAIN}while(false);}
int main(){TouchBus bus;
 for(unsigned code:{0x10u,1u})for(unsigned mode:{1u,2u}){pending={{code,mode,24}};assert(command(bus,2,nullptr,0)==(mode==1));assert(pending.empty()&&!reports&&!sleeps);}
 pending={{0x10,1,1}};assert(!command(bus,2,nullptr,0));
 // Boot ATTN can be stuck or contain more than eight packets; the actual
 // worker drain is bounded and a packet failure stops draining immediately.
 pending.assign(12,{0x10,1,24});writes=readPackets=0;bootIdentify(bus);assert(readPackets==9&&writes==1&&pending.size()==3);
 pending.assign(12,{0x10,1,24});writes=readPackets=0;failPacket=true;bootIdentify(bus);assert(readPackets==2&&writes==1);failPacket=false;
 puts("PASS actual TouchComm CMD02:REPORT_IDENTIFY10 mode1/24B succeeds,mode2 rejects;response01 succeeds; shortpayloadreject; precommandATTNdrain<=8 and failurebounded");}
'''.replace('COMMAND',f(touch,'bool command(')).replace('DRAIN',identify))
board=(P/'B5qUsbBoard.cpp').read_text()
run('maxim-ready-recovery',base+r'''
#include <mutex>
#include <atomic>
#include <thread>
#include "B5qMax77705.h"
std::atomic<unsigned> opens{0},lives{0},waits{0};std::atomic<uint64_t> ms{1000};
std::atomic<bool> entered{false},releaseOpen{true},complete{false};bool failOpen=false;unsigned releaseAfter=0;
std::mutex busLock;
struct Bus{std::mutex *lock=&busLock;uint8_t reg[256]={};
 Bus(){lives++;reg[0xb7]=5;reg[0xb2]=4;reg[0xc3]=0x40;}~Bus(){lives--;}
 bool open(bool hub){assert(hub);opens++;entered=true;while(!releaseOpen)std::this_thread::yield();return !failOpen;}
 bool read(uint8_t address,uint8_t r,uint8_t &v){if(address==0x66)v=r?2:0x15;else if(address==0x25)v=r==0xa?0x42:r==0xd?0x80:0;else{assert(address==0x69);v=reg[r];}return true;}
 bool write(uint8_t a,uint8_t r,uint8_t v){assert(a==0x69);reg[r]=v;return true;}};
Bus *maxim=nullptr;bool maximReady=false,otgOn=false;volatile unsigned maximBusState=0;
void IOSleep(unsigned n){ms+=n;unsigned at=++waits;if(releaseAfter&&at==releaseAfter){releaseOpen=true;while(!complete)std::this_thread::yield();}std::this_thread::yield();}
void IODelay(unsigned){}void IOLockLock(std::mutex*m){m->lock();}void IOLockUnlock(std::mutex*m){m->unlock();}
uint64_t mach_absolute_time(){return ms*1000000;}void absolutetime_to_nanoseconds(uint64_t t,uint64_t *n){*n=t;}
void IOLog(const char*,...){}
OPEN
INIT
ENSURE
CABLE
OTG
void reset(){delete maxim;maxim=nullptr;maximReady=false;otgOn=false;maximBusState=0;waits=0;releaseAfter=0;failOpen=false;entered=false;releaseOpen=true;complete=false;ms+=1001;}
int main(){
 // Battery owns SE8 for1.2s: the USB caller now waits past the former1s cutoff.
 reset();releaseOpen=false;releaseAfter=120;std::thread battery([]{assert(openMaxim());complete=true;});while(!entered)std::this_thread::yield();
 assert(b5q_usb_typec_init()&&maximReady&&waits==120);battery.join();B5qMax77705::Cable cable;assert(b5q_usb_cable_state(&cable)&&cable.valid);assert(b5q_usb_otg(true)&&otgOn);
 // Even a full6s timeout is not terminal: a late successful battery open is
 // discovered immediately by both public consumers without a reboot.
 for(bool useOtg:{false,true}){reset();releaseOpen=false;std::thread owner([]{assert(openMaxim());complete=true;});while(!entered)std::this_thread::yield();
  assert(!b5q_usb_typec_init()&&!maximReady&&waits==600);releaseOpen=true;owner.join();
  assert(maximBusState==2);if(useOtg)assert(b5q_usb_otg(true)&&otgOn);else assert(b5q_usb_cable_state(&cable)&&cable.valid);assert(maximReady);
 }
 reset();failOpen=true;unsigned before=opens;assert(!b5q_usb_cable_state(&cable)&&maximBusState==0&&opens==before+1&&!lives);
 assert(!b5q_usb_otg(true)&&opens==before+1); // throttled within1s
 failOpen=false;ms+=1001;assert(b5q_usb_cable_state(&cable)&&maximReady&&opens==before+2);assert(b5q_usb_otg(true));
 reset();assert(!lives);
 puts("PASS production MAXIM recovery:concurrent1.2sSE8open,6sboundedtimeout,latebusready auto-recovers cable andOTG; failedopen returnsstate0,1sthrottle and retry succeed");}
'''.replace('OPEN',f(board,'bool openMaxim(')).replace('INIT',f(board,'extern "C" bool b5q_usb_typec_init(')).replace('ENSURE',f(board,'bool ensureMaximReady(')).replace('CABLE',f(board,'extern "C" bool b5q_usb_cable_state(')).replace('\nOTG\n','\n'+f(board,'extern "C" bool b5q_usb_otg(')+'\n'))
q=(P/'QcomDwc3.cpp').read_text();role=f(q,'bool setCoreRole(')
run('core-only-reset',base+r'''
constexpr int kRoleHost=2,kRoleDevice=1;bool gDeviceStackAllowed=true;int gCoreRole=1;
std::vector<unsigned> steps;
struct Reg{unsigned index=0;uint32_t value=0;operator uint32_t()const{return value;}
 Reg&operator=(uint32_t v){if(index==0x200/4||index==0x2c0/4)assert(!(v&(1u<<31)));value=v;steps.push_back(index);return *this;}
 void operator|=(uint32_t v){*this=value|v;}void operator&=(uint32_t v){*this=value&v;}};
Reg regs[1024];struct{Reg*va=regs;}gGlobals;
struct QcomDwc3Nub{static void route(void*p){assert(!p);}};
void barrier(){}void IOSleep(unsigned ms){assert(ms==100);assert(regs[0x110/4].value&(1u<<11));}
bool repeater(bool,bool){return true;}
ROLE
int main(){for(unsigned i=0;i<1024;i++)regs[i].index=i;
 regs[0x110/4].value=0x81400000|(2u<<12);regs[0x200/4].value=(1u<<6)|(1u<<8)|3;regs[0x2c0/4].value=(1u<<17)|5;
 assert(setCoreRole(2,true));assert((steps==std::vector<unsigned>{0x110/4,0x110/4,0x110/4,0x200/4,0x2c0/4}));
 assert(!(regs[0x110/4].value&(1u<<11))&&((regs[0x110/4].value>>12)&3)==1&&(regs[0x110/4].value&1));
 assert(regs[0x200/4].value==3&&regs[0x2c0/4].value==5&&!gDeviceStackAllowed);
 puts("PASS actual setCoreRole:CORESOFTRESET set/wait/clear thenPRTCAPDIR; cleanUSBquirks,zeroPHYSOFTRSTbit31 afterQMP");}
'''.replace('ROLE',role))
write64=f(q,'void XHCI_WRITE64(').replace(' override','')
write64=write64.replace('volatile uint32_t *at = reinterpret_cast<volatile uint32_t *>(static_cast<uint8_t *>(base) + offset);','Reg *at = static_cast<Model *>(base)->at(offset);')
run('xhci-write64-causal',base+r'''
#include <cstdarg>
struct Model;
struct Reg{Model*m=nullptr;unsigned half=0;operator uint32_t()const;void operator=(uint32_t);};
struct Model{Reg words[2]={{this,0},{this,1}};unsigned off=0;bool reverseLatch=false,dropAll=false;uint32_t staged[2]={},visible[2]={};std::vector<unsigned> order;
 Reg*at(unsigned n){off=n;return words;}};
Reg::operator uint32_t()const{return m->visible[half];}
void Reg::operator=(uint32_t v){m->order.push_back(half);m->staged[half]=v;
 // A controller latches its register only on its required terminal halfwrite.
 // The alternate-half model discards the failed firstorder, exposing allzero.
 if(m->dropAll)return;
 if(!m->reverseLatch){if(half==0){m->visible[0]=m->staged[0];m->visible[1]=m->staged[1];}}
 else if(half==1){if(m->order.size()>=2&&m->order[m->order.size()-2]==0){m->visible[0]=m->staged[0];m->visible[1]=m->staged[1];}}}
unsigned logs=0,rb2=0,syncs=0,checkpoints=0;void dmaDiagnostics(const char*){}
void hostCheckpoint(const char*,bool=false){checkpoints++;}
unsigned b5q_log_sync(unsigned n){assert(n==750);syncs++;return 0;}
void IOLog(const char *fmt,...){logs++;if(strstr(fmt,"rb2="))rb2++;}void barrier(){}
WRITE
int main(){uint64_t value=0x88ba04000ULL;Model normal;XHCI_WRITE64(&normal,0x30,value);assert((normal.order==std::vector<unsigned>{1,0})&&normal.visible[0]==uint32_t(value)&&normal.visible[1]==8&&logs==1&&!rb2);
 Model alternate;alternate.reverseLatch=true;XHCI_WRITE64(&alternate,0x30,value);assert((alternate.order==std::vector<unsigned>{1,0,0,1})&&alternate.visible[0]==uint32_t(value)&&alternate.visible[1]==8&&rb2==1);
 Model crcr;crcr.reverseLatch=true;XHCI_WRITE64(&crcr,0x18,value);assert(crcr.order.size()==2&&!crcr.visible[0]&&!crcr.visible[1]&&rb2==1);
 Model zero;XHCI_WRITE64(&zero,0x38,0);assert(zero.order.size()==2&&logs==5);
 Model irrelevant;XHCI_WRITE64(&irrelevant,0x10,0);assert(irrelevant.order.size()==2&&logs==5);
 for(unsigned i=5;i<16;i++){Model ok;XHCI_WRITE64(&ok,0x30,value);}assert(logs==16);
 Model after;after.reverseLatch=true;XHCI_WRITE64(&after,0x30,value);assert(after.order.size()==2&&logs==16);
 assert(syncs==14&&checkpoints>=17);
 puts("PASS production XHCI_WRITE64:64bitPA88ba04000,hi/lo-latch andlo/hi-only-latch,originalvalue fallback,CRCR excluded,zero writes,first16calls bounded");}
'''.replace('\nWRITE\n','\n'+write64+'\n'))
abi=json.loads((R/'UniXNU-b5q/scripts/usb-xhci-26C5035r.json').read_text());assert abi['overrides']['421']=='XHCI_WRITE64' if 'overrides'in abi else '"421": "XHCI_WRITE64"'in json.dumps(abi)
assert '(1u<<31)'not in role and '1u << 31'not in role
assert '(id==1||id==2||id==3)?32'in board and 'pdic-raw id=%02x'in board
print('PASS sourcecontracts:DiscoverModes32bytes,raw16bytefailurelog,write64signature preserved atslot421/0xd28')
