#!/usr/bin/env python3
"""Review10: delayed ifnet, dynamic event names, USB role reset and BT IBS."""
from pathlib import Path
import importlib.util,subprocess,tempfile,tomllib

R=Path(__file__).resolve().parents[2];P=R/'UniXNU-b5q/package'
def function(text,signature):
    a=text.index(signature);b=text.index('{',a)+1;depth=1
    while depth:depth+=(text[b]=='{')-(text[b]=='}');b+=1
    return text[a:b]
def execute(root,name,body):
    src=root/(name+'.cpp');exe=root/name;src.write_text(body)
    subprocess.run(['c++','-std=c++17','-g','-O1','-Wall','-Wextra','-Werror',
        '-Wno-misleading-indentation','-fsanitize=address,undefined','-I'+str(P),str(src),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)

ethernet=(P/'B5qEthernet.cpp').read_text();wifi=(P/'B5qWifiBoard.cpp').read_text()
attached=function(ethernet,'extern "C" bool sheng_ethernet_wifi_attached(')
with tempfile.TemporaryDirectory(prefix='b5q-review10-')as td:
    t=Path(td)
    execute(t,'ethernet-attached',r'''
#include <cassert>
#include <cstdio>
using mbuf_t=void*;struct B5qEthernet{};
static B5qEthernet *volatile gController;static int (*volatile gWifiOutput)(mbuf_t);
int output(mbuf_t){return 0;}
ATTACHED
int main(){B5qEthernet c;assert(!sheng_ethernet_wifi_attached());
 __atomic_store_n(&gController,&c,__ATOMIC_RELEASE);assert(!sheng_ethernet_wifi_attached());
 __atomic_store_n(&gWifiOutput,&output,__ATOMIC_RELEASE);assert(sheng_ethernet_wifi_attached());
 __atomic_store_n(&gController,nullptr,__ATOMIC_RELEASE);assert(!sheng_ethernet_wifi_attached());
 puts("PASS production Ethernet callback attachment is independent of delayed ifnet naming");}
'''.replace('ATTACHED',attached))

    spec=importlib.util.spec_from_file_location('b5q_wifi',R/'UniXNU-b5q/scripts/b5q_wifi.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    selected=module.prepare(R/'sources/UniXNU-sheng',t/'generated');generated=selected.read_text()
    post=function(generated,'void post_event(')
    execute(t,'wifi-event-name',r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
struct If{const char*name;unsigned unit;};using ifnet_t=If*;If *gIf=nullptr,*fallback=nullptr;
const char *ifnet_name(ifnet_t p){return p->name;}unsigned ifnet_unit(ifnet_t p){return p->unit;}
ifnet_t sheng_ethernet_ifnet(){return fallback;}
struct DataVector{uint32_t data_length;void*data_ptr;};struct kev_msg{uint32_t vendor_code,kev_class,kev_subclass,event_code;DataVector dv[2];};
constexpr unsigned KEV_VENDOR_APPLE=1,kEvScanDone=10;char observed[16];
int sheng_kev_post(kev_msg*m){memcpy(observed,m->dv[0].data_ptr,sizeof observed);return 0;}
void log(int,const char*,...){}
POST
void verify(const char *name){assert(!strcmp(observed,name));for(unsigned i=4;i<sizeof observed;i++)assert(!observed[i]);}
int main(){If en1{"en",1};fallback=&en1;memset(observed,0xaa,sizeof observed);post_event(1,nullptr,0);verify("en1");
 gIf=&en1;fallback=nullptr;memset(observed,0xaa,sizeof observed);post_event(1,nullptr,0);verify("en1");
 gIf=nullptr;memset(observed,0xaa,sizeof observed);post_event(1,nullptr,0);verify("en0");
 puts("PASS generated Apple80211 event uses zero-filled live en1 and falls back to zero-filled en0 only before ifnet exists");}
'''.replace('POST',post))

    output=function(generated,'errno_t if_output(');ethernet_output=function(generated,'int ethernet_output(')
    execute(t,'wifi-delayed-tx',r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
struct If{};using ifnet_t=If*;struct Packet{uint8_t bytes[64]={};size_t length=64;bool freed=false;};using mbuf_t=Packet*;using errno_t=int;
If *gIf=nullptr,*fallback=nullptr;unsigned gTxRefused=0,stats=0,wakes=0;
ifnet_t sheng_ethernet_ifnet(){return fallback;}size_t mbuf_pkthdr_len(mbuf_t m){return m->length;}size_t mbuf_len(mbuf_t m){return m->length;}
void *mbuf_data(mbuf_t m){return m->bytes;}int mbuf_copydata(mbuf_t m,size_t off,size_t n,void*d){memcpy(d,m->bytes+off,n);return 0;}
void mbuf_freem(mbuf_t m){m->freed=true;}int mbuf_read(void *c,size_t o,void*d,size_t n){return mbuf_copydata(static_cast<mbuf_t>(c),o,n,d);}
void mbuf_release(void *c){mbuf_freem(static_cast<mbuf_t>(c));}void note_frame(const uint8_t*,size_t,bool){}
void note_packet(mbuf_t,size_t,int(*)(void*,size_t,void*,size_t),bool){}int nw_wifi_tx_packet(void*,size_t,int(*)(void*,size_t,void*,size_t),void(*)(void*)){return 0;}
void ifnet_stat_increment_out(ifnet_t ifp,unsigned,uint32_t,unsigned){assert(ifp);stats++;}void sheng_wifi_wake(){wakes++;}void log(int,const char*,...){}
IF_OUTPUT
ETHERNET_OUTPUT
int main(){Packet before;assert(!ethernet_output(&before)&&!gIf&&!stats&&wakes==1&&!before.freed);
 If en1;fallback=&en1;Packet after;assert(!ethernet_output(&after)&&gIf==&en1&&stats==1&&wakes==2&&!after.freed);
 puts("PASS generated Ethernet TX refreshes delayed ifnet and never dereferences null for output statistics");}
'''.replace('IF_OUTPUT',output).replace('ETHERNET_OUTPUT',ethernet_output))

    ready=function(wifi,'bool wifiReadyAccepted(')
    execute(t,'wifi-ready-retry',r'''
#include <cassert>
#include <cerrno>
#include <cstdint>
#include <cstdio>
READY
int main(){uint64_t next=17;assert(wifiReadyAccepted(0,100,next)&&next==17);assert(wifiReadyAccepted(EEXIST,200,next)&&next==17);
 assert(!wifiReadyAccepted(ENOENT,300,next)&&next==1300);assert(!wifiReadyAccepted(EIO,1300,next)&&next==2300);
 puts("PASS production Wi-Fi ready result accepts 0/EEXIST and schedules other failures exactly one second later");}
'''.replace('READY',ready))

    execute(t,'host-events',r'''
#include "B5qUsbHostEvent.h"
#include <cassert>
#include <cstdio>
#include <map>
#include <vector>
using namespace B5qUsbHostEvent;
int main(){std::map<uint64_t,uint64_t> memory;constexpr uint64_t table=0x1000,base=0x2000;
 memory[table]=base;memory[table+8]=16;
 for(unsigned i=0;i<16;i++){memory[base+i*16]=0xa000+i;uint32_t status=((20+i)<<24)|i;uint32_t control=(3u<<24)|(2u<<16)|((32u+i)<<10)|(i&1);memory[base+i*16+8]=status|(uint64_t(control)<<32);}
 auto read=[&](uint64_t pa,uint64_t&v){auto i=memory.find(pa);if(i==memory.end())return false;v=i->second;return true;};
 std::vector<unsigned> seen;assert(latest(table,1,base,4,read,[&](unsigned s,unsigned i,const Event&e){assert(!s&&e.slot==3&&e.endpoint==2&&e.type==32+i&&e.completion==20+i&&e.parameter==0xa000+i);seen.push_back(i);}));
 assert((seen==std::vector<unsigned>{15,14,13,12}));seen.clear();assert(latest(table,1,base+5*16,3,read,[&](unsigned,unsigned i,const Event&){seen.push_back(i);}));assert((seen==std::vector<unsigned>{4,3,2}));
 assert(!latest(table,65,base,1,read,[](unsigned,unsigned,const Event&){}));assert(!latest(table,1,0x5000,1,read,[](unsigned,unsigned,const Event&){}));
 memory.erase(base+15*16+8);assert(!latest(table,1,base,1,read,[](unsigned,unsigned,const Event&){}));
 puts("PASS bounded ERST/ERDP decoder: wrap, fields, invalid pointer/table and unreadable event rejected");}
''')

    usb=(P/'QcomDwc3.cpp').read_text();checkpoint=function(usb,'void hostCheckpoint(const char *reason,bool force,bool allowU3){')
    execute(t,'host-checkpoint-context',r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
constexpr unsigned kXhciRegisterBytes=0x8000;uint32_t regs[kXhciRegisterBytes/4]={};struct{volatile uint32_t*va=regs;}gXhciRegs;
unsigned diagnostics=0,syncs=0;char last[32]={};void dmaDiagnostics(const char*r){diagnostics++;snprintf(last,sizeof last,"%s",r);}
unsigned b5q_log_sync(unsigned ms){assert(ms==750);syncs++;return 1;}void IOLog(const char*,...){}
CHECKPOINT
int main(){constexpr unsigned cap=0x20;regs[0]=cap;auto &status=regs[(cap+4)/4];auto &port=regs[(cap+0x400)/4];
 port=0x60;hostCheckpoint("poll",false,true);assert(!diagnostics&&!syncs);
 port=0x63;hostCheckpoint("read64",false,false);hostCheckpoint("write64",false,false);assert(!diagnostics&&!syncs);
 hostCheckpoint("poll",false,true);assert(diagnostics==1&&syncs==1&&!strcmp(last,"first-U3"));
 status=4;hostCheckpoint("read64",false,false);assert(diagnostics==1&&syncs==1);hostCheckpoint("poll",false,true);assert(diagnostics==2&&syncs==2&&!strcmp(last,"first-HSE"));
 status=1u<<12;hostCheckpoint("poll",false,true);assert(diagnostics==3&&syncs==3&&!strcmp(last,"first-HCE"));
 puts("PASS production checkpoint keeps U3/HCE out of READ64/WRITE64, qualifies U3, and captures fatal HSE/HCE");}
'''.replace('CHECKPOINT',checkpoint))

assert 'if(!sheng_ethernet_wifi_attached())'in wifi
start=wifi.index('if(!netStarted && nw_wifi_stats.stage>=4)');ready_at=wifi.index('if(netStarted && !readyPublished && readyNow>=nextReadyTry && sheng_ethernet_ifnet())',start)
assert start<ready_at<wifi.index('if(nowMs()>=nextReport)',ready_at)
assert 'readyPublished=wifiReadyAccepted(ready,readyNow,nextReadyTry);'in wifi and 'nextTry=now+1000' in wifi
failed=wifi.index('failed:');order=[wifi.index(x,failed)for x in ['sheng_ethernet_wifi_detach();','nw_wifi_stop();','armcpu_spi_mask(800,true)','*command=uint16_t(*command&~4u)','h.pin(94,0x201,0)','b5q_wcn_radio_enable(B5Q_WCN_WLAN,0)']]
assert order==sorted(order)
assert generated.count('char name[16] = "en0"')==0 and 'char name[16] = {};'in generated and 'ifnet_name(ifp)'in generated and 'ifnet_unit(ifp)'in generated

board=(P/'B5qUsbBoard.cpp').read_text();bt=(P/'B5qBluetooth.cpp').read_text()
assert 'static volatile bool gDeviceStackAllowed = false;'in usb
publish=function(usb,'extern "C" void qcom_dwc3_publish(');assert 'QcomDwc3Nub::route(nub);'not in publish
core=function(usb,'bool setCoreRole(');assert core.index('*gctl|=1u<<11')<core.index('*gctl&=~(1u<<11)')<core.index('repeater(false')
assert '1u<<31'not in core and 'phyInit()'not in core and '*gctl&=~(1u<<11);barrier();IOSleep(1);'in core
assert 'hostCheckpoint("read64");'in usb and 'hostCheckpoint("write64");'in usb
assert 'hostCheckpoint("before-power-state",true,false);'in usb and 'hostCheckpoint("poll",false,true);'in usb
assert 'else if(!releaseTiReset())return false;'in board
for marker in ['GUSB2PHYCFG=%x','GUSB3PIPECTL=%x','GUCTL2=%x','PORTPMSC1=%x','PORTPMSC2=%x','host-event reason=','first-U3','first-HCE','kHostEventDumpCount=16','kUsbPortDebugOptions=0x40000019u']:assert marker in usb
assert 'pin(kRx,3u);'in bt and '(2u<<2)|(1u<<4)|(1u<<1)|1u' in bt and 'constexpr uint32_t kUartActive[]={4u,5u,7u,4u}'in bt
assert 'stage=ibs wake-ind='in bt

args=tomllib.loads((R/'UniXNU-b5q/board.toml').read_text())['payload']['kernel_args'];line=' '.join(args).encode('ascii')
assert len(line)==1023 and 'log-bluetooth=2'in args
assert int(next(x.split('=')[1]for x in args if x.startswith('debug=')),0)==0x14e
assert int(next(x.split('=')[1]for x in args if x.startswith('validation_disables=')),0)==0x11040
spec=importlib.util.spec_from_file_location('b5q_menu',R/'UniXNU-b5q/scripts/b5q_menu.py');menu=importlib.util.module_from_spec(spec);spec.loader.exec_module(menu)
profiles=menu.profiles(args);assert profiles[0]['args'].endswith('b5q-dp=1') and 'log-bluetooth=2'in profiles[0]['args'].split()
assert all(len(p['args'].encode())<=1023 for p in profiles) and all('log-bluetooth=2'not in p['args'].split() for p in profiles[1:])
print('PASS review10 source ordering, Wi-Fi teardown/readiness, USB reset/diagnostics, Bluetooth TLMM/IBS and 1023-byte boot args')
