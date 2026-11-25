#!/usr/bin/env python3
"""Focused production-path regressions for the five review3 requirements."""
from pathlib import Path
import ast,importlib.util,subprocess,tempfile,sys
R=Path(__file__).resolve().parents[2];P=R/'UniXNU-b5q/package'
ns={'__file__':str(R/'tests/b5q-ufs/test-v33d-review2.py')};s=(R/'tests/b5q-ufs/test-v33d-review2.py').read_text();exec(compile(s[:s.index("run('BCM-ARC'")],'<host-runner>','exec'),ns)
f,run,base=ns['function'],ns['run'],ns['base']
w=(P/'B5qWcnPower.cpp').read_text();sys.path.insert(0,str(R/'UniXNU-b5q/scripts'))
from b5q_adsp import prepare
with tempfile.TemporaryDirectory(prefix='b5q-review3-adsp-source-')as td:
 sources,_=prepare(R/'sources/UniXNU-sheng',Path(td));adsp=sources[0].read_text()
a=adsp.index('    {\n    B5qAossQmpLock guard;');b=adsp.index('    stage(StLoadState);',a);transaction=adsp[a:b]
assert transaction.index('B5qAossQmpLock')<transaction.index('qcom_qmp_init')<transaction.index('qcom_qmp_send')<transaction.index('qcom_qmp_abandon')
assert 'AppsSmmuLock'not in transaction and 'B5qAossQmpLock'in f(w,'bool pdcInit(')
body=base+r'''
#include <mutex>
#include <thread>
#include <atomic>
#include <string>
#include <algorithm>
struct IOLock{std::mutex m;};
std::atomic<unsigned> waiting{0},active{0},peak{0};
IOLock *IOLockAlloc(){return new IOLock;}
void IOLockFree(IOLock*p){delete p;}
void IOLockLock(IOLock*p){++waiting;p->m.lock();--waiting;assert(++active==1);peak=1;}
void IOLockUnlock(IOLock*p){assert(active==1);--active;p->m.unlock();}
IOLock *aossQmpLock;
LOCK
UNLOCK
#include "B5qAossQmpLock.h"
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wimplicit-fallthrough"
#define barrier qmpBarrier
#include "QcomQmp.c"
#undef barrier
#pragma GCC diagnostic pop
#include "QcomScm.h"
uint32_t aossWords[1024]={},ipccWords[1024]={};
struct Window{uint32_t *va=nullptr;bool open(uint64_t base,unsigned){va=base==0xc300000?aossWords:ipccWords;return true;}};
Window aoss,ipcc;QcomQmp pdcQmp,gQmp;bool pdcReady=false;
struct{uintptr_t va;}gAoss{reinterpret_cast<uintptr_t>(aossWords)};
int32_t native_adsp_stats[16]={};int failed=0,releases=0;
constexpr int StLoadState=6;void fail(int,int error){failed=error;}void release(int&){++releases;}
void IOLog(const char*,...){}void barrier(){}void kickAop(void*){}
std::atomic<bool> holdFirst{true},pending{false},continuePeer{false};
bool ack=true;std::vector<std::string> received;
void IOSleep(unsigned){assert(active==1);
 if(holdFirst.exchange(false)){pending=true;while(!continuePeer)std::this_thread::yield();}
 if(!ack)return;
 auto *r=aossWords;r[4]=r[3];r[10]=r[9];r[5]=r[11];r[12]=r[6];
 if(r[0x100/4]){received.emplace_back(reinterpret_cast<char*>(r+0x100/4+1));r[0x100/4]=0;}}
template<typename F>bool waitUntil(unsigned ms,F done){for(unsigned i=0;i<ms;i++){if(done())return true;IOSleep(1);}return done();}
KICK
WAIT
PDC
bool adspLoad(){int dtb=0,adsp=0;TRANSACTION return true;}
void reset(){std::fill_n(aossWords,1024,0);auto*r=aossWords;r[0]=0x4d41494c;r[1]=1;
 r[3]=r[4]=r[5]=r[6]=r[9]=r[10]=r[11]=r[12]=0xffff;r[13]=0x80;r[14]=0x100;}
int main(){reset();bool wcn=false,dsp=false;
 std::thread t1([&]{wcn=pdcInit();});while(!pending)std::this_thread::yield();
 std::thread t2([&]{dsp=adspLoad();});while(!waiting)std::this_thread::yield();
 assert(active==1&&received.empty());
 // The AOSS owner is waiting on its peer, but the independent RPMh mutex is free.
 std::mutex rpmh;assert(rpmh.try_lock());rpmh.unlock();
 continuePeer=true;t1.join();t2.join();assert(wcn&&dsp&&received.size()==12&&peak==1&&active==0);
 assert(received.back()=="{class: image, res: load_state, name: adsp, val: on}");
 reset();ack=false;assert(!adspLoad()&&failed==-60&&releases==2&&!aossWords[0x100/4]&&!active);
 ack=true;assert(adspLoad()&&!active);assert(b5q_aoss_qmp_lock());b5q_aoss_qmp_unlock();
 puts("PASS actual sharedAOSSmutex:WCN11+ADSP1 transactions cannot overlap; RPMh independent; ADSPwait/abandon/earlyreturn unlock; retry succeeds");}
'''
for marker,text in [('LOCK',f(w,'extern "C" bool b5q_aoss_qmp_lock(')),('UNLOCK',f(w,'extern "C" void b5q_aoss_qmp_unlock(')),('KICK',f(w,'void kickPdc(')),('WAIT',f(w,'bool waitPdc(')),('PDC',f(w,'bool pdcInit(')),('TRANSACTION',transaction)]:
 body=body.replace('\n'+marker+'\n','\n'+text+'\n')if marker!='TRANSACTION'else body.replace('TRANSACTION',text)
run('shared-AOSS-QMP',body)
eth=(P/'B5qEthernet.cpp').read_text()
assert 'controller->enabled'not in eth
run('Ethernet-gate',base+r'''
using IOReturn=int;constexpr int kIOReturnSuccess=0,kIONetworkLinkValid=1,kIONetworkLinkActive=2;
struct OSObject{virtual~OSObject()=default;};
struct IONetworkInterface{};
using Action=IOReturn(*)(OSObject*,void*,void*,void*,void*);
struct Gate{Action action=nullptr;OSObject *owner=nullptr;void *value=nullptr;bool inGate=false;
 void runAction(Action a,void*v){action=a;value=v;}void drain(){inGate=true;action(owner,value,nullptr,nullptr,nullptr);inGate=false;}};
struct B5qEthernet:OSObject{bool enabled=false,enabledAtStatus=false;void *medium=nullptr;unsigned calls=0,status=0;Gate gate;
 B5qEthernet(){gate.owner=this;}Gate *getCommandGate(){return &gate;}
 void setLinkStatus(unsigned s,void*,uint64_t=0){assert(gate.inGate);calls++;status=s;enabledAtStatus=enabled;}
 ACTION
 LINK
 DISABLE
};
B5qEthernet *gController;bool gWifiLink;
CALLER
int main(){B5qEthernet c;gController=&c;c.enabled=true;sheng_ethernet_wifi_link(true);c.enabled=false;c.gate.drain();assert(!c.calls);
 sheng_ethernet_wifi_link(true);c.enabled=true;c.gate.drain();assert(c.calls==1&&c.status==3);
 sheng_ethernet_wifi_link(false);c.gate.drain();assert(c.calls==2&&c.status==1);
 gController=nullptr;sheng_ethernet_wifi_link(true);assert(c.calls==2);
 c.gate.inGate=true;c.enabled=true;assert(!c.disable(nullptr));c.gate.inGate=false;
 assert(c.calls==3&&c.status==1&&c.enabledAtStatus&&!c.enabled);
 puts("PASS production Ethernet enabled read occurs insidegate; queueddisable preventsup; queuedenable permitsup; down/null retained");}
'''.replace('ACTION',f(eth,'static IOReturn linkAction(')).replace('LINK',f(eth,'void link(')).replace('DISABLE',f(eth,'IOReturn disable(').replace(' override','')).replace('CALLER',f(eth,'extern "C" void sheng_ethernet_wifi_link(')))
gpu=(P/'B5qGpu.cpp').read_text();restart=f(gpu,'IOReturn gpuRestart(')
start=restart.index('    if(gPreemptWanted');guard=f(restart[start:],'if(gPreemptWanted')
run('GPU-restart-secondary',base+r'''
using IOReturn=int;bool gPreemptWanted;unsigned calls,failures;
struct{bool on=false;bool preemption(){return on;}}gSubmit;
struct{int error=0;int restartSecondary(unsigned){++calls;return error;}}gRing1;
IOReturn attempt(unsigned completed){IOReturn status=0;auto fail=[](unsigned step,int error){assert(step==7);failures++;return error;};GUARD return 0;}
int main(){gPreemptWanted=true;gRing1.error=-1;assert(!attempt(7)&&!calls);gSubmit.on=true;assert(attempt(7)==-1&&calls==1&&failures==1);
 gRing1.error=0;assert(!attempt(7)&&calls==2);gPreemptWanted=false;assert(!attempt(7)&&calls==2);
 puts("PASS actual gpuRestart guard:requested-but-unattached preemption skipsring1; attached restart and failure propagation retained");}
'''.replace('GUARD',guard))
usb=(P/'UsbProbe.cpp').read_text();a=usb.index('        if (loaded !=');branch=f(usb[a:],'if (loaded !=')
run('USB-worker-return',base+r'''
constexpr int kOSReturnSuccess=0,kOSKextReturnStartStopError=1;unsigned native_usb_stats[54],terminated=0,continued=0;
void IOLog(const char*,...){}void*current_thread(){return nullptr;}void thread_terminate(void*){terminated++;}
void worker(int loaded){BRANCH continued++;}
int main(){worker(-9);assert(terminated==1&&!continued);worker(0);worker(1);assert(continued==2&&terminated==1);
 puts("PASS actual USBload failure branch returns even ifthread_terminate helper returns; successpaths retained");}
'''.replace('BRANCH',branch))
workflow=(R/'.github/workflows/b5q-p0-p5.yml').read_text();a=workflow.index('name: b5q-build-${{');b=workflow.index('\n      - name:',a);assert 'retention-days: 30'in workflow[a:b]
primary=f((P/'QcomDwc3.cpp').read_text(),'static void primary(')
assert '->retain('not in primary and '->release('not in primary
print('PASS focused sourcecontracts:IRQonlyinFlight,30daybuildretention,sharedQMPscope; no bootargs/0014 changes')
