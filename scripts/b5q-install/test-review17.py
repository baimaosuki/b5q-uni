#!/usr/bin/env python3
"""Run the real Review17 USB slots, generated Wi-Fi and header-only H4 tracking."""
import argparse
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

R = Path(__file__).resolve().parents[2]
P = R / 'UniXNU-b5q/package'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--out', type=Path, default=Path(os.environ.get('B5Q_GATE_WORK', R / 'artifacts/b5q-review17-local')))
W = parser.parse_args().out.resolve()
W.mkdir(parents=True, exist_ok=True)
checks = []


def function(text, signature):
    start = text.index(signature)
    at = text.index('{', start)
    depth, end = 1, at + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


def run(name, args):
    result = subprocess.run(list(map(str, args)), cwd=R, text=True, capture_output=True)
    output = result.stdout + result.stderr
    (W / (name + '.log')).write_text(output)
    if result.returncode:
        raise RuntimeError(name + ':\n' + output)
    checks.append(dict(name=name, passed=True, log_sha256=hashlib.sha256(output.encode()).hexdigest()))
    print('PASS', name, flush=True)


def model(temp, name, text):
    source = temp / (name + '.cpp')
    source.write_text(text)
    binary = temp / name
    run(name + '-compile', ['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
        '-Wno-misleading-indentation', '-Wno-unused-parameter', '-O1', '-g', '-pthread',
        '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-I' + str(P), source, '-o', binary])
    run(name + '-ASan-UBSan', [binary])


with tempfile.TemporaryDirectory(prefix='review17-', dir=W) as td:
    temp = Path(td)
    usb = (P / 'QcomDwc3.cpp').read_text()
    tree = ast.parse((R / 'tests/b5q-ufs/test-usb-irq.py').read_text())
    stub = next(n.value.value for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == 'stub' for t in n.targets))
    body = usb[usb.index('class QcomDwc3Nub;'):usb.index('OSDefineMetaClassAndStructors(QcomDwc3Nub,')]
    model(temp, 'usb-source-slots', stub + body + r'''
#include <initializer_list>
using B5qUsbIrq::Delivery;
unsigned hits[3]{};bool recurse=false,leaveDisabled=false,block=false;
std::atomic<bool> entered{false},proceed{false},retired{false};
void slotAction(OSObject *owner,void *context,IOService *service,int source){
 assert(owner==expectedOwner&&context==expectedContext&&source>=0&&source<3);hits[source]++;
 auto*n=static_cast<QcomDwc3Nub*>(service);
 if(source>0&&recurse){
  assert(n->disableInterrupt(source)==0);assert(n->enableInterrupt(source)==0);
  assert(n->deliverSource(source)==Delivery::BusyInFlight);
  if(leaveDisabled)n->disableInterrupt(source);
 }
 if(block){entered=true;while(!proceed)std::this_thread::yield();}
}
int main(){
 OSObject owner;expectedOwner=&owner;int cookie=9;expectedContext=&cookie;
 QcomDwc3Nub device;int type=-1;
 assert(device.maxSources==1&&device.getInterruptType(0,&type)==0&&type==kIOInterruptTypeLevel);
 for(int source:{-1,1,2,3}){
  assert(device.getInterruptType(source,&type)==kIOReturnNoInterrupt);
  assert(device.registerInterrupt(source,&owner,slotAction,&cookie)==kIOReturnNoInterrupt);
  assert(device.enableInterrupt(source)==kIOReturnNoInterrupt&&device.disableInterrupt(source)==kIOReturnNoInterrupt);
  assert(device.unregisterInterrupt(source)==kIOReturnNoInterrupt);
 }
 assert(device.deliverSource(1)==Delivery::BadSource);
 QcomDwc3Nub host;host.maxSources=3;
 QcomDwc3Nub::route(&host);
 assert(host.deliverSource(0)==Delivery::BadSource&&host.deliverSource(3)==Delivery::BadSource);
 assert(host.deliverSource(1)==Delivery::NotRegistered);
 unsigned masks=maskCount,attaches=attachCount;
 for(int i:{1,2}){
  assert(host.getInterruptType(i,&type)==0&&type==kIOInterruptTypeLevel);
  assert(host.registerInterrupt(i,&owner,slotAction,&cookie)==0);
  assert(host.deliverSource(i)==Delivery::NotEnabled);
  assert(host.enableInterrupt(i)==0);
 }
 assert(maskCount==int(masks)&&attachCount==int(attaches));
 uint32_t observed=gIrqWindow.count;recurse=true;
 assert(host.deliverSource(1)==Delivery::Delivered&&hits[1]==1&&hits[2]==0);
 assert(host.deliverSource(2)==Delivery::Delivered&&hits[2]==1);
 assert(gIrqWindow.count==observed&&maskCount==int(masks));
 leaveDisabled=true;host.deliverSource(1);assert(host.deliverSource(1)==Delivery::NotEnabled);
 assert(host.deliverSource(2)==Delivery::Delivered);leaveDisabled=false;recurse=false;
 assert(host.registerInterrupt(0,&owner,slotAction,&cookie)==0);host.enableInterrupt(0);
 uint32_t beforeFire=gIrqWindow.count;fire();assert(hits[0]==1&&gIrqWindow.count==beforeFire+1);
 assert(host.enableInterrupt(1)==0);block=true;
 std::thread caller([&]{assert(host.deliverSource(1)==Delivery::Delivered);});
 while(!entered)std::this_thread::yield();
 std::thread unreg([&]{host.unregisterInterrupt(1);retired=true;});
 std::this_thread::sleep_for(std::chrono::milliseconds(5));assert(!retired&&owner.refs==4);
 proceed=true;caller.join();unreg.join();assert(retired&&host.deliverSource(1)==Delivery::NotRegistered);
 host.unregisterInterrupt(0);host.unregisterInterrupt(2);QcomDwc3Nub::route(nullptr);assert(owner.refs==1);
 delete gInterruptLock;gInterruptLock=nullptr;
 Bridge b;for(unsigned n=0;n<1500;n++)assert(!b.noteSources(true,0x1000+16*n,Delivery::Delivered,true,0x2000+16*n,Delivery::NotRegistered));
 assert(b.kicks==1500&&b.ir1Delivered==1500&&b.ir2Delivered==0&&b.disabled==1500);
 for(unsigned n=0;n<999;n++)assert(!b.noteSources(true,0x1000+16*1499,Delivery::Delivered,false,0x2000+16*1499,Delivery::Delivered));
 assert(b.noteSources(true,0x1000+16*1499,Delivery::Delivered,false,0x2000+16*1499,Delivery::Delivered)&&b.intervalMs()==50);
 b.noteSources(false,0x1000+16*1499,Delivery::NotEnabled,true,0xdeadbeef,Delivery::Delivered);
 assert(b.intervalMs()==1&&b.ir2Delivered==1&&b.kicks==2501);
 b.noteSources(false,0,Delivery::Delivered,false,0,Delivery::Delivered);assert(!b.misses&&!b.haveLast);
}
'''.replace(' Bridge b;', ' B5qUsbIrq::Bridge b;'))
    bridge = function(usb, 'static void hostIrqBridge(')
    assert 'active1?gHostNub->deliverSource(1)' in bridge and 'active2?gHostNub->deliverSource(2)' in bridge
    assert 'gXhciRegs.va[(op + 4u) / 4u]' in bridge
    assert 'd1=%u d2=%u' in bridge and 'er1=%llx er2=%llx' in bridge
    deliver = function(usb, 'B5qUsbIrq::Delivery deliverSource(')
    assert 'observe(' not in deliver and 'armcpu_spi_' not in deliver
    assert 'nub->maxSources=3;' in function(usb, 'void enterHost()')
    assert 'nub->maxSources=1;' in function(usb, 'extern "C" void qcom_dwc3_publish(')
    assert len(json.loads((R / 'UniXNU-b5q/scripts/usb-xhci-26C5035r.json').read_text())['slots']) == 427
    checks.append(dict(name='usb-exact-source-routing-427-abi', passed=True))

    sys.path.insert(0, str(R / 'UniXNU-b5q/scripts'))
    import b5q_wifi
    selected = b5q_wifi.prepare(R / 'sources/UniXNU-sheng', temp / 'wifi')
    text = selected.read_text()
    flush = function(text, 'void flush_rx()')
    drain = function(text, 'int drain_disconnect()')
    assert 'if (!error && gIf && (ifnet_capabilities_enabled(gIf) & 0x400u))' in flush
    assert flush.index('ifnet_input(') < flush.index('ifnet_stat_increment_in') < flush.index('wifi-net: rx-flush')
    assert 'current.state >= NW_STA_AUTH || nw_wifi_disconnect_pending()' in text
    assert text.index('wifi-net: pre-join-drain') < text.index('gKeyed = hasKey; int r = nw_wifi_connect(')
    for field in ['wifi-net: leave-ctx', 'proc_selfpid()', 'wifi-net: join-ctx', 'cached_freq=', 'ssid_hex=', '__atomic_fetch_add(&gLeaveContextLogged', '__atomic_fetch_add(&gJoinContextLogged']:
        assert field in text, field
    original = (R / 'sources/UniXNU-sheng/package/WifiNet.cpp').read_text()
    # Preserve event9 layouts verbatim, including its 540-byte bounds assertion.
    for line in original.splitlines():
        if '540' in line or 'static_assert(sizeof(' in line:
            assert line in text
    pending_source = b5q_wifi.select_shared(R / 'sources/UniXNU-sheng/drivers/Ath12kWifi/src/nw_mainline.c', temp / 'shared').read_text()
    assert 'ui.operation == NW_CONTROL_DISCONNECT_REQUEST' in function(pending_source, 'int nw_wifi_disconnect_pending(')
    assert "EXPORTS.add('nw_wifi_disconnect_pending')" in (R / 'UniXNU-b5q/scripts/build-b5q-wifi.py').read_text()
    associate = text.index('case kAssociate: {')
    join_begin = text.index('      nw_wifi_status current;', associate)
    join_guard = text[join_begin:text.index('      char pass[65];', join_begin)]
    model(temp, 'wifi-real-flush-drain', r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <algorithm>
using errno_t=int;using mbuf_t=void*;void*gIf=(void*)1;
struct ifnet_stat_increment_param{unsigned packets_in=0,bytes_in=0;};
struct ifnet_stats_param{uint64_t packets_in,errors_in,dropped;};
unsigned cap=0x400,in=0,octets=0,inputError=0,stalls=0;
int ifnet_input(void*,void*,ifnet_stat_increment_param*p){if(!inputError&&!(cap&0x400)){in+=p->packets_in;octets+=p->bytes_in;}return inputError;}
unsigned ifnet_capabilities_enabled(void*){return cap;}
void ifnet_stat_increment_in(void*,unsigned count,unsigned bytes,unsigned){in+=count;octets+=bytes;}
void ifnet_stat(void*,ifnet_stats_param*p){p->packets_in=in;}
mbuf_t gRxHead,gRxTail,gRxSpare,gRxSpareParked;uint32_t gRxPendingPackets,gRxPendingBytes,gRxBatches,gRxLargestBatch,gRxBatchSizes[7]{},gRxErrors,gRxLastError,gRxFrames;
struct{uint64_t input=0;}gRxTime;uint64_t rx_now(){return 10;}
void free_rx_list(mbuf_t){}
template<class... T>void log(int,const char*,T...){}
FLUSH
constexpr int NW_STA_AUTH=3,ETIMEDOUT=60;struct nw_wifi_status{unsigned state=0;};
unsigned waited=0,state=0;bool queued=false,hang=false;void disconnect_user(){queued=true;state=0;}void sheng_wifi_wake(){}
int nw_wifi_disconnect_pending(){return queued;}
void nw_wifi_status_get(nw_wifi_status*p){p->state=state;}
void IOSleep(unsigned n){waited+=n;if(waited>=30&&!hang)queued=false;}
DRAIN
bool gPower=true;constexpr int ENETDOWN=50;uint32_t gPreJoinDrainLogged=0;unsigned connects=0;
uint64_t continuous_ms(){return waited;}
int join(){JOIN_GUARD connects++;return 0;}
int main(){for(unsigned sky:{0u,0x400u})for(unsigned err:{0u,1u}){
 cap=sky;inputError=err;in=octets=0;gRxHead=gRxTail=(void*)1;gRxPendingPackets=3;gRxPendingBytes=180;
 flush_rx();assert(in==(err?0u:3u)&&octets==(err?0u:180u));assert(!gRxHead);}
 waited=0;assert(drain_disconnect()==0&&waited==30&&!queued);
 waited=0;hang=true;assert(drain_disconnect()==ETIMEDOUT&&waited==2000&&queued);
 hang=false;queued=false;state=NW_STA_AUTH;waited=connects=0;assert(join()==0&&waited==30&&connects==1);
 queued=true;state=0;waited=0;assert(join()==0&&waited==30&&connects==2);
 queued=false;state=0;waited=0;assert(join()==0&&!waited&&connects==3);
 queued=true;hang=true;waited=0;assert(join()==ETIMEDOUT&&waited==2000&&connects==3);
}
'''.replace('FLUSH', flush).replace('DRAIN', drain).replace('JOIN_GUARD', join_guard))
    checks.append(dict(name='wifi-generated-join-leave-event-layout', passed=True))

    model(temp, 'bluetooth-handle-context', r'''
#include <cassert>
#include <string>
#include <vector>
#include "B5qBtH4Tap.h"
uint64_t ms=100;std::vector<std::string> lines;
void line(void*,const char*s){lines.emplace_back(s);}uint64_t now(void*){return ms;}
void event(B5qBtH4Tap&t,uint8_t code,std::initializer_list<uint8_t> data){std::vector<uint8_t>b{4,code,uint8_t(data.size())};b.insert(b.end(),data);b5q_bt_h4_tap_rx(&t,b.data(),b.size());}
void cmd(B5qBtH4Tap&t,unsigned op,std::initializer_list<uint8_t> data){std::vector<uint8_t>b{1,uint8_t(op),uint8_t(op>>8),uint8_t(data.size())};b.insert(b.end(),data);b5q_bt_h4_tap_tx(&t,b.data(),b.size());}
void acl(B5qBtH4Tap&t,bool tx,unsigned cid){uint8_t b[]={2,0x40,0x20,10,0,6,0,uint8_t(cid),uint8_t(cid>>8),2,1,2,0,0x19,0};if(tx)b5q_bt_h4_tap_tx(&t,b,sizeof b);else b5q_bt_h4_tap_rx(&t,b,sizeof b);}
int main(){B5qBtH4Sink sink{line,now};B5qBtH4Tap t;b5q_bt_h4_tap_init(&t,&sink,nullptr,1);
 event(t,3,{0,0x40,0,1,2,3,4,5,6,1,0});auto*h=b5q_h4_handle(&t,0xf040,0);assert(h&&h->active&&!h->is_le&&h->conn_ms==100);
 ms=200;acl(t,true,0x40);ms=250;acl(t,false,1);assert(h->tx_acl==1&&h->rx_acl==1&&h->last_tx_cid==0x40&&h->last_rx_cid==1&&h->last_psm==0x19);
 event(t,0x14,{0,0x40,0,2,0x20,0});assert(h->mode==2&&h->mode_interval==32&&t.stats.mode_changes==1);
 cmd(t,0x0c37,{0x40,0,0x80,0x0c});assert(h->sup_slots==3200);
 event(t,0x38,{0x40,0,0,0x10});assert(h->sup_slots==4096&&t.stats.supervision_changes==1);
 for(unsigned op:{0x0428u,0x0429u,0x043du,0x043eu})cmd(t,op,{});
 event(t,0x2c,{0,0x41,0});event(t,0x2d,{0,0x41,0});event(t,0x12,{0,1,2,3,4,5,6,1});assert(t.stats.sco_commands==4&&t.stats.sco_events==2&&t.stats.role_changes==1);
 for(unsigned i=0;i<100;i++)acl(t,true,0x40);assert(t.quota.cid==80);
 unsigned old=lines.size();acl(t,false,1);assert(lines.size()==old+1&&lines.back().find("sig-code=")!=std::string::npos);
 t.quota.total=B5Q_BT_H4_QUOTA_TOTAL;t.quota.key=B5Q_BT_H4_QUOTA_KEY;
 ms=1000;event(t,5,{0,0x40,0,8});assert(!h->active);
 const std::string &ctx=lines.back();assert(ctx.find("h4-disconn-ctx")!=std::string::npos);
 for(const char*s:{"reason=0x08","le=0","alive_ms=900","since_tx_ms=750","since_rx_ms=750","tx_acl=101","rx_acl=2","mode=2","intv=32","sup_slots=4096","last_psm=0x0019"})assert(ctx.find(s)!=std::string::npos);
 assert(t.quota.total==1600&&t.disconnLogged==1);
 for(unsigned i=0;i<40;i++)event(t,5,{0,0x40,0,8});assert(t.disconnLogged==32);
 b5q_bt_h4_tap_reset_session(&t);assert(!t.disconnLogged&&!t.handles[0].active);
 // LE connection and update timeout fields, including Enhanced Connection Complete.
 event(t,0x3e,{1,0,0x40,0,0,0,1,2,3,4,5,6,0x18,0,0,0,0x34,0x12,0});
 h=b5q_h4_handle(&t,0x40,0);assert(h&&h->is_le&&h->sup_slots==0x1234);
 event(t,0x3e,{3,0,0x40,0,0x18,0,0,0,0x56,0x34});assert(h->sup_slots==0x3456);
 event(t,5,{0,0x40,0,8});
 event(t,0x3e,{0x0a,0,0x40,0,0,0,1,2,3,4,5,6,0,0,0,0,0,0,0,0,0,0,0,0,0x18,0,0,0,0x78,0x56,0});
 h=b5q_h4_handle(&t,0x40,0);assert(h&&h->is_le&&h->sup_slots==0x5678);
 for(unsigned i=1;i<8;i++)assert(b5q_h4_handle(&t,0x40+i,1));assert(!b5q_h4_handle(&t,0x99,1));
 event(t,5,{0,0x40,0,8});assert(b5q_h4_handle(&t,0x99,1));
}
''')

    # The firmware/clock/FIFO executor is unchanged; only sink and metadata are added.
    old_bt = subprocess.check_output(['git', 'show', 'HEAD:UniXNU-b5q/package/B5qBluetooth.cpp'], cwd=R).decode()
    bt = (P / 'B5qBluetooth.cpp').read_text()
    for signature in ['int clockVote(', 'void rxIrq(', 'void disarmRxWake(', 'void worker(', 'int setRate(', 'int powerOff(']:
        baseline=function(old_bt, signature)
        if signature.startswith('void worker('):
            baseline=baseline.replace('        if(!deadline){thread_yield_to_preemption();continue;}\n        waitUntil(nullptr,deadline);','        waitUntil(nullptr,b5q_bt_worker_deadline(deadline,t));')
        assert baseline == function(bt, signature), signature
    assert function(old_bt, 'int powerOn(') == function(bt, 'int powerOn(')
    assert 'nvm=%s nvm_bytes=%u' in bt and 'h4-disconn-ibs gated=%u wake_ind=%llu sleep_ind=%llu bt_rx_dropped=%llu' in bt
    checks.append(dict(name='bluetooth-observation-only-transport-byte-identity', passed=True))

# Review18 explicitly adds clock prerequisites and breadcrumbs to Link/Session;
# their protocol, ABI and MMIO sequencing are covered by Review18 + all26 DP groups.
for name in ['B5qDpBoard.h', 'B5qDpPhy.h', 'B5qDpClock.h', 'B5qDpDisplay.cpp']:
    assert (P / name).read_bytes() == subprocess.check_output(['git', 'show', 'HEAD:UniXNU-b5q/package/' + name], cwd=R)
assert len(list((R / 'tests/b5q-ufs').glob('test-dp-*.py'))) == 26
checks.append(dict(name='dp-untouched-26-groups-and-adsp-skipped-redline', passed=True))
report = dict(status='HOST_VERIFIED_PENDING_HARDWARE', passed=True, hardware_verified=False, checks=checks,
              adsp='skipped_redline: stage13 logging is generated by scripts/b5q_adsp.py from sources/.../AdspProbe.cpp, not package source',
              commit_performed=False, push_performed=False, ci_triggered=False, esp_created=False, phone_accessed=False)
(W / 'review17-tests.json').write_text(json.dumps(report, indent=2) + '\n')
print('PASS Review17 source-specific USB delivery, Skywalk RX/drained joins and per-handle H4 context')
