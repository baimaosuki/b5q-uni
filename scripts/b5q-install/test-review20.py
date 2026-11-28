#!/usr/bin/env python3
"""Review20: production scheduling, policy, event, CPU/crash and Hub regression."""
import argparse,hashlib,importlib.util,json,os,re,subprocess,tempfile,tomllib
from pathlib import Path
R=Path(__file__).resolve().parents[2];P=R/'UniXNU-b5q/package';ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--out',type=Path,default=Path(os.environ.get('B5Q_GATE_WORK',R/'artifacts/b5q-review20-local')));W=ap.parse_args().out.resolve();W.mkdir(parents=True,exist_ok=True);checks=[]
def run(name,cmd):
 p=subprocess.run(list(map(str,cmd)),cwd=R,capture_output=True,text=True);out=p.stdout+p.stderr;(W/(name+'.log')).write_text(out)
 if p.returncode:raise RuntimeError(name+'\n'+out[-7000:])
 checks.append(dict(name=name,passed=True,command=list(map(str,cmd)),log_sha256=hashlib.sha256(out.encode()).hexdigest()));print('PASS',name,flush=True)
def load(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def fn(s,signature):
 first=s.index(signature);end=s.index('{',first)+1;depth=1
 while depth:depth+=(s[end]=='{')-(s[end]=='}');end+=1
 return s[first:end]
def added(path):return '\n'.join(l[1:]for l in path.read_text().splitlines()if l.startswith('+')and not l.startswith('+++'))
def host(t,name,source,c=False):
 p=t/(name+('.c'if c else'.cpp'));p.write_text(source);binary=t/name
 compiler='/usr/lib/llvm-17/bin/clang'if c else'c++'
 run(name+'-compile',[compiler,'-std=gnu11'if c else'-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-Wno-misleading-indentation','-Wno-missing-field-initializers','-fsanitize=address,undefined','-fno-sanitize-recover=all','-pthread','-I'+str(P),p,'-o',binary]);run(name+'-ASan-UBSan',[binary])
policy=load('r20policy',R/'UniXNU-b5q/scripts/update-b5q-launchd-seed.py');labels=policy.policies();assert list(map(len,labels.values()))==[59,25]
for values in labels.values():assert 'com.apple.wallpaper.agent'not in values and 'com.apple.wallpaper.extension.aerials'in values
before=json.loads((R/'artifacts/b5q-review20-local/before.json').read_text());old=json.loads(subprocess.check_output(['git','show','HEAD:UniXNU-b5q/package/b5q-launchd-lite.json'],cwd=R));new=json.loads((P/'b5q-launchd-lite.json').read_text());old['gui'].remove('com.apple.wallpaper.agent') if 'com.apple.wallpaper.agent'in old['gui']else None;old['gui']=sorted(set(old['gui']+['com.apple.SoftwareUpdateNotificationManager']));old['system']=[n for n in old['system'] if n!='com.apple.softwareupdated'];old['system_enabled']=['com.apple.softwareupdated','com.openssh.sshd'];assert old==new
for forbidden in ['wifivelocityd','sysdiagnosed','ReportCrashService','DisplayControls','calaccessd']:
 assert {n for values in new.values() for n in values if forbidden in n}=={n for values in old.values() for n in values if forbidden in n},forbidden
# Retain the actual source-bound Data seed, despite its old policy. The kernel
# canonical blob migration is separately exercised by test-v33b-policy.py.
seed=R/'artifacts/b5q-review19-ci-46047273117/runtime/data-seed.json';meta=json.loads(seed.read_text())
oldpol=policy.historical_policies();assert meta['launchd_policy']==oldpol
checks.append(dict(name='wallpaper-sshd59-25-canonical-policy-aerial-disabled-no-expanded-denylist',passed=True))
wifi=load('r20wifi',R/'UniXNU-b5q/scripts/b5q_wifi.py')
with tempfile.TemporaryDirectory(prefix='review20-',dir=W)as td:
 t=Path(td)
 # Hash-qualified seed reuse remains a literal no-op despite the new policy.
 seed_copy=t/'data.dbr'
 run('qualified-Data-seed-readonly-extract',['mcopy','-i',R/'artifacts/b5q-review19-ci-46047273117/payload/payload.img','::/EFI/UniXNU/Payloads/scratch-data.img',seed_copy])
 digest,reusable=policy.checked_seed(seed_copy.read_bytes(),meta,'current');assert reusable and digest==policy.MIGRATED_SEED_HASH
 seed_copy.unlink()
 main=wifi.select_shared(R/'sources/UniXNU-sheng/drivers/Ath12kWifi/src/nw_mainline.c',t).read_text();control=wifi.select_shared(R/'sources/UniXNU-sheng/drivers/Ath12kWifi/src/nw_cfg80211_control.c',t).read_text();net=wifi.prepare(R/'sources/UniXNU-sheng',t).read_text()
 assert 'pending.operation == NW_CONTROL_JOIN_REQUEST'in main and 'NW_CONTROL_AUTHENTICATE'in control
 step=fn((P/'B5qAth11k.c').read_text(),'int nw_wifi_step(void)')
 assert step.index('nw_mainline_run();')<step.index('lx_pump();')
 pending=fn(main,'int b5q_wifi_requests_pending(void)');disconnect=fn(main,'void nw_wifi_disconnect(void)')
 code=r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <string>
#include "B5qWorkerWait.h"
using u64=uint64_t;static unsigned boundary_lock;static uint64_t ms;
static void lx_shared_spin_lock(unsigned*){}static void lx_shared_spin_unlock(unsigned*){}
static uint64_t lx_now_ms(){return ms;}
enum {NW_CONTROL_DISCONNECT_REQUEST=265,NW_STA_AUTH=3,NW_STA_IDLE=1,NW_STA_OFF=0};
static struct {unsigned operation;} ui;static struct {bool pending,enabled;} radio;
static bool join_waiting,scan_waiting,scan_ack_pending;static unsigned epoch;static uint64_t b5q_ui_since;
static struct {unsigned state;} status;static void clear_connection(unsigned n){status.state=n;}
#define memzero_explicit(p,n) memset(p,0,n)
'''+pending+'\n'+disconnect+r'''
static volatile uint64_t b5q_wifi_last_slow[4];
static void *hardware;static int firmware_error;static unsigned phase,slow;static std::string order;
static void b5q_step_mark(unsigned n){phase=n;}
static void b5q_wifi_step_observe(unsigned,u64 elapsed){assert(elapsed>200);++slow;}
static void nw_wifi_control_poll(){order+='c';}
static void nw_mainline_run(){order+='m';if(ui.operation==264)ui.operation=0;}
static int lx_pump(){order+='p';ms+=300;return 0;}
static void nw_wifi_link_state(char*,unsigned){}
static bool nw_mainline_pending(){return false;}static bool nw_wifi_control_pending(){return false;}
static unsigned lx_next_wait_ms(unsigned n){return n;}
'''+step+r'''
int main(){
 radio.enabled=true;status.state=NW_STA_IDLE;nw_wifi_disconnect();assert(!ui.operation && !epoch);
 ui.operation=264;assert(b5q_wifi_requests_pending());assert(!nw_wifi_step());assert(order=="cmp"&&slow==1&&phase==0&&!ui.operation);
 radio.pending=true;assert(b5q_wifi_requests_pending());radio.pending=false;scan_ack_pending=true;assert(b5q_wifi_requests_pending());scan_ack_pending=false;assert(!b5q_wifi_requests_pending());
 join_waiting=true;status.state=NW_STA_AUTH;nw_wifi_disconnect();assert(ui.operation==265&&!join_waiting&&epoch==1);assert(b5q_wifi_requests_pending());ui.operation=0;
 assert(b5q_wifi_worker_wait(0,1000,0)==1000);assert(b5q_wifi_worker_wait(1,0,1999999)==0);assert(b5q_wifi_worker_wait(1,0,2000000)==1);assert(b5q_wifi_worker_wait(0,0,0)==1);
 assert(b5q_bt_worker_deadline(0,1000000)==2000000);assert(b5q_bt_worker_deadline(100,1000000)==2000000);assert(b5q_bt_worker_deadline(UINT64_MAX,100)==UINT64_MAX);
}
''';host(t,'wifi-ui-pending-idle-disconnect-step-budget-and-BT-wait',code)
 board=(P/'B5qWifiBoard.cpp').read_text();worker=fn(board,'void worker(');assert worker.index('const uint32_t observed=')<worker.index('error=nw_wifi_step()')<worker.index('assert_wait_deadline')<worker.index('observed!=__atomic_load_n')
 assert 'thread_yield_to_preemption'not in worker
 # Exercise the real one-buffer/cluster sizing and copy code from kern_event.
 event=t/'bsd/kern/kern_event.c';event.parent.mkdir(parents=True);event.write_bytes((R/'sources/UniXNU/out/feeds/xnu-3199e8bc/bsd/kern/kern_event.c').read_bytes())
 subprocess.run(['git','apply','--directory='+str(t.relative_to(R)) ,str(R/'UniXNU-b5q/patches/xnu/b5q-wifi-association-event.patch')],cwd=R,check=True)
 text=event.read_text();chunk=text[text.index('\t/* iPadOS 27 association'):text.index('\tlck_rw_lock_shared(&kev_rwlock);',text.index('\t/* iPadOS 27 association'))]
 host(t,'Apple80211-580byte-event-cluster-overflow-and-copy',r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <cerrno>
using u_int32_t=uint32_t;
#define KEV_VENDOR_APPLE 1
#define KEV_IEEE80211_CLASS 6
#define KEV_MSG_HEADER_SIZE 24
#define MLEN 288
#define MCLBYTES 2048
#define MT_DATA 1
#define relaxed 0
#define os_atomic_inc(p,o) (++*(p))
#define mtod(m,t) reinterpret_cast<t>((m)->bytes)
#define bcopy(a,b,n) memcpy(b,a,n)
struct kern_event_msg{uint32_t total_size,vendor_code,kev_class,kev_subclass,id,event_code;char event_data[2024];};
struct mbuf{alignas(8)char bytes[MCLBYTES];uint32_t m_len;};static mbuf storage;static unsigned clusters;static bool no_memory;
static mbuf *m_get(int,int){clusters=0;return no_memory?nullptr:&storage;}static mbuf *m_getcl(int,int,int){clusters=1;return no_memory?nullptr:&storage;}
struct kev_msg{unsigned vendor_code,kev_class,kev_subclass,event_code;struct{uint32_t data_length;void *data_ptr;}dv[5];};
static struct{unsigned kes_toobig,kes_nomem;}kevtstat;static unsigned static_event_id;
static int post(kev_msg *event_msg){mbuf *m; kern_event_msg *ev;char *tmp;uint32_t total_size;int i,wait=0;
'''+chunk+r'''
return 0;}
int main(){char name[16]="en1",result[540];memset(result,0xaa,sizeof result);kev_msg msg{};msg.vendor_code=1;msg.kev_class=6;msg.event_code=9;msg.dv[0]={16,name};msg.dv[1]={540,result};assert(post(&msg)==0&&clusters==1&&storage.m_len==580);assert(!memcmp(storage.bytes+24,name,16)&&!memcmp(storage.bytes+40,result,540));
 msg.kev_class=1;assert(post(&msg)==EMSGSIZE);msg.dv[1].data_length=MLEN-24-16;assert(post(&msg)==0&&!clusters&&storage.m_len==MLEN);++msg.dv[1].data_length;assert(post(&msg)==EMSGSIZE);msg.kev_class=6;msg.dv[1].data_length=UINT32_MAX;assert(post(&msg)==EMSGSIZE);msg.dv[1].data_length=2048;assert(post(&msg)==EMSGSIZE);msg.dv[1].data_length=540;no_memory=true;assert(post(&msg)==ENOMEM);
}
''')
 # Actual request-filter block: unchanged op21 polls are silent, transitions/errors persist.
 logs=net[net.index('    bool stateChanged=false;'):net.index('    return e;',net.index('    bool stateChanged=false;'))]
 host(t,'wifi-op21-state-log-dedup',r'''
#include <cassert>
#include <cstdint>
#include <cstddef>
struct nw_wifi_status{unsigned state;int signal_dbm;};static nw_wifi_status st{};static unsigned gJoinPending;static int gAssocResult;static unsigned logged;
static void visible_status(nw_wifi_status &s){s=st;}static void log(int,const char*,...){++logged;}
enum{SIOCSA80211=1,kAssociateResult=21,kState=13};static void *kKernelRequest;
static void request(int e){unsigned type=21,cmd=0,len=0,val=0,shown=0;bool first=false,joinState=true;void *ifp=nullptr;struct{unsigned req_len,req_val;}req{},*rq=&req;
'''+logs+r'''
}
int main(){request(0);assert(logged==2);for(unsigned i=0;i<1000;++i)request(0);assert(logged==2);st.state=3;request(0);assert(logged==4);gJoinPending=1;request(0);assert(logged==6);gAssocResult=7;request(0);assert(logged==8);request(5);assert(logged==10);request(5);assert(logged==12);}
''')
 host(t,'kernel-thread-TOP5-deltas-format-and-tid-reuse',r'''
#include <cassert>
#include <cstdio>
#include <cstring>
#include <string>
#include "B5qKernelThreads.h"
static std::string output;static void emit(const char*s,void*){assert(strlen(s)<224);output+=s;}
int main(){static b5q_kthread_window w{};b5q_kthread_sample rows[7]{};for(unsigned i=0;i<7;i++){rows[i].tid=i+1;snprintf(rows[i].name,64,"b5q-worker%u",i);}b5q_kthread_update(&w,rows,7,0);assert(!w.top[0].delta_ms);for(unsigned i=0;i<7;i++)rows[i].cpu_ns=(i+1)*1000000000ULL;b5q_kthread_update(&w,rows,7,30000);assert(w.top[0].sample.tid==7&&w.top[0].delta_ms==7000&&w.top[0].permille==233);assert(w.top[4].sample.tid==3);b5q_kthread_print(&w,emit,nullptr);assert(output.find("B5qProcTop: kthread TOP1 tid=7 name=b5q-worker6 delta_cpu_ms=7000 permille=233")!=std::string::npos);rows[0].tid=100;rows[0].cpu_ns=999999999999ULL;rows[1].cpu_ns=0;b5q_kthread_update(&w,rows,7,30000);assert(w.top[0].delta_ms==0);static_assert(sizeof(b5q_kthread_sample)==80);}
''')
 host(t,'USB-Hub-EP3-context-status-bounds-and-readonly',r'''
#include <cassert>
#include <cstdint>
#include <map>
#include "B5qUsbHostEvent.h"
using namespace B5qUsbHostEvent;
int main(){std::map<uint64_t,uint64_t>mem{{0x1008,0x2000},{0x2060,1},{0x2068,0x4001}};auto read=[&](uint64_t p,uint64_t&v){auto i=mem.find(p);if(i==mem.end())return false;v=i->second;return true;};Endpoint ep{};assert(endpoint(0x1000,32,1,3,read,ep)&&ep.address==0x2060&&ep.words[1]==0x4001);assert(!endpoint(0x1001,32,1,3,read,ep));assert(!endpoint(0x1000,32,256,3,read,ep));assert(!endpoint(0x1000,32,1,32,read,ep));assert(!endpoint(UINT64_MAX&~63ULL,64,255,31,read,ep));
 Event e{0x5020,0,0,1,32,1,1,1};mem[0x5028]=uint64_t(4)<<42;mem[0x5010]=0x6000;mem[0x5018]=(uint64_t(3)<<42)|4;mem[0x5000]=(uint64_t(4)<<48)|(uint64_t(2)<<32)|0xa3;mem[0x5008]=uint64_t(2)<<42;mem[0x6000]=0x10103;unsigned port=0;uint32_t status=0;assert(hubPortStatus(e,read,port,status)&&port==2&&status==0x10103);e.completion=26;assert(!hubPortStatus(e,read,port,status));e.completion=1;mem[0x6000]=UINT64_MAX;mem.erase(0x5010);assert(!hubPortStatus(e,read,port,status));}
''')
 # Crash quota/matching is the exact source added to kern_exit.c.
 crash=added(R/'UniXNU-b5q/patches/xnu/b5q-windowserver-signal.patch');claim=fn(crash,'static unsigned\nb5q_proc_crash_claim(');kind=fn(crash,'static int\nb5q_proc_crash_kind(')
 host(t,'crash-process-names-quota-reentrancy',r'''
#include <assert.h>
#include <stdint.h>
#include <stdatomic.h>
#include <string.h>
#include <pthread.h>
#define MAXCOMLEN 16
static _Atomic uint32_t b5q_proc_crash_slots;
'''+kind+'\n'+claim+r'''
static void done(unsigned kind){atomic_fetch_and_explicit(&b5q_proc_crash_slots,~(1u<<(16+kind)),memory_order_release);}
static void *race(void *p){unsigned k=(unsigned)(uintptr_t)p;for(unsigned i=0;i<1000;i++)if(b5q_proc_crash_claim(k))done(k);return 0;}
int main(){assert(b5q_proc_crash_kind("calaccessd")==0);assert(b5q_proc_crash_kind("DisplayControls")==1);assert(b5q_proc_crash_kind("WindowManagerCon")==2);assert(b5q_proc_crash_kind("WindowManagerControlsExtension")==2);assert(b5q_proc_crash_kind("ScreenshotContro")==3);assert(b5q_proc_crash_kind("ScreenshotControls")==3);assert(b5q_proc_crash_kind("WindowServer")==-1);assert(b5q_proc_crash_kind("calaccessd-evil")==-1);assert(!b5q_proc_crash_claim(4));assert(b5q_proc_crash_claim(0)==1);assert(!b5q_proc_crash_claim(0));done(0);assert(b5q_proc_crash_claim(0)==2);done(0);assert(!b5q_proc_crash_claim(0));pthread_t t[12];for(unsigned i=0;i<12;i++)assert(!pthread_create(&t[i],0,race,(void*)(uintptr_t)(1+i%3)));for(unsigned i=0;i<12;i++)assert(!pthread_join(t[i],0));uint32_t n=atomic_load(&b5q_proc_crash_slots);assert((n&15)==8);for(unsigned k=0;k<4;k++)assert(((n>>(4+2*k))&3)==2);assert(!(n&0xf0000));}
''',True)
 snapshot=added(R/'UniXNU-b5q/patches/xnu/b5q-kernel-thread-stats.patch')
 host(t,'kernel-thread-snapshot-lock-order-noalloc-overflow',r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#define _Static_assert static_assert
#define NSEC_PER_SEC 1000000000ULL
#define NSEC_PER_USEC 1000ULL
#define TH_OPT_IDLE_THREAD 1
struct thread{unsigned options;thread *next;uint64_t tid;char name[64];};using thread_t=thread*;
struct task{thread_t threads;} kernel;static task *kernel_task=&kernel;static unsigned locks;
struct time_value_t{unsigned seconds,microseconds;};
static void task_lock(task*){assert(!locks);++locks;}static void task_unlock(task*){assert(locks==1);--locks;}
#define queue_iterate(q,var,type,link) for(var=*(q);var;var=var->next)
static void thread_read_times(thread_t t,time_value_t *u,time_value_t *s,void *p){assert(locks==1&&!p);*u={1,unsigned(t->tid)};*s={2,500};}
static uint64_t thread_tid(thread_t t){assert(locks==1);return t->tid;}
static void thread_get_thread_name(thread_t t,char *p){assert(locks==1);memcpy(p,t->name,64);}
#define bzero(p,n) memset(p,0,n)
'''+snapshot+r'''
int main(){thread c{0,nullptr,3,{}},b{1,&c,2,{}},a{0,&b,1,{}};memset(a.name,'A',64);strcpy(c.name,"b5q-wifi");kernel.threads=&a;b5q_kthread_sample rows[2]{};unsigned dropped=99;assert(b5q_kernel_thread_snapshot(rows,2,&dropped)==2&&!dropped&&!locks);assert(rows[0].tid==1&&rows[0].cpu_ns==3000501000ULL&&rows[0].name[63]==0);assert(rows[1].tid==3&&!strcmp(rows[1].name,"b5q-wifi"));assert(b5q_kernel_thread_snapshot(rows,1,&dropped)==1&&dropped==1&&!locks);assert(!b5q_kernel_thread_snapshot(nullptr,1,&dropped));assert(!b5q_kernel_thread_snapshot(rows,257,&dropped));}
''')
 # Use the existing proven register/dyld mock ABI to exercise the NEW entire
 # process-context collector, including rejection paths and early failures.
 import ast
 ws_tree=ast.parse((R/'tests/b5q-ufs/test-ws-signal.py').read_text())
 ws_value=next(n.value for n in ws_tree.body if isinstance(n,ast.Assign)and any(isinstance(v,ast.Name)and v.id=='harness'for v in n.targets))
 harness=ws_value.func.value.value
 harness=harness[:harness.index('int main(void)')]
 harness=re.sub(r'static unsigned backtrace\(.*?\n', '', harness)
 proc_context=fn(crash,'__attribute__((noinline)) static void\nb5q_process_crash_context(')
 crash_helpers='static _Atomic uint32_t b5q_proc_crash_slots;\n'+kind+'\n'+claim+'\n'+proc_context
 harness=harness.replace('HELPER','#define MAXCOMLEN 16\n'+crash_helpers)
 harness+=r'''
int main(void){ws.p_name="calaccessd";foreign=1;b5q_process_crash_context(&ws,SIGABRT);foreign=0;enabled=0;b5q_process_crash_context(&ws,SIGABRT);enabled=1;b5q_process_crash_context(&ws,SIGTERM);assert(!user_calls&&!copy_calls);b5q_process_crash_context(&ws,SIGABRT);assert(user_calls==1&&copy_calls==1&&!kernel_calls);missing_state=1;bad_dyld=1;b5q_process_crash_context(&ws,SIGTRAP);assert(user_calls==2&&copy_calls==2);for(unsigned i=0;i<10;i++)b5q_process_crash_context(&ws,SIGBUS);assert(user_calls==2);char *names[]={"DisplayControls","WindowManagerCon","ScreenshotContro"};for(unsigned i=0;i<3;i++){ws.p_name=names[i];b5q_process_crash_context(&ws,SIGSEGV);b5q_process_crash_context(&ws,SIGILL);}assert(user_calls==8&&copy_calls==8&&!kernel_calls);assert((atomic_load(&b5q_proc_crash_slots)&15)==8);}
'''
 # Match Darwin's uint64_t printf typedef in this host-only saved-state fixture.
 host(t,'process-crash-whole-context-format-and-reject',harness.replace('uint64_t','unsigned long long'),True)
 # Run actual Host exit code with termination refusal and delayed bridge drain.
 leave=fn((P/'QcomDwc3.cpp').read_text(),'void leaveRole(')
 host(t,'USB-host-real-teardown-VBUS-route-bridge-refusal',r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <string>
#include "B5qMax77705.h"
static std::string trace;static bool stop_ok,terminate_ok=true;
struct QcomDwc3Xhci{unsigned refs=1;void retain(){++refs;trace+='r';}void release(){assert(refs>1);--refs;trace+='R';}} host;
struct Nub{unsigned refs=1;bool terminate(int){trace+='t';return terminate_ok;}void release(){assert(refs==1);--refs;trace+='n';}} nub;
struct QcomDwc3Nub{static void route(void*p){assert(!p);trace+='u';}};
struct IOService{static IOService *getResourceService(){static IOService s;return &s;}void removeProperty(const char*){}};
static QcomDwc3Xhci *gHost=&host;static Nub *gHostNub=&nub;static bool gDmaReady=true,gDeviceStackAllowed;static uint32_t native_usb_stats[54];
static uint32_t regs[0x2000]{};static struct{uint32_t *va=regs;}gXhciRegs;
static B5qMax77705::Cable gAppliedCable;static int gAppliedOrientation;
enum{kRoleHost=2,kRoleDevice=1,kIOServiceSynchronous=1};
struct Controller{unsigned cable(bool){return 0;}}controller;static Controller *gController=&controller;
static void IOLog(const char*,...){}static void IOSleep(unsigned){}static bool b5q_usb_otg(bool on){assert(!on);trace+='o';return true;}
static bool stopHostIrqBridge(){trace+='s';return stop_ok;}static void releaseHostPortPowerHolds(){trace+='h';}static void dmaDiagnostics(const char*){trace+='d';}
'''+leave+r'''
int main(){regs[0]=0x40;regs[0x44/4]=1;terminate_ok=false;leaveRole(kRoleHost);assert(gHostNub&&gHost&&host.refs==1&&trace.find('o')==std::string::npos&&trace.find('u')==std::string::npos);trace.clear();terminate_ok=true;stop_ok=false;leaveRole(kRoleHost);assert(gHostNub&&gHost&&host.refs==2&&trace.find('t')<trace.find('s')&&trace.find('o')==std::string::npos);trace.clear();stop_ok=true;leaveRole(kRoleHost);assert(!gHost&&!gHostNub&&host.refs==1&&trace.find('t')==std::string::npos);assert(trace.find('s')<trace.find('u')&&trace.find('u')<trace.find('o')&&trace.find('o')<trace.find('n'));}
''')
 old=added(Path('artifacts/b5q-review20-local/tmp/windowserver-before.patch')) if (R/'artifacts/b5q-review20-local/tmp/windowserver-before.patch').is_file()else '\n'.join(l[1:]for l in subprocess.check_output(['git','show','HEAD:UniXNU-b5q/patches/xnu/b5q-windowserver-signal.patch'],cwd=R).decode().splitlines()if l.startswith('+')and not l.startswith('+++'))
 assert fn(old,'__attribute__((noinline)) static void\nb5q_windowserver_signal_context(')==fn(crash,'__attribute__((noinline)) static void\nb5q_windowserver_signal_context(')
 context=fn(crash,'__attribute__((noinline)) static void\nb5q_process_crash_context(');assert 'p != current_proc()'in context and 'SIGTRAP'in context and 'backtrace_user(frames, 16'in context and 'b5q-ws-signal'in context
 usb=(P/'QcomDwc3.cpp').read_text();leave=fn(usb,'void leaveRole(');assert leave.index('gHostNub->terminate(kIOServiceSynchronous)')<leave.index('stopHostIrqBridge()')<leave.index('QcomDwc3Nub::route(nullptr)')<leave.rindex('b5q_usb_otg(false)')
 assert 'if(gHostNub){IOSleep(100);continue;}'in usb and 'gGlobals.va[0x630/4]'in usb and 'hub-configured'in usb and 'host-halt cmd='in usb
 for line in usb.splitlines():
  if '0x630/4]'in line:assert not re.search(r'0x630/4\]\s*[|&+]?=',line),'no speculative GFLADJ writes'
 checks.append(dict(name='WindowServer8quota-byte-identity-crash-guard-USB-halt-order-GFLADJ-readonly',passed=True))
 for n,digest in before['protected_sha256'].items():assert hashlib.sha256((R/n).read_bytes()).hexdigest()==digest,n
 args=tomllib.loads((R/'UniXNU-b5q/board.toml').read_text())['payload']['kernel_args'];assert len(' '.join(args).encode())==1023
 assert 'unsigned owned = 1; PE_parse_boot_argn("gpu-owned-coherent"'in(P/'B5qGpu.cpp').read_text()
 checks.append(dict(name='protected68-zero-drift-1023B-owned1',passed=True))
(W/'review20-tests.json').write_text(json.dumps(dict(passed=True,status='HOST_VERIFIED_PENDING_HARDWARE',hardware_verified=False,checks=checks),indent=2)+'\n')
print('PASS Review20 production host regressions; hardware pending')
