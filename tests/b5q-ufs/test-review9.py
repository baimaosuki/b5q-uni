#!/usr/bin/env python3
"""Review9: production zero allocation, ath11k guards and timed Type-C roles."""
from pathlib import Path
import importlib.util,re,subprocess,tempfile

R=Path(__file__).resolve().parents[2];P=R/'UniXNU-b5q/package'
def function(text,signature):
    a=text.index(signature);b=text.index('{',a)+1;depth=1
    while depth:depth+=(text[b]=='{')-(text[b]=='}');b+=1
    return text[a:b]
def execute(root,name,body):
    src=root/(name+'.cpp');exe=root/name;src.write_text(body)
    subprocess.run(['c++','-std=c++17','-g','-O1','-Wall','-Wextra','-Werror',
        '-Wno-misleading-indentation','-Wno-unused-parameter','-fsanitize=address,undefined',
        '-I'+str(P),str(src),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)

spec=importlib.util.spec_from_file_location('wifi',R/'UniXNU-b5q/scripts/build-b5q-wifi.py')
wifi=importlib.util.module_from_spec(spec);spec.loader.exec_module(wifi)
with tempfile.TemporaryDirectory(prefix='b5q-review9-')as td:
    t=Path(td);gen=wifi.prepare(R/'sources/UniXNU-sheng/drivers/Ath12kWifi',t)
    wmi=(gen/'wmi.c').read_text();header=(gen/'wmi.h').read_text()
    alloc=(P/'B5qWifiBoard.cpp').read_text()
    constants='\n'.join(re.findall(r'^#define REG_RULE_(?:START_FREQ|END_FREQ|MAX_BW|REG_PWR|ANT_GAIN|FLAGS|PSD_INFO|PSD_EIRP)\s+[^\n]+',header,re.M))
    structs='\n'.join(header[header.index('struct '+n+' {'):header.index('};',header.index('struct '+n+' {'))+2] if n=='cur_reg_rule' else
        header[header.index('struct '+n+' {'):header.index('} __packed;',header.index('struct '+n+' {'))+11] for n in ['cur_reg_rule','wmi_regulatory_ext_rule'])
    body=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <map>
using u32=uint32_t;using u16=uint16_t;using u8=uint8_t;using s8=int8_t;
#define __packed __attribute__((packed))
#define BIT(x) (1u<<(x))
CONSTANTS
STRUCTS
bool oom=false;std::map<void*,size_t> live;
void *IOMallocData(size_t n){if(oom)return nullptr;void*p=malloc(n);assert(p&&n>=16);live[p]=n;return p;}
void IOFreeData(void*p,size_t n){assert(live.at(p)==n);live.erase(p);free(p);}
ALLOC
FREE
void *zeroAlloc(size_t n){void*p=allocate(n);if(p)memset(p,0,n);return p;}
#define kzalloc_objs(v,n,flags) static_cast<decltype(&(v))>(zeroAlloc(sizeof(v)*(n)))
#define GFP_ATOMIC 0
u32 u32_get_bits(u32 v,u32 mask){return (v&mask)>>__builtin_ctz(mask);}
RULES
int main(){
 for(size_t n:{size_t(0),size_t(1),size_t(4096)}){void*p=allocate(n);assert(p);if(n)memset(p,0xa5,n);release(p);}
 assert(live.empty());release(nullptr);assert(!allocate(SIZE_MAX)&&!allocate(SIZE_MAX-15));
 oom=true;assert(!allocate(0)&&!allocate(64));oom=false;
 auto *empty=create_ext_reg_rules_from_wmi(0,nullptr);assert(empty);release(empty);
 wmi_regulatory_ext_rule rule{};rule.freq_info=(7125u<<16)|5925u;rule.bw_pwr_info=(6u<<24)|(24u<<16)|320u;
 auto *one=create_ext_reg_rules_from_wmi(1,&rule);assert(one&&one[0].start_freq==5925&&one[0].end_freq==7125&&one[0].max_bw==320&&one[0].reg_power==24&&one[0].ant_gain==6);release(one);
 oom=true;assert(!create_ext_reg_rules_from_wmi(0,nullptr));assert(live.empty());
 puts("PASS production allocate/release and real WMI regulatory parser: zero 6GHz AP rules succeed; nonzero, overflow, OOM, sized free ASan/UBSan");
}
'''.replace('CONSTANTS',constants).replace('STRUCTS',structs).replace('ALLOC',function(alloc,'void *allocate(size_t n)')).replace('FREE',function(alloc,'void release(void *p)')).replace('RULES',function(wmi,'static struct cur_reg_rule\n*create_ext_reg_rules_from_wmi('))
    execute(t,'zero-regulatory',body)

    pci=(gen/'pci.c').read_text();mac=(gen/'mac.c').read_text()
    # Execute the real PCI start, then the real mac_start idle-PS block.
    start=mac.index('\tif (ab->hw_params.idle_ps) {',mac.index('static int ath11k_mac_op_start('))
    idle=function(mac[start:],'\tif (ab->hw_params.idle_ps)')
    a=mac.index('\tif (!ab->default_regd[ar->pdev_idx])',mac.index('static int ath11k_mac_op_add_interface('))
    guard=function(mac[a:],'\tif (!ab->default_regd[ar->pdev_idx])')
    assert a<mac.index('ath11k_wmi_vdev_create(',a)
    body=r'''
#include <cassert>
#include <cerrno>
#include <cstdint>
#include <cstdio>
constexpr unsigned ATH11K_FLAG_MULTI_MSI_VECTORS=0,ATH11K_HW_WCN6855_HW21=21,WMI_PDEV_PARAM_IDLE_PS_CONFIG=9;
struct ath11k_pci{};struct ath11k_base{unsigned long dev_flags=0;unsigned hw_rev=21;struct{bool idle_ps=true;}hw_params;void*default_regd[1]={};};
struct ath11k_pdev{unsigned pdev_id=0;};struct ath11k{unsigned pdev_idx=0;};
bool test_bit(unsigned bit,unsigned long*p){return (*p>>bit)&1;}
unsigned restores=0,starts=0,commands=0,vdevs=0;ath11k_pci pci;
ath11k_pci*ath11k_pci_priv(ath11k_base*){return &pci;}
void ath11k_pci_aspm_restore(ath11k_pci*){restores++;}void ath11k_pcic_start(ath11k_base*){starts++;}
#define ath11k_info(...) ((void)0)
#define ath11k_warn(...) ((void)0)
#define ath11k_err(...) ((void)0)
int ath11k_wmi_pdev_set_param(ath11k*,unsigned,unsigned,unsigned){commands++;return 0;}
PCI
int macStart(ath11k_base*ab,ath11k*ar){int ret=0;ath11k_pdev device,*pdev=&device;@IDLE@ return ret;err: return ret;}
int addInterface(ath11k_base*ab,ath11k*ar){int ret=0;GUARD vdevs++;return 0;err:return ret;}
int main(){
 for(unsigned multi=0;multi<2;multi++)for(unsigned hw:{21u,20u})for(bool initial:{false,true}){
  ath11k_base ab;ab.dev_flags=multi;ab.hw_rev=hw;ab.hw_params.idle_ps=initial;ath11k ar{};
  restores=starts=commands=0;assert(!ath11k_pci_start(&ab)&&starts==1&&restores==multi);
  bool expected=initial&&(multi||hw!=21);assert(ab.hw_params.idle_ps==expected);
  assert(!macStart(&ab,&ar)&&commands==unsigned(expected));
  assert(addInterface(&ab,&ar)==-EAGAIN&&vdevs==0);ab.default_regd[0]=&ab;
  assert(!addInterface(&ab,&ar)&&vdevs==1);vdevs=0;
 }
 puts("PASS actual single/multi MSI HW21/other idle-PS policy, mac_start IMPS command gate; missing regd fails before vdev/WMM effects");
}
'''.replace('PCI',function(pci,'static int ath11k_pci_start(')).replace('@IDLE@',idle).replace('GUARD',guard)
    # Avoid requiring a C++ initializer_list header only by including it.
    execute(t,'imps-regdomain','#include <initializer_list>\n'+body)
    assert 'B5qWifi: credit-timeout cmd=%u eid=%u credits=%d idle_ps=%u multi-msi=%u' in wmi
    assert 'ab->htc.endpoint[wmi->eid].tx_credits' in wmi

    q=(P/'QcomDwc3.cpp').read_text()
    body=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <initializer_list>
#include "B5qMax77705.h"
#include "B5qDpPort.h"
#include "B5qUsbHostRole.h"
using B5qMax77705::Cable;
void*gHost=(void*)1;void*gHostNub=(void*)1;Cable gAppliedCable;int gAppliedOrientation=-1;
constexpr unsigned kXhciRegisterBytes=0x8000;uint32_t xhciRegisters[kXhciRegisterBytes/4]{};
struct{uint32_t *va=xhciRegisters;}gXhciRegs;
struct{uint32_t *va=nullptr;}gGlobals;constexpr uint32_t kUsb3SuspendPhy=1u<<17;void barrier(){}
uint64_t ms=0;unsigned sleeps=0,leaves=0,off=0,enters=0;bool otg=false,reverse=false,expire=false;
Cable physical(){Cable c;c.valid=true;
 if(ms>=100&&ms<5000){
  c.cc0=reverse?0x88:0x48;c.pd=0x87;
  // The source window is lost if APSS misses VBUS before t=250ms.
  if(!otg&&ms>=250){c.pd=7;expire=true;}
  if(otg){c.cc0=reverse?0x8a:0x4a;c.bc=0x80;c.cc1=9;}
 }return c;}
constexpr int kRoleHost=2,kRoleNone=0,kRoleDevice=1,THREAD_UNINT=0,kMillisecondScale=1000;
int gRoleWanted=0,gRoleApplied=0,gCoreRole=0;uint32_t gCableWanted=0,gCableApplied=0,gDpLanes=0;
void*gRoleLock=nullptr;bool gDeviceStackAllowed=false,gSuperSpeed=false,gPhyResetPending=false;uint32_t native_usb_stats[54]={};
namespace B5qFeatures{enum{DisplayPort=64};unsigned option(const char*,unsigned){return 0;}}
bool b5q_usb_cable_state(Cable*out){*out=physical();return true;}
void IOLockLock(void*){}void IOLockUnlock(void*){}
void clock_interval_to_deadline(unsigned n,unsigned scale,uint64_t*p){assert(scale==kMillisecondScale);*p=ms+n;}
void IOLockSleepDeadline(void*,void*,uint64_t deadline,int){assert(deadline>ms&&deadline-ms<=1000);ms=deadline;if(++sleeps>30)throw 1;}
void cableChanged(){auto c=physical();gCableWanted=c.signature();gRoleWanted=c.role();}
bool b5q_usb_otg(bool on){otg=on;if(!on)off++;return true;}
void leaveRole(int r){if(r==kRoleHost){leaves++;b5q_usb_otg(false);}gHostNub=nullptr;}
bool enterRole(int r){gHostNub=r==kRoleHost?(void*)1:nullptr;enters+=r==kRoleHost;gCoreRole=r;B5qMax77705::Cable c;b5q_usb_cable_state(&c);gAppliedCable=c;gAppliedOrientation=c.orientation();return r!=kRoleHost||b5q_usb_otg(true);}
bool b5q_dp_port_poll(B5qDpPortState*){return true;}bool b5q_dp_link_stop(){return true;}void b5q_dp_link_update(const B5qDpPortState*){}
bool qmpInit(bool){return true;}void selectUtmiClock(){}void retryDevicePower(){}void hostStats(){}void deviceStats(){}
void IOSleep(unsigned n){ms+=n;}
template<class... T>void IOLog(const char*,T...){ }
using wait_result_t=int;
void *current_thread(){return nullptr;}
void thread_set_thread_name(void*,const char*){}
void configureHostPorts(void*){}unsigned hostPortHoldCount(){return 2;}
ROLE
int main(){
 xhciRegisters[0]=0x40;xhciRegisters[(0x40+0x400)/4]=1;
 for(unsigned pin=0;pin<2;pin++){
  ms=sleeps=leaves=off=enters=0;otg=expire=false;reverse=pin;gRoleWanted=gRoleApplied=0;
  auto initial=physical();gCableWanted=gCableApplied=initial.signature();
  try{roleThread(nullptr,0);}catch(int){}
  assert(enters==1&&leaves==1&&off==1&&!otg&&!expire); // sole leave is real unplug at5s
 }
 // Demonstrate the missed physical Source window with the former1s sampling.
 ms=1000;otg=false;expire=false;assert(!physical().attached()&&expire);
 for(unsigned cc:{0x48u,0x88u}){
  Cable c;c.valid=true;c.cc0=cc;c.pd=0x87;assert(c.sourceCandidate()&&c.role()==2&&c.sourceVbus(2)&&c.pollIntervalMs()==50);
  auto sig=c.signature();c.cc0+=2;c.bc=0x80;c.cc1=9;assert(c.signature()==sig&&c.pollIntervalMs()==1000);
  c.cc0=cc;c.cc1=0;c.pd=7;assert(!c.attached()&&!c.sourceVbus(2)&&c.pollIntervalMs()==50);
  c.pd=0x87;c.cc1=2;assert(!c.attached()&&!c.sourceVbus(2));
  c.cc1=0;c.valid=false;assert(!c.attached()&&c.pollIntervalMs()==1000);
 }
 for(unsigned cc:{0xa1u,0xb1u}){Cable c;c.valid=true;c.cc0=cc;c.pd=7;assert(c.role()==1&&!c.sourceVbus(1));auto sig=c.signature();c.bc=0x80;assert(c.signature()==sig);}
 Cable hub;hub.valid=true;hub.cc0=0x41;hub.pd=0x87;assert(hub.role()==2&&!hub.sourceVbus(2));
 puts("PASS actual roleThread captures100msSourcewindow; candidate50ms/connected1s; VBUSfeedbackstable/no selfleave, realunplugoff; PD07/water/badI2C refused; a1/b1Device/PDhub preserved");
}
'''.replace('ROLE',function(q,'void roleThread('))
    execute(t,'typec-window',body)
print('PASS review9 production ASan/UBSan kernel regressions; physical hardware results remain pending')
