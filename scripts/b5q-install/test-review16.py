#!/usr/bin/env python3
"""Review16 local source and model tests: Wi-Fi MAC/probes, USB IR bridge, DP AuxPins/link probes."""
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
parser.add_argument('--out', type=Path, default=Path(os.environ.get('B5Q_GATE_WORK', R / 'artifacts/b5q-review16-local')))
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
    return text


def model(temp, name, source):
    path = temp / (name + '.cpp')
    path.write_text(source)
    binary = temp / name
    run(name + '-compile', ['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
        '-Wno-misleading-indentation', '-Wno-sign-compare', '-O1', '-g',
        '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
        '-I' + str(P), path, '-o', binary])
    return run(name + '-ASan-UBSan', [binary])


# 1. Wi-Fi: the board MAC must reach ath11k instead of the ath11k random address.
compat = (P / 'B5qAth11kCompat/B5qAth11kCompat.h').read_text()
mac_fn = function(compat, 'static inline int device_get_mac_address')
assert 'void nw_board_mac(u8 *a);' in compat
assert 'extern "C"' in compat
assert 'nw_board_mac(address)' in mac_fn and 'return 0;' in mac_fn
assert 'memset(address, 0, 6)' not in mac_fn and '-ENODEV' not in mac_fn
ath = (P / 'B5qAth11k.c').read_text()
assert 'void nw_board_mac(u8 *a) {' in ath
assert 'wlan_mac.bin' in function(ath, 'void nw_board_mac(u8 *a)')
checks.append(dict(name='wifi-board-mac-symbol-and-fallback', passed=True))

sys.path.insert(0, str(R / 'UniXNU-b5q/scripts'))
spec = importlib.util.spec_from_file_location('review16_wifi', R / 'UniXNU-b5q/scripts/b5q_wifi.py')
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)
with tempfile.TemporaryDirectory(prefix='review16-wifi-', dir=W) as td:
    selected = generator.prepare(R / 'sources/UniXNU-sheng', Path(td) / 'wifi')
    text = selected.read_text()
    audit = json.loads((Path(td) / 'wifi/network-source.json').read_text())
    for marker in ['log_ifnet_bind', 'ifnet_lladdr_copy_bytes', 'probe_frame', '__atomic_load_n(&gFrameProbeLogged, __ATOMIC_RELAXED) >= 64',
                   '__atomic_load_n(seen, __ATOMIC_RELAXED) >= 24', 'extern "C" uint32_t ifnet_eflags(ifnet_t);', 'wifi-net: ifnet-bind where=%s if=%s%u flags=0x%x eflags=0x%x cap=0x%x',
                   'wifi-net: frame dir=%s len=%zu dst=', 'wifi-net: rx-flush batch=%u bytes=%u rc=%d',
                   'if_in=%llu if_ierr=%llu if_iqdrop=%llu', 'if=%s%u flags=%x eflags=%x cap=%x in=%llu ierr=%llu iqdrop=%llu offered=%u']:
        assert marker in text, marker
    assert text.count('probe_frame(e, n, out)') == 1
    for where in ['start', 'tx', 'traffic', 'rx', 'attach']:
        assert text.count('log_ifnet_bind("%s")' % where) == 1, where
    assert '__atomic_exchange_n(&gIfBindLogged, 1u, __ATOMIC_ACQ_REL)' in text
    assert '__atomic_fetch_add(&gFrameProbeLogged' in text
    assert '__atomic_fetch_add(seen' in text
    assert '&gFrameProbeRx' in text and '&gFrameProbeTx' in text
    assert 'boot_cpu_kick' not in text and 'boot_kthread_report' not in text
    assert 'Review16' in audit['adaptation'] and audit['reference_revision'] == generator.REVISION
    assert hashlib.sha256(selected.read_bytes()).hexdigest() == audit['selected_sha256']
checks.append(dict(name='wifi-generated-bounded-probes-and-mac-path', passed=True))

# 2. USB: secondary delivery owns no storm accounting and the bridge has a bounded backoff.
usb = (P / 'QcomDwc3.cpp').read_text()
deliver = function(usb, 'B5qUsbIrq::Delivery deliverSource(uint32_t source)')
for marker in ['gActiveNub!=this', '!slot.enabled', '!slot.action', 'slot.inFlight', 'NotRegistered',
               'BadSource', 'BusyInFlight', 'NotEnabled']:
    assert marker in deliver, marker
assert 'gIrqWindow.observe' not in deliver
assert 'armcpu_spi_mask' not in deliver and 'unmaskLocked' not in deliver
for marker in ['const bool active1 = have1 && (ir1.iman & 3u) == 3u;',
               'const bool active2 = have2 && (ir2.iman & 3u) == 3u;',
               'if (active1) ++gHostIrqBridge.ir1;', 'if (active2) ++gHostIrqBridge.ir2;',
               'const unsigned op = gXhciRegs.va[0] & 0xffu;',
               'gXhciRegs.va[(op + 4u) / 4u]']:
    assert marker in usb, marker
assert 'const bool active=((ir1.iman&3u)==3u)||((ir2.iman&3u)==3u);' not in usb
primary = function(usb, 'static void primary(void *)')
assert 'self->slots[0].inFlight==0' in primary
enter = function(usb, 'void enterHost()')
leave = function(usb, 'void leaveRole(int role)')
assert 'startHostIrqBridge()' in enter
assert leave.index('stopHostIrqBridge()') < leave.index('gHostNub->terminate')
assert 'host-ir-bridge #%u ir1_iman=%x ir2_iman=%x er1=%llx er2=%llx sts=%x d1=%u d2=%u result=%u/%u' in usb
assert 'ir0=%x/%llx ir1=%x/%llx ir2=%x/%llx' in usb
assert 'secKicks=%u secIr1=%u secIr2=%u secNoFilter=%u secBusy=%u secDisabled=%u secBackoff=%u' in usb
assert 'host-device-tree id=%llx vid=%04x pid=%04x' in usb and 'IOUSBHostInterface' not in usb
abi = json.loads((R / 'UniXNU-b5q/scripts/usb-xhci-26C5035r.json').read_text())
assert len(abi['slots']) == 427
checks.append(dict(name='usb-secondary-delivery-bridge-enumeration-427-abi', passed=True, xhci_slots=len(abi['slots'])))

with tempfile.TemporaryDirectory(prefix='review16-usb-', dir=W) as td:
    model(Path(td), 'usb-ir-bridge', r'''
#include <cassert>
#include <cstdint>
#include <map>
#include "B5qUsbIrq.h"
using namespace B5qUsbIrq;
int main(){
 std::map<unsigned,uint32_t> r;unsigned reads=0;
 for(unsigned i=0;i<3;i++){unsigned base=0x1000+0x20+i*0x20;r[base]=0x10+i;r[base+0x18]=0x2000+i*0x1000;r[base+0x1c]=8;}
 auto mmio=[&](unsigned off){assert(off<0x8000);reads++;return r.at(off);};
 Snapshot a{},b{},c{};assert(snapshot(0x1000,0,0x8000,mmio,a)&&a.iman==0x10&&a.erdp==0x800002000ULL);
 assert(snapshot(0x1000,1,0x8000,mmio,b)&&b.iman==0x11&&b.erdp==0x800003000ULL);
 assert(snapshot(0x1000,2,0x8000,mmio,c)&&c.iman==0x12&&c.erdp==0x800004000ULL);
 unsigned old=reads;assert(!snapshot(0x1000,3,0x8000,mmio,a));assert(!snapshot(0x1001,2,0x8000,mmio,a));
 assert(!snapshot(0x1000,2,0x1070,mmio,a));assert(reads==old);
 Bridge s;uint64_t e1=0x1000,e2=0x2000;
 for(unsigned i=0;i<1500;i++)assert(!s.note(true,e1+i*16u,false,e2+i*8u,Delivery::Delivered));
 assert(!s.throttled&&s.intervalMs()==1&&s.misses==0&&s.kicks==1500);
 for(unsigned i=0;i<999;i++)assert(!s.note(true,e1+1499u*16u,false,e2+1499u*8u,Delivery::Delivered));
 assert(!s.throttled&&s.misses==999);
 assert(s.note(true,e1+1499u*16u,false,e2+1499u*8u,Delivery::Delivered));
 assert(s.throttled&&s.intervalMs()==50&&s.backoff==1&&s.misses==1000&&s.kicks==2500);
 assert(!s.note(true,e1+1499u*16u,false,e2+1499u*8u,Delivery::Delivered)&&s.backoff==1);
 assert(!s.note(true,e1+1501u*16u,false,e2+1500u*8u,Delivery::Delivered));
 assert(!s.throttled&&s.intervalMs()==1&&s.misses==0);
 s.idle();assert(!s.throttled&&s.intervalMs()==1&&s.misses==0&&!s.haveLast);
 const uint32_t before=s.kicks;
 s.note(true,0x9000,true,0xa000,Delivery::FilterRejected);assert(s.noFilter==1&&s.kicks==before);
 s.note(true,0x9000,true,0xa000,Delivery::BusyInFlight);assert(s.busy==1&&s.kicks==before);
 s.note(true,0x9000,true,0xa000,Delivery::NotEnabled);assert(s.disabled==1&&s.kicks==before);
 assert(s.note(false,0,false,0,Delivery::Delivered)==false&&s.misses==0&&s.kicks==before);
}
''')
checks.append(dict(name='usb-ir1-ir2-snapshot-and-backoff-model', passed=True))

# 3. DP: CFG/OUT latch success is separate from GPIO180's diagnostic IN sense.
board = (P / 'B5qDpBoard.h').read_text()
assert 'uint8_t inMismatch' in board and 'return cfg&&out;' in board
assert 'return (io.gpioRead(pin,0)&0x3ffu)==0x200u&&bool(io.gpioRead(pin,4)&1)==high' not in board
with tempfile.TemporaryDirectory(prefix='review16-dp-', dir=W) as td:
    model(Path(td), 'dp-aux-latch', r'''
#include <cassert>
#include <cstdint>
#include <initializer_list>
#include "B5qDpBoard.h"
using namespace B5qDp;
struct Io {
 uint32_t cfg[2]{},out[2]{};bool forceIn=false,failEnable=false;unsigned elapsed=0;
 unsigned i(unsigned pin){assert(pin==180||pin==183);return pin==183;}
 uint32_t gpioRead(unsigned pin,unsigned off){unsigned n=i(pin);assert(off==0||off==4);
  if(!off)return cfg[n];
  uint32_t v=out[n]&~1u;v|=(forceIn||!(cfg[n]&0x200))?1u:((out[n]>>1)&1u);return v;}
 void gpioWrite(unsigned pin,unsigned off,uint32_t value){unsigned n=i(pin);assert(off==0||off==4);
  if(off)out[n]=value&~1u;else if(failEnable&&pin==183){failEnable=false;return;}else cfg[n]=value;}
 void delay(unsigned us){elapsed+=us;}
};
int main(){
 for(bool reverse:{false,true}){
  Io io;io.cfg[0]=0xaaaa;io.cfg[1]=0xbbbb;io.out[0]=0x10;io.out[1]=0x20;const auto before=io;
  AuxPins p;assert(p.begin(io,reverse)&&p.owned&&p.inMismatch==0&&io.elapsed==200);
  assert((io.cfg[0]&0x3ff)==0x200&&(io.cfg[1]&0x3ff)==0x200);
  assert(bool(io.gpioRead(180,4)&1)==reverse&&!bool(io.gpioRead(183,4)&1));
  assert(p.end(io)&&!p.owned&&io.cfg[0]==before.cfg[0]&&io.out[1]==before.out[1]);
 }
 {Io io;io.forceIn=true;AuxPins p;assert(p.begin(io,false)&&p.owned);assert(p.inMismatch==3);assert(p.end(io));}
 {Io io;io.forceIn=true;AuxPins p;assert(p.begin(io,true)&&p.owned);assert(p.inMismatch==2);assert(p.end(io));}
 {Io io;io.cfg[0]=0x12345600;io.cfg[1]=0xabcdef00;io.out[0]=0x11111110;io.out[1]=0x22222220;
  const auto before=io;io.failEnable=true;AuxPins p;assert(!p.begin(io,false)&&!p.owned);
  assert(io.cfg[0]==before.cfg[0]&&io.cfg[1]==before.cfg[1]&&io.out[0]==before.out[0]&&io.out[1]==before.out[1]);}
}
''')
checks.append(dict(name='dp-auxpins-latch-in-mismatch-rollback', passed=True))

link = (P / 'B5qDpLink.cpp').read_text()
session = (P / 'B5qDpSession.h').read_text()
for marker in ['stage=hw-open ok rev=%u sel=%08x/%08x en=%08x/%08x in_mismatch=%x',
               'aux-dump ahb0=%08x', 'edid0-15=', 'fit-mode[%u]', 'train-detail last_rate=%u',
               'dpcd202=%02x %02x %02x %02x %02x %02x', 'dpu-resources ctl=%u',
               'scanout-detail video_stage=%u', 'iomfb-create ok=%u', 'present #%llu ok=%u blank=%u stride=%llu tag=%llu']:
    assert marker in link, marker
for marker in ['lastRate', 'lastLanes', 'clockLast', 'trainStatus[6]', 'videoStage',
               'auxFailRegs[10]', 'haveAuxFailRegs', 'captureAuxFailure']:
    assert marker in session, marker
fail_body = function(session, 'bool fail(LinkError why)')
assert fail_body.index('clockLast=clock.last') < fail_body.index('stop()')
assert fail_body.index('captureAuxFailure') < fail_body.index('stop()')
discover_body = function(session, 'bool discover(unsigned routeLanes,bool flipped)')
assert discover_body.index('haveAuxFailRegs=false') < discover_body.index('stop()')
assert 'session.haveAuxFailRegs?f[0]:io.read(Block::Ahb,0x00)' in link
assert link.count('session.clockLast') >= 2
assert 'session.clock.last' not in function(link, 'bool startDisplay()') and 'session.clock.last' not in link
assert len(list((R / 'tests/b5q-ufs').glob('test-dp-*.py'))) == 26
run('dp-discover-failure-snapshot', [sys.executable, R / 'tests/b5q-ufs/test-dp-session.py'])
checks.append(dict(name='dp-link-diagnostics-aux-edid-training-scanout', passed=True))

# 4. Red lines and untouched Review15 Bluetooth/USB contracts.
def changed(path):
    result = subprocess.run(['git', 'diff', '--quiet', 'HEAD', '--', path], cwd=R)
    return result.returncode != 0

for path in ['.github/workflows', 'UniXNU', 'sources', 'UniXNU-b5q/patches', 'UniXNU-b5q/board.toml',
             'UniXNU-b5q/scripts/usb-xhci-26C5035r.json', 'UniXNU-b5q/scripts/usb-dual-bindings-26C5035r.json',
             'UniXNU-b5q/package/B5qWcnPower.cpp', 'UniXNU-b5q/package/B5qBtFifo.c',
             'UniXNU-b5q/package/B5qTouch.cpp', 'UniXNU-b5q/package/B5qDpPdic.h',
             'UniXNU-b5q/package/B5qDpPhy.h', 'UniXNU-b5q/package/B5qDpAux.h']:
    assert not changed(path), 'red-line changed: ' + path
# Review17 intentionally expands H4 observation; transport/power behavior stays byte-identical.
old_bt = subprocess.check_output(['git', 'show', 'HEAD:UniXNU-b5q/package/B5qBluetooth.cpp'], cwd=R).decode()
new_bt = (P / 'B5qBluetooth.cpp').read_text()
for signature in ['int clockVote(', 'void rxIrq(', 'void disarmRxWake(', 'void worker(', 'int setRate(']:
    assert function(old_bt, signature) == function(new_bt, signature), signature
subprocess.run(['git', 'diff', '--check'], cwd=R, check=True)
checks.append(dict(name='review16-zero-diff-red-lines-and-bluetooth', passed=True))

receipt = dict(status='HOST_VERIFIED_PENDING_HARDWARE', passed=True, hardware_verified=False,
               checks=checks, sanitizer='address,undefined', commit_performed=False, push_performed=False,
               CI_triggered=False, ESP_created=False, phone_accessed=False)
(W / 'review16-tests.json').write_text(json.dumps(receipt, indent=2) + '\n')
print('PASS review16 Wi-Fi MAC/probes, USB IR1/IR2 bridge and enumeration, DP AuxPins/link probes; 427 ABI and red lines intact')
