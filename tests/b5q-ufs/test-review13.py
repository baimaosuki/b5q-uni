#!/usr/bin/env python3
"""review13: PD VBUS-only swap, host-port power/edges, RDDM wait/scan, H4 tap."""
import argparse
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
parser.add_argument('--out', type=Path, default=Path(os.environ.get('B5Q_GATE_WORK', R / 'artifacts/b5q-review13-local')))
W = parser.parse_args().out.resolve()
W.mkdir(parents=True, exist_ok=True)
checks = []


def function(text, signature):
    start = text.index(signature)
    brace = text.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


def block(text, signature):
    start = text.index(signature)
    brace = text.index('{', start)
    depth = 1
    end = brace + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[brace:end]


def execute(name, command, **kwargs):
    result = subprocess.run(list(map(str, command)), cwd=R, capture_output=True, text=True, **kwargs)
    (W / (name + '.log')).write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(name + ':\n' + result.stdout + result.stderr)
    checks.append(dict(name=name, passed=True,
                       log_sha256=hashlib.sha256((result.stdout + result.stderr).encode()).hexdigest()))
    print('PASS', name, flush=True)
    return result.stdout


def model(t, name, source, cpp=False, includes=()):
    path = t / (name + ('.cpp' if cpp else '.c'))
    path.write_text(''.join('#include "%s"\n' % include for include in includes) + source)
    binary = t / name
    execute(name + '-compile', ['c++' if cpp else 'cc', '-std=c++17' if cpp else '-std=gnu11',
                               '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                               '-fno-omit-frame-pointer', '-pthread', str(path), '-o', str(binary)])
    execute(name + '-ASan-UBSan', [binary])


usb = (P / 'QcomDwc3.cpp').read_text()
role = function(usb, 'void roleThread(')
hot = block(role, 'if(B5qUsbHostRole::canHotSwapVbus(view))')
assert 'leaveRole(' not in hot and 'enterRole(' not in hot
assert 'b5q_usb_otg(source)' in hot and 'swapCable.sourceVbus(role)' in hot
assert r'qcom-dwc3: host-vbus-swap power=%u->%u source=%u ok=%u\n' in hot
assert 'gAppliedCable=swapCable' in hot and 'gAppliedOrientation=swapCable.orientation()' in hot
assert hot.index('b5q_usb_otg(source)') < hot.index('continue;')
assert 'gCableApplied=cableVersion' in hot
assert role.index('B5qUsbHostRole::canHotSwapVbus(view)') < role.index('leaveRole(__atomic_load')
wake=role[role.index('IOLockSleepDeadline'):role.index('canHotSwapVbus(view)')]
assert wake.index('b5q_dp_port_poll(&port)') < wake.index('const unsigned liveDp=')
assert 'const unsigned liveDp=dpEnabled&&port.configured?port.lanes:0' in role
assert '!dpEnabled||liveDp==gDpLanes' in role
assert 'requestedDp==gDpLanes' not in role[role.index('const unsigned liveDp='):role.index('canHotSwapVbus(view)')]
configure = function(usb, 'void configureHostPorts(IOService *host) {')
for text in ('OSDictionary *forceSettings', '"UsbForcePower"', 'OSNumber::withNumber(1u,32)',
             '"B5qPortForcePowerApplied"', '"B5qPortForcePowerRc"', '"B5qPortForcePowerTries"',
             'ensureHostPortHold(port)', 'tries<4',
             r'qcom-dwc3: port-force-power name=%s cur=%lu rc=%08x\n'):
    assert text in configure, text
assert configure.index('forceSettings->setObject("UsbForcePower"') < configure.index('port->setProperties(forceSettings)')
assert 'kUSBDebugOptions' in configure and 'settings->setObject("kUSBDebugOptions"' in configure
assert configure.index('if(fpRc==kIOReturnSuccess)') < configure.index('B5qPortForcePowerTries",tries+1u')
assert configure.count('port->setProperty("B5qPortForcePowerApplied"')==1
stats = function(usb, 'void hostStats() {')
for text in ('host-port-edge', 'device-drop', 'dmaDiagnostics("port-edge")', 'edgeDumps<4', 'B5qUsbHostRole::portEdge',
             'idVendor', 'idProduct', 'bcdDevice', 'bDeviceClass', 'bDeviceSubClass', 'bDeviceProtocol',
             'USB Address', 'USBSpeed', 'kUSBProductString', 'hostPortPowerEdges(gHost)'):
    assert text in stats, text
assert stats.index('configureHostPorts(gHost)') < stats.index('hostPortPowerEdges(gHost)')
checks.append(dict(name='USB-PD-hot-swap-and-port-contracts', passed=True))

with tempfile.TemporaryDirectory(prefix='review13-', dir=W) as td:
    t = Path(td)
    model(t, 'usb-hot-swap-view', r'''
#include <cassert>
#include <cstdint>
int main(){B5qUsbHostRole::View v={true,true,true,true,true,false,true,true,true};
 assert(B5qUsbHostRole::canHotSwapVbus(v));
 v.wantedHost=false;assert(!B5qUsbHostRole::canHotSwapVbus(v));v.wantedHost=true;
 v.hostObjects=false;assert(!B5qUsbHostRole::canHotSwapVbus(v));v.hostObjects=true;
 v.dpLanesUnchanged=false;assert(!B5qUsbHostRole::canHotSwapVbus(v));v.dpLanesUnchanged=true;
 v.cableValid=false;assert(!B5qUsbHostRole::canHotSwapVbus(v));v.cableValid=true;
 v.cableWater=true;assert(!B5qUsbHostRole::canHotSwapVbus(v));v.cableWater=false;
 v.cableAttached=false;assert(!B5qUsbHostRole::canHotSwapVbus(v));v.cableAttached=true;
 v.cableHost=false;assert(!B5qUsbHostRole::canHotSwapVbus(v));v.cableHost=true;
 v.orientationUnchanged=false;assert(!B5qUsbHostRole::canHotSwapVbus(v));v.orientationUnchanged=true;
 v.appliedHost=false;assert(!B5qUsbHostRole::canHotSwapVbus(v));
 assert(!B5qUsbHostRole::portEdge(0,0));
 assert(B5qUsbHostRole::portEdge(0,1u<<17));
 assert(B5qUsbHostRole::portEdge(0,1u<<18));
 assert(B5qUsbHostRole::portEdge(0,1u<<22));
 assert(!B5qUsbHostRole::portEdge(1u<<17,1u<<17));
 assert(!B5qUsbHostRole::portEdge((1u<<17)|(1u<<18),1u<<17));
 assert(B5qUsbHostRole::portEdge(2u,0u));
 assert(!B5qUsbHostRole::portEdge(0u,2u));
 return 0;}
''', cpp=True, includes=[str(P / 'B5qUsbHostRole.h')])

    model(t, 'usb-force-power', r'''
#include <cassert>
#include <cstdint>
#include <cstring>
#include <memory>
#include <map>
#include <string>
#include <vector>
struct OSObject{virtual ~OSObject()=default;};
static std::vector<std::unique_ptr<OSObject>> allocations;
template<class T>T*track(T*p){allocations.emplace_back(p);return p;}
struct OSNumber:OSObject{unsigned value;explicit OSNumber(unsigned n):value(n){}
 static OSNumber*withNumber(unsigned n,unsigned bits){assert(bits==32);return track(new OSNumber(n));}
 unsigned unsigned32BitValue(){return value;}};
struct OSDictionary:OSObject{std::map<std::string,OSObject*> values;
 static OSDictionary*withCapacity(unsigned n){assert(n==1);return track(new OSDictionary);}
 void setObject(const char*n,OSObject*p){values[n]=p;}};
struct OSIterator:OSObject{std::vector<OSObject*>values;unsigned pos=0;
 OSObject*getNextObject(){return pos<values.size()?values[pos++]:nullptr;}};
using IOReturn=unsigned;constexpr unsigned kIOReturnSuccess=0,kUsbPortDebugOptions=0x40000119u,kUsbHostDebugOptions=0x4000015du;
constexpr unsigned kXhciRegisterBytes=0x8000;static uint32_t registers[kXhciRegisterBytes/4]{};
static struct{uint32_t *va=registers;}gXhciRegs;
static OSObject yes;static OSObject*kOSBooleanTrue=&yes;static const char*gIOServicePlane="service";
static unsigned powerLogs,debugLogs,forceLogs;
template<class...T>void IOLog(const char*format,T...){if(strstr(format,"port-force-power"))forceLogs++;else if(strstr(format,"port-power"))powerLogs++;else debugLogs++;}
struct IOService:OSObject{
 std::map<std::string,OSObject*>props;std::vector<OSObject*>children;bool port=false;
 bool holdFail=false;
 unsigned debugCalls=0,forceCalls=0,powerCalls=0,state=2,powerError=0,forceError=0;
 const char*getName(){return port?"AppleUSB20XHCIPort":"host";}
 OSObject*getProperty(const char*n){auto it=props.find(n);return it==props.end()?nullptr:it->second;}
 void setProperty(const char*n,OSObject*p){props[n]=p;}
 void setProperty(const char*n,unsigned v,unsigned bits){setProperty(n,OSNumber::withNumber(v,bits));}
 IOReturn setProperties(OSDictionary*d){
  if(d->values.count("UsbForcePower")){forceCalls++;assert(d->values.size()==1);auto*n=dynamic_cast<OSNumber*>(d->values["UsbForcePower"]);assert(n&&n->value==1);return forceError;}
  debugCalls++;assert(d->values.size()==1);auto*n=dynamic_cast<OSNumber*>(d->values["kUSBDebugOptions"]);assert(n&&n->value==(port?kUsbPortDebugOptions:kUsbHostDebugOptions));return 0;}
 OSObject*metaCast(const char*n){assert(!strcmp(n,"AppleUSBHostPort"));return port?this:nullptr;}
 OSIterator*getChildIterator(const char*plane){assert(plane==gIOServicePlane);auto*i=track(new OSIterator);i->values=children;return i;}
 unsigned long getPowerState(){return state;}
 IOReturn changePowerStateTo(unsigned long n){assert(n==3);powerCalls++;if(!powerError)state=3;return powerError;}
};
enum PortHoldResult{kPortHoldAttached,kPortHoldPending,kPortHoldFailed};
static PortHoldResult ensureHostPortHold(IOService*p){return p->holdFail?kPortHoldFailed:kPortHoldAttached;}
static void setHostPortHoldOwner(IOService*){}
#define OSDynamicCast(T,p) dynamic_cast<T*>(p)
#define OSSafeReleaseNULL(p) do{(p)=nullptr;}while(0)
HELPER
int main(){
 registers[0]=0x40;registers[(0x40+0x400)/4]=1;
 IOService host,port;port.port=true;host.children={&port};
 configureHostPorts(&host);
 assert(host.debugCalls==1&&port.debugCalls==1&&port.forceCalls==0&&port.powerCalls==0);
 assert(port.getProperty("B5qPortPowerPinned")&&!port.getProperty("B5qPortForcePowerApplied"));
 assert(debugLogs==2&&forceLogs==0);
 unsigned fc=port.forceCalls,dc=port.debugCalls;
 for(unsigned n=0;n<8;n++)configureHostPorts(&host);
 assert(port.forceCalls==fc&&port.debugCalls==dc);
 IOService retry;retry.port=true;retry.holdFail=true;retry.forceError=5;retry.state=3;
 host.children.push_back(&retry);
 for(unsigned n=0;n<3;n++)configureHostPorts(&host);
 assert(retry.forceCalls==3&&!retry.getProperty("B5qPortForcePowerApplied"));
 auto*tries=dynamic_cast<OSNumber*>(retry.getProperty("B5qPortForcePowerTries"));
 assert(tries&&tries->value==3&&!retry.getProperty("B5qPortPowerPinned"));
 retry.forceError=0;configureHostPorts(&host);
 assert(retry.forceCalls==4&&retry.getProperty("B5qPortForcePowerApplied")&&retry.getProperty("B5qPortPowerPinned"));
 unsigned locked=retry.forceCalls;for(unsigned n=0;n<8;n++)configureHostPorts(&host);
 assert(retry.forceCalls==locked);
 IOService hardFail;hardFail.port=true;hardFail.holdFail=true;hardFail.forceError=5;
 host.children.push_back(&hardFail);
 for(unsigned n=0;n<12;n++)configureHostPorts(&host);
 assert(hardFail.forceCalls==4&&!hardFail.getProperty("B5qPortPowerPinned"));
 auto*hardTries=dynamic_cast<OSNumber*>(hardFail.getProperty("B5qPortForcePowerTries"));
 assert(hardTries&&hardTries->value==4&&!hardFail.getProperty("B5qPortForcePowerApplied"));
 hardFail.holdFail=false;configureHostPorts(&host);assert(hardFail.getProperty("B5qPortPowerPinned"));
 return 0;}
'''.replace('HELPER', '#include "'+str(P/'B5qUsbHostRole.h')+'"\n'+configure), cpp=True)

    ath = (P / 'B5qAth11k.c').read_text()
    rddm = (P / 'B5qAth11kRddm.h').read_text()
    for text in ('#define B5Q_TX_HISTORY_COUNT 32u', '#define B5Q_WMI_RX_HISTORY_COUNT 32u',
                 '#define B5Q_WMI_RX_DUMP_COUNT 16u',
                 'rddm-status rxvec=%08x state=%u waited-ms=%u entries=%u',
                 'rddm-hit idx=%u seg=%u off=%06x text=\'%s\'', 'sram-assert skipped/expected-zero in RDDM',
                 'exec==MHI_EE_RDDM||reason==MHI_CB_EE_RDDM', 'b5q_rddm_dump(controller)',
                 'dma_sync(buffer->dma_addr,buffer->len,2 /* DMA_FROM_DEVICE */)',
                 'b5q_rddm_segment_nonzero(buffer->buf,buffer->len,&nonzero)',
                 'b5q_rddm_wait_rxvec(b5q_rddm_read_status,b5q_rddm_delay'):
        assert text in ath, text
    assert 'wait_event_timeout' not in rddm and 'msleep' not in rddm and 'mutex' not in rddm
    dump = function(ath, 'static void b5q_ath11k_dump_state(')
    assert dump.index('b5q_ath11k_trace_dump()') < dump.index('b5q_rddm_dump(controller)')
    assert dump.index('b5q_rddm_dump(controller)') < dump.index('sram-assert skipped/expected-zero in RDDM')
    for text in ('B5Q_RDDM_WAIT_MAX_MS 3000u', 'B5Q_RDDM_WAIT_STEP_MS 10u',
                 'B5Q_RDDM_STATUS_XFER_COMPL 2u', 'B5Q_RDDM_STATUS_ERROR 3u',
                 'B5Q_RDDM_TEXT_MAX 160u', 'B5Q_RDDM_HIGH_MAX 12u', 'B5Q_RDDM_LOW_MAX 12u',
                 'B5Q_RDDM_HIT_MAX 24u', 'b5q_rddm_printable(data[at])',
                 'b5q_rddm_memcaselen', 'struct B5qRddmWord'):
        assert text in rddm, text
    emit_at=rddm.index('static inline void b5q_rddm_emit(')
    emit_body=rddm[emit_at:]
    assert emit_body.index('scan->dropped++') < emit_body.index('b5q_rddm_seen(scan, text)')
    assert emit_body.count('b5q_rddm_seen(scan, text)')==1
    checks.append(dict(name='RDDM-source-contracts', passed=True))

    model(t, 'rddm-wait-scan', r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint32_t u32;
struct fake{unsigned reads,dels;u32 values[8];unsigned count;};
static u32 rd(void*c,u32 off){struct fake*f=c;assert(off==0x78);u32 v=f->values[f->reads<f->count?f->reads:f->count-1];f->reads++;return v;}
static void dl(void*c,unsigned ms){struct fake*f=c;assert(ms==10);f->dels++;}
static unsigned hits,high,low;static char seen[32][161];
static void emit(void*c,const struct B5qRddmHit*h){(void)c;assert(h->length<=160);assert(strlen(h->text)<=160);
 if(hits<32)strcpy(seen[hits],h->text);
 hits++;
 if(h->priority==0)high++;else low++;}
static void reset(void){hits=high=low=0;memset(seen,0,sizeof seen);}
int main(){
 struct fake f={0,0,{0u,1u,(2u<<30),(3u<<30)},4};
 struct B5qRddmWait w=b5q_rddm_wait_rxvec(rd,dl,&f,3000,10);
 assert(w.rxvec==(2u<<30)&&w.state==2&&w.waited_ms==20&&w.polls==2&&f.reads==3&&f.dels==2);
 f.reads=0;f.dels=0;f.values[0]=(3u<<30);w=b5q_rddm_wait_rxvec(rd,dl,&f,3000,10);
 assert(w.state==3&&w.waited_ms==0&&w.polls==0);
 f.reads=0;f.values[0]=UINT32_MAX;w=b5q_rddm_wait_rxvec(rd,dl,&f,3000,10);assert(w.state==3&&w.waited_ms==0);
 f.reads=0;f.dels=0;f.count=1;f.values[0]=0;w=b5q_rddm_wait_rxvec(rd,dl,&f,3000,10);
 assert(w.state==0&&w.waited_ms==3000&&w.polls==300&&f.reads==301&&f.dels==300);
 assert(b5q_rddm_is_elf((const uint8_t*)"\x7f" "ELF",4)&&!b5q_rddm_is_elf((const uint8_t*)"\x7f" "ELG",4));
 char clean[8];assert(b5q_rddm_clean_ascii(clean,sizeof clean,(const uint8_t*)"A\x01\xffZ",4)==4&&!strcmp(clean,"A..Z"));
 uint8_t zeros[8]={0};size_t nz=9;assert(b5q_rddm_segment_nonzero(zeros,8,&nz)==0&&nz==0);
 zeros[3]=7;assert(b5q_rddm_segment_nonzero(zeros,8,&nz)==1&&nz==1);
 struct B5qRddmScan scan;struct B5qRddmSegment seg[3];
 const char*a="Asserted in wal_vdev.c:1234 ERR_FATAL";
 const char*b="wmi_mgmt_tx.c:88 err failed";
 seg[0]=(struct B5qRddmSegment){(const uint8_t*)a,(u32)strlen(a)};
 seg[1]=(struct B5qRddmSegment){(const uint8_t*)b,(u32)strlen(b)};
 b5q_rddm_scan_init(&scan,emit,0);reset();b5q_rddm_scan(&scan,seg,2);
 assert(high>=1&&low>=1&&hits>=2);
 for(unsigned i=0;i<hits;i++)assert(strstr(seen[i],"wal_vdev.c:1234")||strstr(seen[i],"wmi_mgmt_tx.c:88"));
 b5q_rddm_scan(&scan,seg,2);assert(hits==high+low);
 const char*dup1="Asserted in crash-dup";const char*dup2="Asserted in crash-dup";
 seg[0]=(struct B5qRddmSegment){(const uint8_t*)dup1,(u32)strlen(dup1)};
 seg[1]=(struct B5qRddmSegment){(const uint8_t*)dup2,(u32)strlen(dup2)};
 reset();b5q_rddm_scan(&scan,seg,2);assert(high==1&&low==0&&hits==1);
 char many[16][64];struct B5qRddmSegment segs[16];
 for(unsigned i=0;i<16;i++){snprintf(many[i],sizeof many[i],"Asserted in crash%02u",i);segs[i]=(struct B5qRddmSegment){(const uint8_t*)many[i],(u32)strlen(many[i])};}
 reset();b5q_rddm_scan(&scan,segs,16);assert(high==7&&hits==7);
 char mix[42][64];struct B5qRddmSegment msegs[42];
 for(unsigned i=0;i<40;i++){snprintf(mix[i],sizeof mix[i],"Asserted in mix%02u",i);msegs[i]=(struct B5qRddmSegment){(const uint8_t*)mix[i],(u32)strlen(mix[i])};}
 snprintf(mix[40],sizeof mix[40],"wal_mix.c:1 err");snprintf(mix[41],sizeof mix[41],"wal_mix.c:1 err");
 msegs[40]=(struct B5qRddmSegment){(const uint8_t*)mix[40],(u32)strlen(mix[40])};
 msegs[41]=(struct B5qRddmSegment){(const uint8_t*)mix[41],(u32)strlen(mix[41])};
 reset();b5q_rddm_scan(&scan,msegs,42);
 assert(high==7&&low==1&&hits==8);
 char lows[16][64];struct B5qRddmSegment lsegs[16];
 for(unsigned i=0;i<16;i++){snprintf(lows[i],sizeof lows[i],"wal_%02u.c:1 err",i);lsegs[i]=(struct B5qRddmSegment){(const uint8_t*)lows[i],(u32)strlen(lows[i])};}
 reset();b5q_rddm_scan(&scan,lsegs,16);assert(low==12&&hits==12);
 char control[]="Asserted in wal\x01vdev.c:1234";seg[0]=(struct B5qRddmSegment){(const uint8_t*)control,(u32)strlen(control)};
 reset();b5q_rddm_scan(&scan,seg,1);assert(high==1&&strstr(seen[0],"wal.vdev.c:1234"));
 char longtext[400];memset(longtext,'A',sizeof longtext);memcpy(longtext,"Asserted in ",12);
 seg[0]=(struct B5qRddmSegment){(const uint8_t*)longtext,sizeof longtext};
 reset();b5q_rddm_scan(&scan,seg,1);assert(high==1&&strlen(seen[0])==160);
 return 0;}
''', includes=[str(P / 'B5qAth11kRddm.h')])

    # Real build-script probes: run the same prepare() used by the target build.
    sys.path.insert(0, str(R / 'UniXNU-b5q/scripts'))
    spec = importlib.util.spec_from_file_location('review13_build_wifi', R / 'UniXNU-b5q/scripts/build-b5q-wifi.py')
    build_wifi = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(build_wifi)
    gen = build_wifi.prepare(R / 'sources/UniXNU-sheng/drivers/Ath12kWifi', t / 'wifi')
    wmi = (gen / 'wmi.c').read_text()
    mac = (gen / 'mac.c').read_text()
    for text in ('B5qWifi: vdev-create id=%u type=%u subtype=%u pdev=%u mac=',
                 'B5qWifi: vdev-set-param vdev=%u param=%u value=%u',
                 'B5qWifi: sta-ps vdev=%u param=%u value=%u',
                 'B5qWifi: sta-psmode vdev=%d psmode=%u',
                 'B5qWifi: wmm-update vdev=%u type=%u BE=%u/%u/%u/%u/%u/%u',
                 'B5qWifi: add-interface type=%u state=%u regd=%02x%02x dfs=%u',
                 'B5qWifi: conf-tx type=%u ac=%u aifs=%u cwmin=%u cwmax=%u txop=%u uapsd=%u state=%u'):
        assert (text in wmi) or (text in mac), text
    assert wmi.index('B5qWifi: vdev-set-param') < wmi.index('WMI_VDEV_SET_PARAM_CMDID')
    assert wmi.index('B5qWifi: wmm-update') < wmi.index('WMI_VDEV_SET_WMM_PARAMS_CMDID')
    assert 'param->ac_be.aifs' in wmi and 'param->ac_bk.cwmin' in wmi and 'param->ac_vi.txop' in wmi and 'param->ac_vo.no_ack' in wmi
    checks.append(dict(name='Wi-Fi-build-probes', passed=True))

    bt = (P / 'B5qBtH4Tap.h').read_text()
    source = (P / 'B5qBluetooth.cpp').read_text()
    native = function(source, 'size_t nativeRx(')
    assert 'qbt_transport_receive(bytes,(uint32_t)n)' in native
    assert 'b5q_bt_h4_tap_rx_taken(&h4Tap,bytes,n,taken)' in native
    assert 'b5q_bt_h4_tap_rx(&h4Tap' not in native
    worker = function(source, 'void worker(')
    assert worker.index('qbt_transmit(bt.core,tx,n)') < worker.index('b5q_bt_h4_tap_tx(&h4Tap,tx,n)')
    assert 'if(active&&bt.log>=2)b5q_bt_h4_tap_reset_streams(&h4Tap)' in worker
    power_on = function(source, 'int powerOn() {')
    power_off = function(source, 'int powerOff() {')
    assert 'b5q_bt_h4_tap_reset_session(&h4Tap)' in power_on
    assert 'b5q_bt_h4_tap_reset_streams(&h4Tap)' in power_off
    for text in ('B5qBluetooth: stage=h4 tx-cmd=%llu tx-acl=%llu rx-evt=%llu rx-acl=%llu errs=%llu smp=%llu l2cap=%llu desync=%llu evt13=%llu logged=%u/%u',
                 'process name=BluetoothUIServer pid=%u change=%u', 'static const char *const names[]={"bluetoothd","BlueTool","BluetoothUIServer"}',
                 'for(unsigned i=0;i<3;i++)', 'if(i<2) {'):
        assert text in source, text
    assert source.index('stage=transport tx=') < source.index('stage=h4 tx-cmd=')
    for text in ('B5Q_BT_H4_QUOTA_TOTAL 800u', 'B5Q_BT_H4_QUOTA_KEY 558u', 'B5Q_BT_H4_QUOTA_NORMAL 240u',
                 'B5Q_BT_H4_ATT_LIMIT 160u', 'B5Q_BT_H4_CID_LIMIT 80u', 'B5Q_BT_H4_PREFIX 64u',
                 'tap->stats.desync++', 'b5q_h4_get8(v, protocol + 6u)'):
        assert text in bt, text
    parser_reset=function(bt, 'static inline void b5q_bt_h4_parser_reset(')
    assert 'p->desync' not in parser_reset and 'memset(p' not in parser_reset
    streams=function(bt, 'static inline void b5q_bt_h4_tap_reset_streams(')
    assert 'stats.desync' not in streams
    smp=bt[bt.index('if (smp_op == 0x05u)'):bt.index('} else if (cid == 0x0001u')]
    assert 'protocol + 5u' in smp and 'protocol + 6u' in smp and '? keydist : 0u' not in smp
    checks.append(dict(name='Bluetooth-source-contracts', passed=True))

    model(t, 'h4-parser-quota', r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
struct out{unsigned lines,desync,att_summary,cid_summary;char last[512],firstdesync[128];};
static void line(void*c,const char*t){struct out*o=c;o->lines++;snprintf(o->last,sizeof o->last,"%s",t);
 if(strstr(t,"att-summary"))o->att_summary++;
 if(strstr(t,"cid-summary"))o->cid_summary++;
 if(strstr(t,"desync=")){o->desync++;if(!o->firstdesync[0])snprintf(o->firstdesync,sizeof o->firstdesync,"%s",t);}}
static uint64_t now(void*c){(void)c;return 123;}
static void send(struct B5qBtH4Tap*t,struct out*o,const uint8_t*p,unsigned n,int tx){
 (void)o;
 for(unsigned i=0;i<n;i+=3){unsigned m=n-i<3?n-i:3;if(tx)b5q_bt_h4_tap_tx(t,p+i,m);else b5q_bt_h4_tap_rx(t,p+i,m);}}
static void acl(uint8_t*out,unsigned cid,unsigned op,unsigned len,unsigned reason){
 memset(out,0,len+9);out[0]=2;unsigned h=0x40;out[1]=h&255;out[2]=(h>>8)|0x20;out[3]=(len+4)&255;out[4]=((len+4)>>8)&255;
 out[5]=4;out[6]=0;out[7]=cid&255;out[8]=(cid>>8)&255;out[9]=op;if(reason)out[10]=reason;}
int main(){
 struct B5qBtH4Sink sink={line,now};struct B5qBtH4Tap tap;struct out o;memset(&o,0,sizeof o);
 b5q_bt_h4_tap_init(&tap,&sink,&o,1);
 uint8_t cmd[]={1,0x03,0x0c,0x00};send(&tap,&o,cmd,sizeof cmd,1);assert(tap.stats.tx_cmd==1&&o.lines==1&&strstr(o.last,"type=CMD op=0x0c03"));
 uint8_t smp[32];acl(smp,6,5,7,3);send(&tap,&o,smp,16,0);assert(tap.stats.smp==1&&strstr(o.last,"pairing-failed reason=0x03"));
 acl(smp,6,1,7,0);smp[10]=3;smp[11]=1;smp[12]=1;smp[13]=16;smp[14]=5;smp[15]=0x0a;send(&tap,&o,smp,16,0);
 assert(strstr(o.last,"io=0x03")&&strstr(o.last,"maxkey=16")&&strstr(o.last,"init=0x05")&&strstr(o.last,"resp=0x0a"));
 acl(smp,6,2,7,0);smp[10]=3;smp[11]=1;smp[12]=1;smp[13]=16;smp[14]=0x0b;smp[15]=0x0c;send(&tap,&o,smp,16,0);
 assert(strstr(o.last,"init=0x0b")&&strstr(o.last,"resp=0x0c"));
 uint8_t sig[]={2,0x40,0,0x08,0,4,0,1,0,0x03,0x02,0x01,0x00};send(&tap,&o,sig,sizeof sig,0);
 assert(strstr(o.last,"sig-code=0x03")&&strstr(o.last,"sig-id=2"));
 uint8_t att[]={2,0x40,0,0x09,0,4,0,4,0,1,0x0b,0x01,0x00,0x05};send(&tap,&o,att,sizeof att,0);
 assert(strstr(o.last,"att-op=0x01")&&strstr(o.last,"att-error=0x05")&&tap.stats.errs>=1);
 uint8_t scan[]={1,0x01,0x04,0x00};send(&tap,&o,scan,sizeof scan,1);assert(tap.stats.filtered==1);
 uint8_t evt[16];evt[0]=4;evt[1]=0x0e;evt[2]=4;evt[3]=1;evt[4]=0x01;evt[5]=0x04;evt[6]=0;send(&tap,&o,evt,7,0);
 assert(tap.stats.filtered==2);evt[6]=9;send(&tap,&o,evt,7,0);assert(strstr(o.last,"status=0x09"));
 uint8_t bad[]={0xff,4,0x05,0x04,0x00,0x01,0x00,0x13};send(&tap,&o,bad,sizeof bad,0);
 assert(tap.stats.desync==1&&strstr(o.firstdesync,"desync=0xff")&&strstr(o.last,"evt=0x05"));
 uint8_t big[1200];memset(big,0,sizeof big);big[0]=2;big[1]=0x40;big[2]=0;big[3]=0xab;big[4]=0x04;
 send(&tap,&o,big,sizeof big,0);send(&tap,&o,cmd,sizeof cmd,1);assert(tap.stats.rx_acl==6&&tap.stats.tx_cmd==3);
 assert(tap.stats.desync==1&&o.desync==1);
 for(unsigned n=0;n<10;n++)send(&tap,&o,bad,sizeof bad,0);
 assert(tap.stats.desync==11&&o.desync==8);
 uint8_t part[]={1,0x03,0x0c,0x00};b5q_bt_h4_tap_rx_taken(&tap,part,sizeof part,2);b5q_bt_h4_tap_rx_taken(&tap,part+2,2,2);
 assert(tap.stats.tx_cmd==3);b5q_bt_h4_tap_rx_taken(&tap,part,sizeof part,99);assert(tap.stats.desync==11);
 unsigned sessionDesync=tap.stats.desync;b5q_bt_h4_tap_reset_streams(&tap);assert(tap.stats.desync==sessionDesync);
 b5q_bt_h4_tap_reset_session(&tap);assert(tap.stats.desync==0&&tap.tx.desync==0&&tap.rx.desync==0);
 struct B5qBtH4Tap quota;struct out q;memset(&q,0,sizeof q);b5q_bt_h4_tap_init(&quota,&sink,&q,1);
 uint8_t attok[16];acl(attok,4,0x0a,5,0);for(unsigned i=0;i<200;i++)send(&quota,&q,attok,14,0);
 assert(quota.stats.att==200&&quota.quota.att==160&&quota.stats.att_dropped==40&&q.att_summary==1);
 uint8_t dyn[16];acl(dyn,0x40,0,2,0);for(unsigned i=0;i<100;i++)send(&quota,&q,dyn,11,0);
 assert(quota.quota.cid==80&&quota.stats.cid_dropped==20&&q.cid_summary==1);
 for(unsigned i=0;i<800;i++)send(&quota,&q,smp,16,0);
 assert(quota.quota.total==800&&quota.stats.logged==800&&quota.quota.key<=558);
 unsigned before=q.lines;send(&quota,&q,smp,16,0);assert(quota.quota.total==800&&q.lines==before);
 return 0;}
''', includes=[str(P / 'B5qBtH4Tap.h')])

receipt = dict(passed=True, hardware_verified=False, checks=checks,
               sanitizer='address,undefined', host_verified_pending_hardware=True,
               ci_triggered=False, push_performed=False, esp_created=False, phone_accessed=False)
(W / 'review13-tests.json').write_text(json.dumps(receipt, indent=2) + '\n')
print('PASS review13 PD VBUS-only swap, UsbForcePower port contracts, real RDDM wait/scanner, build probes and streaming H4 tap')
