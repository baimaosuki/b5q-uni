#!/usr/bin/env python3
"""review14: WCN6855 TWT config, RDDM seg0 priority, macOS 27.3 LE mask,
BLE H4 event decoding, and public-IOPM host-port power holds."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

R = Path(__file__).resolve().parents[2]
P = R / 'UniXNU-b5q/package'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--out', type=Path, default=Path(os.environ.get('B5Q_GATE_WORK', R / 'artifacts/b5q-review14-local')))
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


def execute(name, command, **kwargs):
    result = subprocess.run(list(map(str, command)), cwd=R, capture_output=True, text=True,
                            env=kwargs.pop('env', None), **kwargs)
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


# 1. Wi-Fi build-script generated source: qca6390 only, plus the WMI probe.
sys.path.insert(0, str(R / 'UniXNU-b5q/scripts'))
spec = importlib.util.spec_from_file_location('review14_build_wifi', R / 'UniXNU-b5q/scripts/build-b5q-wifi.py')
build_wifi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_wifi)
with tempfile.TemporaryDirectory(prefix='review14-wifi-', dir=W) as td:
    gen = build_wifi.prepare(R / 'sources/UniXNU-sheng/drivers/Ath12kWifi', Path(td) / 'wifi')
    hw = (gen / 'hw.c').read_text()
    wmi = (gen / 'wmi.c').read_text()
    qca = function(hw, 'static void ath11k_init_wmi_config_qca6390(')
    ipq = function(hw, 'static void ath11k_init_wmi_config_ipq8074(')
    assert qca.count('twt_ap_pdev_count') == 1 and qca.count('twt_ap_sta_count') == 1
    assert 'ab->num_radios ? ab->num_radios : 1' in qca and 'config->twt_ap_sta_count = 8;' in qca
    assert 'ab->num_radios ? ab->num_radios : 1' not in ipq
    assert 'config->twt_ap_pdev_count = ab->num_radios;' in ipq and 'config->twt_ap_sta_count = 1000;' in ipq
    assert 'B5qWifi: wmi-init radios=%u vdevs=%u peers=%u twt_ap_pdev=%u twt_ap_sta=%u' in wmi
    assert wmi.index('memcpy(&wmi_ab->wlan_resource_config') < wmi.index('B5qWifi: wmi-init')
    inputs = json.loads((Path(td) / 'wifi/source-inputs.json').read_text())
    assert inputs['wcn6855_twt_ap_config'] == 'twt_ap_pdev_count=max(num_radios,1) twt_ap_sta_count=8'
checks.append(dict(name='wifi-twt-ap-and-wmi-probe', passed=True))


# 2. RDDM scanner: live crash RAM (segment 0) first, static high hits capped.
with tempfile.TemporaryDirectory(prefix='review14-rddm-', dir=W) as td:
    model(Path(td), 'rddm-seg0-priority', r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static unsigned hits, seg0, static_high, first_seg;
static char seen[24][161];
static void emit(void *ctx, const struct B5qRddmHit *hit) {
    (void)ctx;
    assert(hit->length <= 160 && hit->length == strlen(hit->text));
    if (hits < 24) strcpy(seen[hits], hit->text);
    if (!hits) first_seg = hit->seg;
    if (hit->priority == 0) { if (hit->seg == 0) seg0++; else static_high++; }
    hits++;
}
static void reset(void) { hits = seg0 = static_high = first_seg = 0; memset(seen, 0, sizeof seen); }
int main(void) {
    struct B5qRddmScan scan;
    const char *live = "ExIPC: Exception recieved tid=1a inst=17be7d0 cause=7003\n"
        "Asserted in live0\nAsserted in live1\nAsserted in live2\n"
        "Asserted in live3\nAsserted in live4\nAsserted in live5\nAsserted in live6\n";
    char stat[1024]; size_t n = 0;
    for (unsigned i = 0; i < 12; i++) n += (size_t)snprintf(stat + n, sizeof stat - n, "Asserted in static%02u\n", i);
    struct B5qRddmSegment segs[2] = {
        {(const uint8_t *)live, (uint32_t)strlen(live)},
        {(const uint8_t *)stat, (uint32_t)strlen(stat)}};
    b5q_rddm_scan_init(&scan, emit, 0);
    reset(); b5q_rddm_scan(&scan, segs, 2);
    assert(first_seg == 0 && strstr(seen[0], "ExIPC: Exception recieved") != 0);
    assert(seg0 == 8 && static_high == 4 && hits == 12 && scan.high == 12);
    assert(static_high <= 6);

    // Twelve live hits consume the high quota, leaving static firmware text none.
    char live12[2048]; n = 0;
    for (unsigned i = 0; i < 12; i++) n += (size_t)snprintf(live12 + n, sizeof live12 - n, "Asserted in live12_%02u\n", i);
    segs[0] = (struct B5qRddmSegment){(const uint8_t *)live12, (uint32_t)strlen(live12)};
    reset(); b5q_rddm_scan(&scan, segs, 2);
    assert(seg0 == 12 && static_high == 0 && scan.high == 12 && first_seg == 0);
    return 0;
}
''', includes=[str(P / 'B5qAth11kRddm.h')])
checks.append(dict(name='rddm-real-crash-slice-seg0-priority', passed=True,
                   real_input='logs/b5q-xnu2log-review13/XNU2LOG.txt:1433'))


# 3. macOS 27.3 bluetoothd: exact thin arm64e sites, UUID and anchors.
bt_path = R / 'artifacts/b5q-p2-work/os-root/usr/sbin/bluetoothd'
assert bt_path.is_file(), bt_path
bt_bytes = bt_path.read_bytes()
bt_sha = hashlib.sha256(bt_bytes).hexdigest()
assert bt_bytes[:4] == b'\xca\xfe\xba\xbe'
narch = struct.unpack_from('>I', bt_bytes, 4)[0]
slice_off = slice_size = None

def uuid_offset(raw):
    ncmds = struct.unpack_from('<I', raw, 16)[0]
    at = 32
    for _ in range(ncmds):
        cmd, size = struct.unpack_from('<II', raw, at)
        if cmd == 0x1b:
            return at + 8
        at += size
    raise AssertionError('LC_UUID missing')

for i in range(narch):
    cputype, subtype, off, size, align = struct.unpack_from('>iiIII', bt_bytes, 8 + i * 20)
    if (cputype & 0xffffffff) == 0x0100000c and (subtype & 0xffffffff) == 0x80000002:
        slice_off, slice_size = off, size
assert slice_off is not None
thin = bytearray(bt_bytes[slice_off:slice_off + slice_size])
assert thin[0:4] == b'\xcf\xfa\xed\xfe'
sys.path.insert(0, str(R / 'UniXNU-b5q/scripts'))
import b5q_bt_le_mask as le

assert thin[le.SITE1_OFFSET:le.SITE1_OFFSET + 8] == le.SITE1_ORIGINAL
try:
    le.patch_macos27_bluetoothd_bytes(bytes(thin))
    raise AssertionError('original 0x001f site1 was accepted without the test switch')
except ValueError as exc:
    assert 'native_macos27' in str(exc)
native = bytearray(thin)
native[le.SITE1_OFFSET:le.SITE1_OFFSET + 8] = le.SITE1_OLD
patched, audit = le.patch_macos27_bluetoothd_bytes(bytes(native))
assert patched[le.SITE1_OFFSET:le.SITE1_OFFSET + 8] == le.SITE1_NEW
assert struct.unpack_from('<I', patched, le.SITE2_OFFSET)[0] == le.SITE2_NEW
assert audit['uuid'] == le.B5Q_UUID and audit['sha256_before'] == hashlib.sha256(native).hexdigest()
assert audit['sha256_after'] == hashlib.sha256(patched).hexdigest()
assert audit['site_count'] == 2 and audit['new_mask'] == 0x187f and audit['old_mask'] == 0x101f

# Negative cases stay byte-exact: wrong UUID, subtype, site1, and both anchors.
bad = bytearray(native); bad[uuid_offset(bad)] ^= 1
for label, data, text in (
        ('uuid', bad, 'UUID'),
        ('subtype', bytearray(native[:8]) + struct.pack('<i', 2) + native[12:], 'cpusubtype'),
        ('site1', bytearray(native), 'site 1 bytes'),
        ('pre-anchor', bytearray(native), 'site 2 pre-anchor'),
        ('post-anchor', bytearray(native), 'site 2 post-anchor')):
    if label == 'site1':
        data[le.SITE1_OFFSET] = 0x1f; data[le.SITE1_OFFSET + 1] = 0x11
    elif label == 'pre-anchor':
        data[0x193644:0x193648] = struct.pack('<I', 0x7100001e)
    elif label == 'post-anchor':
        data[0x19364c:0x193650] = struct.pack('<I', 0xd29f4fe8)
    try:
        le.patch_macos27_bluetoothd_bytes(bytes(data))
        raise AssertionError(label + ' was accepted')
    except ValueError as exc:
        assert text in str(exc), (label, exc)

# The disassembler sees the exact mov w8,#0x187f replacement.
objdump = R / 'tools/llvm21/usr/lib/llvm-21/bin/llvm-objdump'
assert objdump.is_file()
with tempfile.TemporaryDirectory(prefix='review14-bt-', dir=W) as td:
    thin_path = Path(td) / 'bluetoothd-arm64e'
    thin_path.write_bytes(native)
    file_audit = le.patch_macos27_bluetoothd_file(thin_path)
    assert thin_path.read_bytes() == patched
    assert file_audit['sha256_after'] == hashlib.sha256(patched).hexdigest()
    env = dict(os.environ, LD_LIBRARY_PATH=str(R / 'tools/llvm21/usr/lib/x86_64-linux-gnu'))
    dis = subprocess.run([str(objdump), '--macho', '-d', str(thin_path)], capture_output=True, text=True, env=env)
    assert dis.returncode == 0, dis.stderr
    assert '100193648:' in dis.stdout and 'mov\tw8, #0x187f' in dis.stdout
assert hashlib.sha256(bt_path.read_bytes()).hexdigest() == bt_sha
checks.append(dict(name='macos27-bluetoothd-le-mask-real-slice', passed=True,
                   real_input='artifacts/b5q-p2-work/os-root/usr/sbin/bluetoothd',
                   uuid=le.B5Q_UUID, old_mask=0x101f, new_mask=0x187f,
                   slice_offset=slice_off, slice_size=slice_size))


# 4. H4 parsing: new LE events, evt13 counter only, and real BLE conn slice.
with tempfile.TemporaryDirectory(prefix='review14-h4-', dir=W) as td:
    model(Path(td), 'h4-le-events', r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
static char logbuf[65536]; static size_t loglen;
static void line(void *ctx, const char *text) {
    (void)ctx; assert(loglen + strlen(text) + 2 < sizeof logbuf);
    loglen += (size_t)snprintf(logbuf + loglen, sizeof logbuf - loglen, "%s\n", text);
}
static uint64_t now_ms(void *ctx) { (void)ctx; return 1; }
static void feed(struct B5qBtH4Tap *tap, uint8_t evt, const uint8_t *payload, uint32_t n) {
    uint8_t frame[128]; assert(n + 3 <= sizeof frame);
    frame[0] = 4; frame[1] = evt; frame[2] = (uint8_t)n;
    memcpy(frame + 3, payload, n); b5q_bt_h4_tap_feed(tap, 0, frame, n + 3);
}
static int contains(const char *text) { return strstr(logbuf, text) != 0; }
int main(void) {
    struct B5qBtH4Sink sink = {line, now_ms}; struct B5qBtH4Tap tap;
    b5q_bt_h4_tap_init(&tap, &sink, 0, 1);
    const uint8_t conn_param[] = {6,1,0,10,0,32,0,5,0,0xf4,1};
    const uint8_t data_len[] = {7,1,0,0x1b,0,0x2a,0,0x10,0,0x20,0};
    const uint8_t phy[] = {0xc,0,1,0,1,2};
    const uint8_t phy_fail[] = {0xc,1,1,0,1,2};
    feed(&tap, 0x3e, conn_param, sizeof conn_param);
    feed(&tap, 0x3e, data_len, sizeof data_len);
    uint64_t errs_before_phy = tap.stats.errs;
    feed(&tap, 0x3e, phy, sizeof phy);
    assert(contains("le-conn-param-req handle=0x0001 min=0x000a max=0x0020 lat=0x0005 timeout=0x01f4"));
    assert(contains("le-data-len handle=0x0001 tx_oct=0x001b tx_time=0x002a rx_oct=0x0010 rx_time=0x0020"));
    assert(contains("le-phy status=0x00 handle=0x0001 tx_phy=0x01 rx_phy=0x02"));
    assert(tap.stats.errs == errs_before_phy);
    loglen = 0;
    feed(&tap, 0x3e, phy_fail, sizeof phy_fail);
    assert(contains("le-phy status=0x01 handle=0x0001 tx_phy=0x01 rx_phy=0x02 err=1"));
    assert(tap.stats.errs == errs_before_phy + 1);
    const uint8_t evt13[] = {1,0,0,0};
    for (unsigned i = 0; i < 3; i++) feed(&tap, 0x13, evt13, sizeof evt13);
    assert(tap.stats.evt13 == 3 && tap.stats.filtered >= 3 && !contains("evt=13"));
    // Real review13 BLE connection event: status=0 handle=0001 addr=cb:21:d5:9d:42:41.
    const uint8_t real[] = {0x04,0x3e,19,1,0,1,0,0,0,0xcb,0x21,0xd5,0x9d,0x42,0x41,0x18,0,0,0,0x48,0,0};
    loglen = 0; b5q_bt_h4_tap_feed(&tap, 0, real, sizeof real);
    assert(contains("le-conn status=0x00 handle=0x0001") && contains("cb:21:d5:9d:42:41"));
    return 0;
}
''', includes=[str(P / 'B5qBtH4Tap.h')])
checks.append(dict(name='h4-le-events-and-real-conn-slice', passed=True,
                   real_input='logs/b5q-xnu2log-review13/XNU2LOG.txt:2031'))


# 5. Kernel BT source: p_comm truncation, evt13 health field and decoders.
bt = (P / 'B5qBluetooth.cpp').read_text()
assert 'i==2?!strncmp(name,"BluetoothUIServe",16)' in bt
assert 'desync=%llu evt13=%llu logged=%u/%u' in bt and 'h4Tap.stats.evt13' in bt
h4 = (P / 'B5qBtH4Tap.h').read_text()
assert 'uint64_t evt13;' in h4 and 'tap->stats.evt13++' in h4
assert 'le-conn-param-req' in h4 and 'le-data-len' in h4 and 'le-phy status=' in h4
assert 'if (sub == 0x0cu && b5q_h4_get8(v, payload + 1u) != 0u) error = 1;' in h4
checks.append(dict(name='bt-kernel-probes-and-health', passed=True))


# 6. USB host: public-IOPM child, managed table, release before terminate.
usb = (P / 'QcomDwc3.cpp').read_text()
hold = function(usb, 'PortHoldResult ensureHostPortHold(IOService *port)')
assert 'OSTypeAlloc(B5qUsbPortPowerHold)' in hold and 'hold->PMinit()' in hold
assert 'port->addPowerChild(hold)' in hold and 'port->changePowerStateTo(3)' in hold
assert 'if(slot==-2){port->release();return hostPortHoldState(port);}' in hold
assert 'if(slot==-1){port->release();return kPortHoldFailed;}' in hold
assert 'hold->PMstop();hold->release();hold=nullptr;' in hold
assert 'removePowerChild' not in usb and 'IOPowerConnection' not in usb
assert 'copyParentEntry' not in hold
assert 'port-power-hold name=%s add=%x req=%x pwr=%lu' in hold
configure = function(usb, 'void configureHostPorts(IOService *host) {')
assert 'setHostPortHoldOwner(host)' in configure and 'ensureHostPortHold(port)' in configure
assert 'hold==kPortHoldFailed' in configure and 'hold==kPortHoldAttached' in configure
assert 'UsbForcePower' in configure and 'if(!forceOk||port->getPowerState()<3)' not in configure
release = function(usb, 'void releaseHostPortPowerHolds() {')
assert 'hold->changePowerStateTo(0)' in release
assert 'for(unsigned wait=0;wait<50u;wait++)' in release
assert 'copyParentEntry(gIOPowerPlane)' in release and 'if(!parent)break;' in release
assert 'parent->release()' in release and 'IOSleep(1)' in release
assert release.index('hold->changePowerStateTo(0)') < release.index('hold->PMstop()')
assert release.index('hold->PMstop()') < release.index('copyParentEntry(gIOPowerPlane)')
assert release.index('copyParentEntry(gIOPowerPlane)') < release.index('parent->release()')
assert release.index('parent->release()') < release.index('IOSleep(1)')
assert release.index('IOSleep(1)') < release.index('hold->release()')
leave = function(usb, 'void leaveRole(int role)')
assert leave.index('releaseHostPortPowerHolds()') < leave.index('gHostNub->terminate')
assert leave.count('releaseHostPortPowerHolds()') == 1
role = function(usb, 'void roleThread(')
assert 'kFastPortPollAttempts' in role and 'IOSleep(50)' in role
assert role.index('for(unsigned i=0;i<B5qUsbHostRole::kFastPortPollAttempts') < role.index('fastPortPollNeeded(hostPortHoldCount())')
assert 'kPortPowerHoldSlots = 8' in (P / 'B5qUsbHostRole.h').read_text()
checks.append(dict(name='usb-port-power-hold-lifecycle', passed=True))

with tempfile.TemporaryDirectory(prefix='review14-usb-', dir=W) as td:
    model(Path(td), 'usb-host-role-helpers', r'''
#include <assert.h>
int main(void) {
    assert(B5qUsbHostRole::fastPortPollNeeded(0));
    assert(B5qUsbHostRole::fastPortPollNeeded(1));
    assert(!B5qUsbHostRole::fastPortPollNeeded(2));
    assert(!B5qUsbHostRole::fastPortPollNeeded(8));
    assert(B5qUsbHostRole::portEdge(2, 0));
    assert(B5qUsbHostRole::portEdge(0, 1u << 17));
    assert(B5qUsbHostRole::portEdge(0, 1u << 22));
    assert(!B5qUsbHostRole::portEdge(0, 0));
    return 0;
}
''', cpp=True, includes=[str(P / 'B5qUsbHostRole.h')])
checks.append(dict(name='usb-fast-attach-state-helper', passed=True))

receipt = dict(passed=True, hardware_verified=False, review=14, checks=checks,
               real_device_inputs=[
                   'logs/b5q-xnu2log-review13/XNU2LOG.txt:1433',
                   'logs/b5q-xnu2log-review13/XNU2LOG.txt:2031',
                   'artifacts/b5q-p2-work/os-root/usr/sbin/bluetoothd'],
               bluetoothd_sha256=bt_sha, bluetoothd_slice_offset=slice_off,
               bluetoothd_slice_size=slice_size, le_event_mask=0x187f,
               sanitizer='address,undefined', host_only=True,
               push_performed=False, CI_triggered=False, ESP_created=False, phone_accessed=False)
(W / 'review14-tests.json').write_text(json.dumps(receipt, indent=2) + '\n')
print('PASS review14 WCN6855 TWT init, RDDM seg0 priority, macOS 27.3 LE mask, BLE H4 probes and IOPM host-port power hold')
