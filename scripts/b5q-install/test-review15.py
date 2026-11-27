#!/usr/bin/env python3
"""Review15 real source tests: WCN bands, connected USB ports/IR1 and DP PD headers."""
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
parser.add_argument('--out', type=Path, default=Path(os.environ.get('B5Q_GATE_WORK', R / 'artifacts/b5q-review15-local')))
W = parser.parse_args().out.resolve()
W.mkdir(parents=True, exist_ok=True)
checks = []


def function(text, signature):
    start = text.index(signature)
    brace = text.index('{', start)
    depth, end = 1, brace + 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[start:end]


def run(name, command):
    result = subprocess.run(list(map(str, command)), cwd=R, capture_output=True, text=True)
    text = result.stdout + result.stderr
    (W / (name + '.log')).write_text(text)
    if result.returncode:
        raise RuntimeError(name + ':\n' + text)
    checks.append(dict(name=name, passed=True, log_sha256=hashlib.sha256(text.encode()).hexdigest()))
    print('PASS', name, flush=True)
    return result.stdout


def model(temp, name, source):
    path = temp / (name + '.cpp')
    path.write_text(source)
    binary = temp / name
    run(name + '-compile', ['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
        '-Wno-misleading-indentation', '-Wno-sign-compare', '-O1', '-g',
        '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
        '-I' + str(P), path, '-o', binary])
    return run(name + '-ASan-UBSan', [binary])


sys.path.insert(0, str(R / 'UniXNU-b5q/scripts'))
spec = importlib.util.spec_from_file_location('review15_wifi', R / 'UniXNU-b5q/scripts/build-b5q-wifi.py')
wifi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wifi)
with tempfile.TemporaryDirectory(prefix='review15-', dir=W) as td:
    temp = Path(td)
    gen = wifi.prepare(R / 'sources/UniXNU-sheng/drivers/Ath12kWifi', temp / 'wifi')
    hw, wmi = (gen / 'hw.c').read_text(), (gen / 'wmi.c').read_text()
    qca = function(hw, 'static void ath11k_init_wmi_config_qca6390(')
    expected = 'config->twt_ap_pdev_count = ab->hw_params.max_radios ? ab->hw_params.max_radios : 3;'
    assert expected in qca and 'config->twt_ap_sta_count = 8;' in qca
    assert 'B5qWifi: wmi-init radios=%u max_radios=%u' in wmi
    assert 'ab->num_radios, ab->hw_params.max_radios, config.num_vdevs, config.num_peers' in wmi
    assert json.loads((temp / 'wifi/source-inputs.json').read_text())['wcn6855_twt_ap_config'] == 'twt_ap_pdev_count=max_radios(fallback 3) twt_ap_sta_count=8'
    pinned = R / 'sources/UniXNU-sheng/drivers/Ath12kWifi/deps/linux/drivers/net/wireless/ath/ath11k'
    assert function(hw, 'static void ath11k_init_wmi_config_ipq8074(') == function((pinned / 'hw.c').read_text(), 'static void ath11k_init_wmi_config_ipq8074(')
    core = (pinned / 'core.c').read_text().split('.hw_rev = ATH11K_HW_WCN6855_HW21,', 1)[1].split('\n\t},', 1)[0]
    assert '.max_radios = 3,' in core and '.single_pdev_only = true,' in core
    assignment = qca[qca.index('config->twt_ap_pdev_count'):qca.index('config->twt_ap_sta_count')]
    model(temp, 'wifi-all-bands', r'''
#include <cassert>
#include <initializer_list>
struct Base{unsigned num_radios;struct{unsigned max_radios;}hw_params;};
struct Config{unsigned twt_ap_pdev_count;};
void configure(Base *ab,Config *config){ASSIGNMENT}
int main(){for(unsigned maximum:{0u,1u,2u,3u}){Base ab{1,{maximum}};Config c{};configure(&ab,&c);
 assert(c.twt_ap_pdev_count==(maximum?maximum:3u));
 if(maximum==3||maximum==0)for(unsigned mac_id=0;mac_id<3;mac_id++)assert(mac_id<c.twt_ap_pdev_count);}}
'''.replace('ASSIGNMENT', assignment))

    model(temp, 'usb-hold-ir1-td-context', r'''
#include <cassert>
#include <cstdint>
#include <map>
#include <vector>
#include "B5qUsbHostRole.h"
#include "B5qUsbHostEvent.h"
using namespace B5qUsbHostEvent;
int main(){
 using B5qUsbHostRole::portConnectedForHold;using B5qUsbHostRole::fastPortPollNeeded;
 for(unsigned a:{0u,1u})for(unsigned b:{0u,1u}){
  assert(portConnectedForHold("AppleUSB20XHCIPort",a,b)==bool(a));
  assert(portConnectedForHold("AppleUSB20XHCITypeCPort",a,b)==bool(a));
  assert(portConnectedForHold("AppleUSB30XHCIPort",a,b)==bool(b));
  assert(portConnectedForHold("AppleUSB30XHCITypeCPort",a,b)==bool(b));
  assert(!portConnectedForHold("unknown",a,b));
 }
 assert(!portConnectedForHold(nullptr,1,1));assert(!portConnectedForHold("AppleUSB2",1,1));
 assert(fastPortPollNeeded(0,1)&&!fastPortPollNeeded(1,1));
 assert(fastPortPollNeeded(1,2)&&!fastPortPollNeeded(2,2));
 assert(!fastPortPollNeeded(0,0)&&!fastPortPollNeeded(8,0));
 std::map<unsigned,uint32_t> regs;unsigned reads=0;
 for(unsigned ir=0;ir<2;ir++){unsigned p=0x1020+ir*0x20;regs[p]=0x10+ir;regs[p+8]=1;
  regs[p+16]=0x2000+ir*0x1000;regs[p+20]=8;regs[p+24]=0x4000+ir*0x1000;regs[p+28]=8;}
 auto mmio=[&](unsigned off){assert(off<0x8000);reads++;return regs.at(off);};
 Interrupter ir0{},ir1{};assert(interrupter(0x1000,0,0x8000,mmio,ir0));
 assert(interrupter(0x1000,1,0x8000,mmio,ir1));
 assert(ir0.iman==0x10&&ir1.iman==0x11&&ir1.erst==0x800003000ULL&&ir1.erdp==0x800005000ULL);
 unsigned oldReads=reads;assert(!interrupter(0xffffffe0,1,0x8000,mmio,ir1));
 assert(!interrupter(0x7fc0,1,0x8000,mmio,ir1));assert(!interrupter(0,2,0x8000,mmio,ir1));assert(reads==oldReads);
 std::map<uint64_t,uint64_t> ram;
 auto read=[&](uint64_t pa,uint64_t &v){auto at=ram.find(pa);if(at==ram.end())return false;v=at->second;return true;};
 // IR0 and IR1 have independent event tables; the IR1 error points into a TD.
 for(unsigned ir=0;ir<2;ir++){
  uint64_t table=0x10000+ir*0x1000,ring=0x20000+ir*0x1000;
  ram[table]=ring;ram[table+8]=16;
  for(unsigned n=0;n<16;n++){ram[ring+16*n]=0;ram[ring+16*n+8]=0;}
  ram[ring]=ir?0x30030:0x3020;
  ram[ring+8]=uint64_t((1u<<24)|(1u<<16)|(32u<<10)|1u)<<32|uint64_t(ir?27u:1u)<<24;
 }
 TransferBases bases;unsigned events=0,errors=0;
 for(unsigned ir=0;ir<2;ir++)assert(latest(0x10000+ir*0x1000,1,0x20010+ir*0x1000,16,read,
  [&](unsigned segment,unsigned index,const Event &e){assert(segment==0&&index<16);events++;
   if(e.type==32&&e.completion==27){errors++;assert(e.parameter==0x30030&&e.slot==1&&e.endpoint==1&&e.cycle==1);}bases.observe(e);}));
 assert(events==32&&errors==1&&bases.count==1&&bases.values[0]==0x30000);
 Event e{0x30050,0,0,13,32,1,1,1};bases.observe(e);assert(bases.count==1);
 e.parameter=0x40020;bases.observe(e);e.parameter=0x50020;bases.observe(e);assert(bases.count==2);
 for(unsigned n=0;n<6;n++){ram[0x30000+16*n]=0x100+n;ram[0x30008+16*n]=uint64_t((n+1)<<10)<<32|n;}
 unsigned trbs=0;assert(transfer(0x30000,read,[&](unsigned i,uint64_t lo,uint64_t hi){assert(i==trbs++&&lo==0x100+i&&((hi>>42)&63)==i+1);}));assert(trbs==6);
 trbs=0;assert(!transfer(0x50000,read,[&](unsigned,uint64_t,uint64_t){trbs++;}));assert(!trbs);
 assert(!transfer(UINT64_MAX&~255ULL,read,[&](unsigned,uint64_t,uint64_t){assert(false);}));
 for(unsigned stride:{32u,64u}){
  ram[0x60008]=0x70000;ram[0x70000]=0x1122334455667788;ram[0x70008]=9;
  ram[0x70000+stride]=10;ram[0x70008+stride]=11;Slot1 c{};
  assert(slot1(0x60000,stride,read,c)&&c.address==0x70000&&c.slot[0]==0x1122334455667788&&c.ep0[1]==11);
 }
 Slot1 denied{};assert(!slot1(0x80000,32,read,denied));assert(!slot1(0x60000,16,read,denied));
 assert(!latest(0x90000,1,0x20000,16,read,[](unsigned,unsigned,const Event&){assert(false);}));
}
''')

    model(temp, 'dp-real-pd-headers', r'''
#include <cassert>
#include <array>
#include <cstring>
#include "B5qDpPdic.h"
using namespace B5qDp;
struct M{PdError error=PdError::None;bool enable(bool){return true;}bool request(unsigned,unsigned=0,uint32_t=0,bool=false){return true;}};
std::array<uint8_t,33> packet(unsigned id,uint32_t vdo=0,unsigned objects=2){
 std::array<uint8_t,33> b{};b[0]=0x4b;b[1]=id;b[2]=0x8f;b[3]=uint8_t((objects<<4)|8);
 put32(b.data()+4,(uint32_t(id<=2?0xff00:0xff01)<<16)|0x8000|(id==6?0:64)|id|((id==4||id==0x11)?256:0));
 put32(b.data()+8,vdo);return b;
}
int main(){
 M m;for(auto hi:{uint8_t(0x18),uint8_t(0x1f)}){
  AltMode s;s.phase=AltMode::Phase::Enter;const uint8_t real[]={0x4b,4,0x8f,hi,0x44,0xa9,1,0xff};
  assert(s.event(m,4,real,8)&&s.phase==AltMode::Phase::Status);
 }
 AltMode s;assert(s.start(m));
 for(auto id:{1u,2u,3u,4u,0x10u,0x11u,6u}){
  unsigned objects=(id==4||id==0x11)?1:2;
  uint32_t data=id==2?0xff01u:id==3?5u|64u|(28u<<16):2u|128u|16u;
  auto b=packet(id,data,objects);assert(s.event(m,id,b.data(),(objects+1)*4));
  if(id==4)assert(s.phase==AltMode::Phase::Status);
  if(id==0x11||id==6)assert(s.phase==AltMode::Phase::Active&&s.hpd&&s.pin==8);
 }
 for(unsigned failure=0;failure<5;failure++){
  AltMode bad;bad.phase=AltMode::Phase::Enter;auto b=packet(4,0,1);size_t bytes=8;
  if(failure==0)b[3]=8;
  if(failure==1)bytes=7;
  if(failure==2)b[3]=0x28;
  if(failure==3)b[2]=0x8e;
  if(failure==4)b[0]=0x4a;
  assert(!bad.event(m,4,b.data(),bytes)&&bad.error==PdError::Packet);
 }
}
''')

    # Execute the actual Session against the existing causal AUX/PLL model.
    tree = ast.parse((R / 'tests/b5q-ufs/test-dp-session.py').read_text())
    original = next(n.value.value for n in tree.body if isinstance(n, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == 'h' for t in n.targets))
    prefix = original.split('int main(){', 1)[0]
    model(temp, 'dp-discovery-cache', prefix + r'''
int main(){
 {Io io;Session<Io> s(io);assert(s.discover(4,false)&&s.discoverStep==6&&s.dpcd[0]==0x14&&s.dpcd[1]==20&&s.edidBytes==256);assert(s.stop());}
 {Io io;io.online=false;Session<Io>s(io);assert(!s.discover(4,false)&&s.discoverStep==0);}
 {Io io;io.clockFault=true;Session<Io>s(io);assert(!s.discover(4,false)&&s.discoverStep==1);}
 {Io io;io.nackAt=1;Session<Io>s(io);assert(!s.discover(4,false)&&s.discoverStep==2);}
 {Io io;io.corruptEdid=true;Session<Io>s(io);assert(!s.discover(4,false)&&s.discoverStep==4);}
}
''')
    # Prove that diagnostic caches do not change the physical programming trace.
    prefix = prefix.replace('#include <map>', '#include <map>\n#include <tuple>')
    prefix = prefix.replace('std::map<std::pair<Block,unsigned>,uint32_t> regs;',
                            'std::vector<std::tuple<unsigned,unsigned,uint32_t>> trace;\n std::map<std::pair<Block,unsigned>,uint32_t> regs;')
    prefix = prefix.replace('void write(Block b,unsigned off,uint32_t value){',
                            'void write(Block b,unsigned off,uint32_t value){trace.emplace_back(unsigned(b),off,value);')
    trace_main = r'''
int main(){for(unsigned fault=0;fault<5;fault++){
 Io io;if(fault==1)io.clockFault=true;if(fault==2)io.nackAt=1;if(fault==3)io.corruptEdid=true;if(fault==4)io.pllFault=true;
 Session<Io>s(io);bool ok=s.discover(4,false);if(ok)ok=s.train();if(ok)ok=s.video();s.stop();
 printf("case=%u ok=%u error=%u us=%llu\n",fault,ok,unsigned(s.error),(unsigned long long)io.now);
 for(auto row:io.trace)printf("%u %x %x\n",std::get<0>(row),std::get<1>(row),std::get<2>(row));
}}
'''
    baseline = temp / 'baseline-session.h'
    baseline.write_bytes(subprocess.check_output(['git', 'show', 'HEAD:UniXNU-b5q/package/B5qDpSession.h'], cwd=R))
    before = model(temp, 'dp-session-before', prefix.replace('#include "B5qDpSession.h"', '#include "' + str(baseline) + '"') + trace_main)
    after = model(temp, 'dp-session-after', prefix + trace_main)
    assert before == after, 'Diagnostic caches changed DP hardware programming'
    checks.append(dict(name='dp-identical-physical-programming-traces', passed=True,
                       trace_sha256=hashlib.sha256(after.encode()).hexdigest()))

usb = (P / 'QcomDwc3.cpp').read_text()
stats = function(usb, 'void hostStats() {')
assert 'if (!gDmaReady || !gHost || gCoreRole != kRoleHost) return;' in stats
assert 'kUsbHostDebugOptions=0u' in usb and 'kUsbPortDebugOptions=0u' in usb and 'usb-debug' in usb and '0x4000015du' in usb and '0x40000119u' in usb
configure = function(usb, 'void configureHostPorts(IOService *host) {')
assert configure.index('portConnectedForHold') < configure.index('ensureHostPortHold(port)')
assert 'host->setProperties(hostSettings)' in configure and 'port->setProperties(settings)' in configure
diagnostic = function(usb, 'void dmaDiagnostics(const char *reason){')
for marker in ['irIndex<2', 'host-event reason=%s ir=%u', 'host-td', 'host-slot1', 'HCSPARAMS1=', 'dmaRead64']:
    assert marker in diagnostic, marker
for forbidden in ['IOMalloc', 'withRange', 'mapRegion', 'ml_phys_write', 'gXhciRegs.va[off/4]=']:
    assert forbidden not in diagnostic
assert 'removePowerChild' not in usb
assert 'gFirstCc27Seen=false' in usb and 'dmaDiagnostics("first-cc27")' in stats
release = function(usb, 'void releaseHostPortPowerHolds() {')
base_usb = subprocess.check_output(['git', 'show', 'HEAD:UniXNU-b5q/package/QcomDwc3.cpp'], cwd=R).decode()
assert release == function(base_usb, 'void releaseHostPortPowerHolds() {')
board = (P / 'B5qUsbBoard.cpp').read_text()
for marker in ['pdic-defer', 'pdic-start', 'pdic-irq', 'pdic-raw id=%02x', 'pdic-raw2', 'pdic-timeout']:
    assert marker in board
link = (P / 'B5qDpLink.cpp').read_text()
for marker in ['stage=pool-ready', 'stage=hw-open', 'B5qDP: discover', 'train_err=', 'phy_last=', 'stage=scanout', 'B5qDP: feature b5q-dp=', 'B5qDP: port phase=']:
    assert marker in link
for name in ['B5qDpPhy.h', 'B5qDpClock.h', 'B5qDpDpu.h', 'B5qDpDisplay.cpp', 'B5qWcnPower.cpp',
             'B5qBtFifo.c']:
    assert (P / name).read_bytes() == subprocess.check_output(['git', 'show', 'HEAD:UniXNU-b5q/package/' + name], cwd=R), name
# Review17's H4 diagnostics are allowed; preserve its actual UART/IBS executor.
old_bt = subprocess.check_output(['git', 'show', 'HEAD:UniXNU-b5q/package/B5qBluetooth.cpp'], cwd=R).decode()
for signature in ['int clockVote(', 'void rxIrq(', 'void disarmRxWake(', 'void worker(', 'int setRate(']:
    assert function(old_bt, signature) == function((P / 'B5qBluetooth.cpp').read_text(), signature)
assert len(list((R / 'tests/b5q-ufs').glob('test-dp-*.py'))) == 26
checks.append(dict(name='diagnostics-and-red-line-source-contracts', passed=True))
receipt = dict(status='HOST_VERIFIED_PENDING_HARDWARE', passed=True, hardware_verified=False,
               checks=checks, sanitizer='address,undefined', commit_performed=False, push_performed=False,
               CI_triggered=False, ESP_created=False, phone_accessed=False)
(W / 'review15-tests.json').write_text(json.dumps(receipt, indent=2) + '\n')
print('PASS review15 Wi-Fi full-band TWT, connected USB holds/IR1/TD/context, real PD headers and DP diagnostics')
