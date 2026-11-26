#!/usr/bin/env python3
from pathlib import Path
import hashlib,importlib.util,struct,subprocess,tempfile,tomllib

R=Path(__file__).resolve().parents[2]
P=R/'UniXNU-b5q/package'

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

wifi=load('review11_wifi',R/'UniXNU-b5q/scripts/build-b5q-wifi.py')
with tempfile.TemporaryDirectory(prefix='b5q-review11-wifi-') as td:
    out=Path(td);gen=wifi.prepare(R/'sources/UniXNU-sheng/drivers/Ath12kWifi',out)
    wmi=(gen/'wmi.c').read_text();htc=(gen/'htc.c').read_text();mac=(gen/'mac.c').read_text();pcic=(gen/'pcic.c').read_text()
    send=wmi[wmi.index('int ath11k_wmi_cmd_send('):]
    assert send.index('b5q_ath11k_trace_tx(1u')<send.index('wait_event_timeout_once(')
    assert 'b5q_ath11k_wmi_timeout(cmd_id)' in send and 'b5q_ath11k_trace_startup(4u, id' in wmi
    hsend=htc[htc.index('int ath11k_htc_send('):]
    assert 'ep->service_id == ATH11K_HTC_SVC_ID_HTT_DATA_MSG' in hsend
    assert hsend.index('b5q_ath11k_trace_tx(2u')<hsend.index('skb_push(skb')
    assert 'b5q_ath11k_trace_startup(2u, eid' in hsend and 'b5q_ath11k_trace_startup(3u, eid' in htc
    tasklet=pcic[pcic.index('static void ath11k_pcic_ce_tasklet('):pcic.index('static irqreturn_t ath11k_pcic_ce_interrupt_handler(')]
    handler=pcic[pcic.index('static irqreturn_t ath11k_pcic_ce_interrupt_handler('):pcic.index('static void ath11k_pcic_ext_grp_disable(')]
    assert 'ath11k_pcic_ce_irq_enable(ce_pipe->ab, ce_pipe->pipe_num)' in tasklet and 'enable_irq(' not in tasklet
    assert 'ath11k_pcic_ce_irq_disable(ab, ce_pipe->pipe_num)' in handler and 'disable_irq_nosync(' not in handler
    ext_poll=pcic[pcic.index('static int ath11k_pcic_ext_grp_napi_poll('):pcic.index('static irqreturn_t ath11k_pcic_ext_interrupt_handler(')]
    ext_irq=pcic[pcic.index('static irqreturn_t ath11k_pcic_ext_interrupt_handler('):pcic.index('static int\nath11k_pcic_get_msi_irq(')]
    assert 'ath11k_pcic_ext_grp_enable(irq_grp)' in ext_poll and 'enable_irq(' not in ext_poll
    assert 'ath11k_pcic_ext_grp_disable(irq_grp)' in ext_irq and 'disable_irq_nosync(' not in ext_irq
    assert pcic.count('enable_irq(')==2 and pcic.count('disable_irq_nosync(')==2
    add=mac[mac.index('static int ath11k_mac_op_add_interface('):mac.index('static void ath11k_mac_op_remove_interface(')]
    defaults=['ac_be = (struct wmi_wmm_params_arg){ .aifs = 3, .cwmin = 15, .cwmax = 1023 }',
              'ac_bk = (struct wmi_wmm_params_arg){ .aifs = 7, .cwmin = 15, .cwmax = 1023 }',
              'ac_vi = (struct wmi_wmm_params_arg){ .aifs = 2, .cwmin = 7, .cwmax = 15, .txop = 94 }',
              'ac_vo = (struct wmi_wmm_params_arg){ .aifs = 2, .cwmin = 3, .cwmax = 7, .txop = 47 }']
    assert all(x in add for x in defaults)
    assert max(add.index(x) for x in defaults)<add.index('ath11k_wmi_vdev_create(')
    start=mac[mac.index('static int ath11k_mac_op_start('):mac.index('static void ath11k_mac_op_stop(')]
    for x in ('ath11k_dp_tx_htt_h2t_ppdu_stats_req','WMI_PDEV_PARAM_MESH_MCAST_ENABLE',
              'ath11k_mac_config_mon_status_default(ar, true)','ath11k_wmi_pdev_lro_cfg'):
        assert x in start

ath=(P/'B5qAth11k.c').read_text()
diagnostic=ath[ath.index('static void b5q_ath11k_dump_state('):ath.index('void nw_wifi_hw_ready(')]
fatal=ath[ath.index('void b5q_ath11k_mhi_failed('):ath.index('void nw_wifi_set_platform(')]
for x in ('MHI_STATUS=%08x','MHI_EXEC_ENV=%08x','BHI_ERRCODE=%08x','BHI_ERRDBG1=%08x',
          'BHI_ERRDBG2=%08x','BHI_ERRDBG3=%08x','b5q_ath11k_trace_dump()'):
    assert x in diagnostic
assert 'b5q_ce_dump(ab,2);b5q_ce_dump(ab,3);' in diagnostic and 'lx_irq_disabled(irq)' in ath
assert fatal.index('b5q_ath11k_dump_state(')<fatal.index('ATH11K_FLAG_CRASH_FLUSH')
assert 'event="WMI-timeout"' not in ath and '"WMI-timeout"' in fatal
assert 'sequence<=64' in ath and 'startup-io seq=' in ath
assert '#define B5Q_TX_HISTORY_COUNT 16u' in ath and '__ATOMIC_RELEASE' in ath and '__ATOMIC_ACQUIRE' in ath
print('PASS review11 Wi-Fi: single-MSI CE/ext masking fixed, WMM defaults retained, timeout/fatal MHI+BHI+CE2/3 diagnostics and bounded bidirectional startup trace')

usb=(P/'QcomDwc3.cpp').read_text()
restore=usb[usb.index('void restoreHostGlobals()'):usb.index('void wantRole(')]
role=usb[usb.index('bool setCoreRole('):usb.index('bool followOrientation(')]
for body in (restore,role):
    assert '*usb2&=~(kUsb2SuspendPhy|kUsb2EnableLpm)' in body
    assert '*usb3&=~kUsb3SuspendPhy' in body
assert all(x in restore for x in ('*guctl|=kGuctlSprsCtrlTransEn','*guctl1=(*guctl1&~(7u<<21))|kGuctl1Host','*guctl2|=kGuctl2Host'))
assert '1u<<31' not in role and 'phyInit()' not in role and role.index('*gctl&=~(1u<<11)')<role.index('repeater(false')
assert 'kHostEventDumpCount=16' in usb and 'first-HCE' in usb and 'GUCTL2=%x' in usb
assert 'kUsbPortDebugOptions=0x40000119u' in usb and '"kUSBDebugOptions"' in usb and 'metaCast("AppleUSBHostPort")' in usb
set_power=usb[usb.index('IOReturn setPowerState(unsigned long state'):usb.index('// write-64-hi-lo-quirk')]
write64=usb[usb.index('void XHCI_WRITE64('):usb.index('\n    }\n};',usb.index('void XHCI_WRITE64('))]
assert 'b5q_log_sync' not in set_power and 'b5q_log_sync' not in write64
assert 'allowU3&&(firstHse||firstHce||firstU3)' in usb
assert 'UsbHostControllerUSB2LPMPolicy' not in usb and 'kUSBHostDeviceDisablePortLPM' not in usb

with tempfile.TemporaryDirectory(prefix='b5q-review11-usb-') as td:
    td=Path(td);source=td/'events.cpp';binary=td/'events'
    source.write_text(r'''#include "B5qUsbHostEvent.h"
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <map>
#include <vector>
int main(){using namespace B5qUsbHostEvent;std::map<uint64_t,uint64_t> m;
 const uint64_t table=0x1000,base=0x2000;m[table]=base;m[table+8]=32;
 for(unsigned i=0;i<32;i++){m[base+16*i]=0x100+i;m[base+16*i+8]=uint64_t((1u|(32u<<10)|(1u<<16)|(1u<<24)))<<32|((10u+i)<<24);}
 auto read=[&](uint64_t p,uint64_t&v){if(!m.count(p))return false;v=m[p];return true;};std::vector<unsigned> got;
 assert(latest(table,1,base+16*16,16,read,[&](unsigned,unsigned i,const Event&e){got.push_back(i);assert(e.type==32&&e.slot==1&&e.endpoint==1);}));
 assert(got.size()==16&&got.front()==15&&got.back()==0);puts("PASS review11 USB event window: exactly16 bounded entries ending at ERDP");}
''')
    subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-I',str(P),str(source),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)

bt=load('review11_bt',R/'UniXNU-b5q/scripts/b5q_bluetooth.py')
with tempfile.TemporaryDirectory(prefix='b5q-review11-bt-') as td:
    sources,_=bt.prepare(R/'sources/UniXNU-sheng/drivers/QcaBluetooth',P,
        R/'sources/UniXNU-sm8550-common/kits/Sm8550Platform',Path(td),R/'sources/UniXNU-sheng')
    tty=[p for p in sources if p.name=='qbt_tty.c'][0].read_text()
    getter=tty[tty.index('uint64_t qbt_transport_rx_dropped('):tty.index('\n}',tty.index('uint64_t qbt_transport_rx_dropped('))+2]
    assert 'lck_mtx_lock(&bt_tty_lock)' in getter and 'lck_mtx_unlock(&bt_tty_lock)' in getter
    assert 'return count' in getter
bluetooth=(P/'B5qBluetooth.cpp').read_text()
for x in ('stage=discovery inquiry=','le-param=','le-enable=','ext-param=','ext-enable=',
          'stage=transport tx=','malformed=','unmatched=','backpressure=','hardware-errors=','tty-rx-dropped='):
    assert x in bluetooth
pump=bluetooth[bluetooth.index('void pump('):bluetooth.index('int quiesce(')]
assert pump.index('qbt_rx_wake(bt.core)')<pump.index('qbt_receive(bt.core,&wakeByte,1)')

codesign=load('review11_codesign',R/'UniXNU-b5q/scripts/b5q_codesign.py')
addon=load('review11_addon',R/'UniXNU/scripts/addon-add-dir.py')
actual_addon=R/'artifacts/b5q-review10-ci-45788497473/extra/_temp/b5q-stage-data/gpu-addon.bin'
actual_trust=R/'artifacts/b5q-review10-ci-45788497473/extra/_temp/b5q-stage-data/owner-trust.bundle'
assert actual_addon.is_file() and actual_trust.is_file()
daemon={name:body for name,_,body in addon.read(actual_addon)}['sbin/bluetoothd']
before=codesign.inspect_code_directories(daemon);assert len(before)==1 and before[0]['platform']==0 and before[0]['flags']==2
old_entry=codesign.inspect_trust_entry(actual_trust.read_bytes(),before[0]['cdhash'])
assert old_entry['hash_type']==2 and old_entry['constraint_category']==0
with tempfile.TemporaryDirectory(prefix='b5q-review11-sign-') as td:
    td=Path(td);original=td/'original-bluetoothd'
    subprocess.run(['/usr/lib/llvm-17/bin/llvm-lipo',str(R/'artifacts/b5q-p2-work/os-root/usr/sbin/bluetoothd'),'-thin','arm64e','-output',str(original)],check=True)
    apple=codesign.inspect_code_directories(original.read_bytes());assert len(apple)==1 and apple[0]['platform']==27 and apple[0]['flags']==0 and apple[0]['page_hashes_valid']
    patched=td/'bluetoothd';patched.write_bytes(daemon)
    metadata=codesign.set_platform(patched,27);after=codesign.inspect_code_directories(patched.read_bytes())
    assert len(after)==1 and after[0]['platform']==27 and after[0]['page_hashes_valid'] and after[0]['cdhash']!=before[0]['cdhash']
    module=struct.pack('<I16sI',2,bytes(16),1)+bytes.fromhex(after[0]['cdhash'])+bytes([2,0,0,0])
    source=td/'trust';source.write_bytes(struct.pack('<II',1,8)+module);destination=td/'trusted'
    trust=codesign.set_trust_category(source,destination,after[0]['cdhash'],1)
    assert trust['constraint_category']==1 and codesign.inspect_trust_entry(destination.read_bytes(),after[0]['cdhash'])['constraint_category']==1

with tempfile.TemporaryDirectory(prefix='b5q-review11-amfi-') as td:
    td=Path(td);(td/'security').mkdir();source=td/'security/mac_base.c'
    source.write_bytes((R/'sources/UniXNU/out/feeds/xnu-3199e8bc/security/mac_base.c').read_bytes())
    subprocess.run(['patch','-s','-p1','-d',str(td),'-i',str(R/'UniXNU-b5q/patches/xnu/b5q-amfi-lwcr.patch')],check=True)
    patched=source.read_text();begin=patched.index('struct b5q_amfi_constraint_args {');end=patched.index('\n#if CONFIG_MACF',begin)
    helper=patched[begin:end]
    harness=td/'amfi.c';binary=td/'amfi'
    harness.write_text(r'''#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint64_t user_addr_t;typedef int32_t SInt32;typedef struct proc*proc_t;
struct proc{int pid;};struct __mac_syscall_args{const char*policy;int call;user_addr_t arg;};
#define MAXCOMLEN 16
static int enabled=1;static int PE_parse_boot_argn(const char*n,void*p,int z){assert(!strcmp(n,"no-lc")&&z==4);*(uint32_t*)p=enabled;return 1;}
static int copyin(user_addr_t p,void*out,size_t n){memcpy(out,(void*)(uintptr_t)p,n);return 0;}
static int copyout(const void*in,user_addr_t p,size_t n){memcpy((void*)(uintptr_t)p,in,n);return 0;}
static SInt32 OSIncrementAtomic(volatile SInt32*p){return __atomic_fetch_add(p,1,__ATOMIC_RELAXED);}
static int proc_pid(proc_t p){return p->pid;}static void proc_name(int p,char*b,int n){snprintf(b,n,"p%d",p);}
#define bzero(p,n) memset((p),0,(n))
HELPER
int main(void){struct proc p={42};struct b5q_amfi_constraint_error e={.error_code=19,.message="failed"};
 struct b5q_amfi_constraint_args a={0};a.error_out=(user_addr_t)(uintptr_t)&e;a.error_out_size=sizeof(e);
 struct __mac_syscall_args u={"AMFI",102,(user_addr_t)(uintptr_t)&a};
 assert(b5q_amfi_constraint_override(&p,&u,"AMFI",5));assert(!e.error_code&&!e.message[0]);
 e.error_code=7;assert(b5q_amfi_constraint_override(&p,&u,"AMFI",0));assert(!e.error_code);
 e.error_code=0;assert(!b5q_amfi_constraint_override(&p,&u,"AMFI",0));assert(!e.error_code);
 assert(!b5q_amfi_constraint_override(&p,&u,"Sandbox",5));u.call=101;assert(!b5q_amfi_constraint_override(&p,&u,"AMFI",5));
 u.call=102;a.error_out_size=4;assert(!b5q_amfi_constraint_override(&p,&u,"AMFI",5));enabled=0;a.error_out_size=0x404;assert(!b5q_amfi_constraint_override(&p,&u,"AMFI",5));
 puts("PASS applied XNU AMFI102 helper: C11/ASan/UBSan, exact64/0x404 ABI, real-call-first failure-only and bounded output clear");}
'''.replace('HELPER',helper))
    subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(harness),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
bluetooth_builder=(R/'UniXNU-b5q/scripts/build-b5q-bluetooth-userspace.py').read_text()
media_builder=(R/'UniXNU-b5q/scripts/build-b5q-media-runtime.py').read_text()
assert bluetooth_builder.index('set_platform(daemon,27)')<bluetooth_builder.index("actual=re.search")
assert 'set_trust_category(trust,platform_trust,daemon[\'cdhash\'],1)' in media_builder
amfi=(R/'UniXNU-b5q/patches/xnu/b5q-amfi-lwcr.patch').read_text()
for marker in ('uap->call != 102','strcmp(target, "AMFI")','PE_parse_boot_argn("no-lc"','args.error_out_size != sizeof(output)',
               'OSIncrementAtomic(&logged)','slot < 32','copyout(&output, args.error_out, sizeof(output))','error = 0'):
    assert marker in amfi
args=' '.join(tomllib.loads((R/'UniXNU-b5q/board.toml').read_text())['payload']['kernel_args']).encode()
assert len(args)==1023
print('PASS review11 Bluetooth: real review10 CodeDirectory page hashes parsed, platform27 changes CDHash, v2 category1 enforced, AMFI102 ABI/rate-limit patch and health telemetry retained')
