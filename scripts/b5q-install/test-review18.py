#!/usr/bin/env python3
"""Exercise Review18 production transforms, journal contract and bounded probes."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib

R = Path(__file__).resolve().parents[2]
P = R / 'UniXNU-b5q/package'
ap = argparse.ArgumentParser(description=__doc__)
ap.add_argument('--out', type=Path, default=Path(os.environ.get('B5Q_GATE_WORK', R / 'artifacts/b5q-review18-local')))
W = ap.parse_args().out.resolve()
W.mkdir(parents=True, exist_ok=True)
checks = []


def run(name, command):
    p = subprocess.run(list(map(str, command)), cwd=R, capture_output=True, text=True)
    output = p.stdout + p.stderr
    (W / (name + '.log')).write_text(output)
    if p.returncode:
        raise RuntimeError(name + '\n' + output[-6000:])
    checks.append(dict(name=name, passed=True, log_sha256=hashlib.sha256(output.encode()).hexdigest()))
    print('PASS', name, flush=True)


def function(text, signature):
    first = text.index(signature)
    at = text.index('{', first)
    end, depth = at + 1, 1
    while depth:
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    return text[first:end]


def host(temp, name, source):
    cpp, binary = temp / (name + '.cpp'), temp / name
    cpp.write_text(source)
    run(name + '-compile', ['c++', '-Wno-misleading-indentation', '-std=c++17', '-O1', '-g', '-Wall', '-Wextra', '-Werror',
        '-Wno-unused-parameter', '-fsanitize=address,undefined', '-fno-sanitize-recover=all',
        '-I' + str(P), cpp, '-o', binary])
    run(name + '-ASan-UBSan', [binary])


sys.path.insert(0, str(R / 'tools/xnu2log/scripts'))
import nabu_log_volume as volume
import read_xnu2log as reader
token = bytes(range(16))
assert volume.CAPACITY == 16 * 1024 * 1024 and volume.FILE_BYTES == 33566720
for capacity in [4 * 1024 * 1024, 16 * 1024 * 1024]:
    slot = 4096 + capacity
    for first in [0, 1024]:
        payload = b'tail' if not first else bytes(capacity)
        encoded = volume.encode_slot(token, 9, bytes(16), payload, first=first, capacity=capacity)
        image = volume.make_config(token, capacity) + encoded + bytes(slot)
        data, info = volume.decode_container(image)
        assert data == payload and info['ring_capacity'] == capacity and info['sequence'] == 9
        assert reader.parse_slot(image, 4096, token)['data'] == payload
        broken = bytearray(image)
        broken[16] ^= 1
        try:
            volume.decode_container(broken)
            raise AssertionError('accepted corrupt geometry')
        except ValueError:
            pass
checks.append(dict(name='journal16MiB-and-legacy4MiB-dynamic-decode', passed=True))

with tempfile.TemporaryDirectory(prefix='review18-', dir=W) as directory:
    temp = Path(directory)
    host(temp, 'policy-and-coordinates', r'''
#include <cassert>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>
#include "ThermalLevel.h"
#include "B5qProcTopFormat.h"
#include "B5qTouchReports.h"
#include "B5qUsbHostRole.h"
#include "B5qUfs/B5qLogFormat.h"
static std::vector<std::string> logs;
static void emit(const char *s,void*){assert(strlen(s)<255);logs.emplace_back(s);}
int main(){
 uint8_t hidpi[12]{};B5qDisplay::hidpiMode(2640,1080,hidpi);
 const uint8_t expectedMode[12]={0,0,0x0a,0x50,0,0,4,0x38,0,0,0,1};assert(!memcmp(hidpi,expectedMode,12));
 assert(NB_LOG_CAPACITY==16u*1024*1024&&NB_LOG_FILE_BYTES==33566720u);
 assert(thermal_level_input(0,69999,thermal_level_cpu_trips)==0);
 assert(thermal_level_input(0,70000,thermal_level_cpu_trips)==1);
 assert(thermal_level_input(1,67000,thermal_level_cpu_trips)==1);
 assert(thermal_level_input(1,66999,thermal_level_cpu_trips)==0);
 assert(thermal_level_input(0,80000,thermal_level_cpu_trips)==2);
 assert(thermal_level_input(0,90000,thermal_level_cpu_trips)==3);
 assert(thermal_level_input(0,68000,thermal_level_gpu_trips)==1);
 assert(thermal_level_input(0,78000,thermal_level_gpu_trips)==2);
 assert(thermal_level_input(0,88000,thermal_level_gpu_trips)==3);
 static b5q_cpu_window cpu;
 b5q_cpu_begin(&cpu,0);
 for(int i=0;i<7;i++)b5q_cpu_sample(&cpu,i,100+i,i?"busy":"kernel_task",1000000000);
 b5q_cpu_begin(&cpu,30000);
 for(int i=0;i<7;i++)b5q_cpu_sample(&cpu,i,100+i,i?"busy":"kernel_task",1000000000+uint64_t(i+1)*1000000000);
 assert(cpu.top[0].pid==6&&cpu.top[0].delta_ms==7000&&cpu.top[0].permille==233);
 assert(cpu.kernel.delta_ms==1000);
 b5q_cpu_print(&cpu,emit,nullptr);assert(logs.size()==6&&logs.back().find("kernel_task")!=std::string::npos);
 b5q_cpu_begin(&cpu,30000);b5q_cpu_sample(&cpu,6,999,"reused",900000000000);
 assert(!cpu.top[0].delta_ms); // no CPU attribution across PID reuse
 b5q_cpu_begin(&cpu,30000);b5q_cpu_sample(&cpu,6,999,"exec-reset",1);assert(!cpu.top[0].delta_ms);
 B5qUsbHostRole::View view{true,true,true,false,true,false,true,true,true};
 assert(B5qUsbHostRole::canReleaseSuperSpeed(view,2,4));
 assert(!B5qUsbHostRole::canReleaseSuperSpeed(view,4,2));
 assert((B5qUsbHostRole::disableSuperSpeed(0xffffffffu)&((1u<<4)|(0x7fu<<17)|(1u<<16)))==0);
 assert(B5qUsbHostRole::disableSuperSpeed(0)&2u);
 view.cableWater=true;assert(!B5qUsbHostRole::canReleaseSuperSpeed(view,2,4));
 for(unsigned angle:{0u,90u,270u}){
  const unsigned w=angle?2640:1080,h=angle?1080:2640,pw=1080,ph=2640;
  const unsigned stride=pw*4+16,srcStride=w*4+12;
  std::vector<uint8_t> source(uint64_t(srcStride)*h),dest(uint64_t(stride)*ph,0xaa);
  for(unsigned y=0;y<h;y++)for(unsigned x=0;x<w;x++){
   uint32_t value=(y<<16)|x;memcpy(source.data()+uint64_t(y)*srcStride+x*4,&value,4);
  }
  assert(B5qDisplay::copy(dest.data(),dest.size(),stride,source.data(),source.size(),srcStride,w,h,angle,4,
    [](const uint8_t*p){uint32_t v;memcpy(&v,p,4);return v|0xff000000u;}));
  for(unsigned y:{0u,h/2,h-1})for(unsigned x:{0u,w/2,w-1}){
   unsigned px,py,lx,ly;B5qDisplay::toPhysical(x,y,w,h,angle,px,py);
   B5qDisplay::fromPhysical(px,py,pw,ph,angle,lx,ly);assert(lx==x&&ly==y);
   uint32_t value;memcpy(&value,dest.data()+uint64_t(py)*stride+px*4,4);assert(value==((y<<16)|x|0xff000000u));
  }
  for(unsigned y=0;y<ph;y++)for(unsigned pad=pw*4;pad<stride;pad++)assert(dest[y*stride+pad]==0xaa);
  assert(!B5qDisplay::copy(dest.data(),dest.size()-stride,stride,source.data(),source.size(),srcStride,w,h,angle,4,[](const uint8_t*){return 0u;}));
  for(unsigned x:{0u,2048u,4095u})for(unsigned y:{0u,2048u,4095u}){
   unsigned lx,ly;B5qTouch::displayPoint(x,y,angle,lx,ly);
   unsigned px,py;B5qDisplay::toPhysical(lx,ly,4096,4096,angle,px,py);assert(px==x&&py==y);
  }
 }
}
''')
    # Execute the actual production AIR functions on the host, rather than a
    # second shader model. Only the target triple changes for this test object.
    air = R / 'UniXNU/drivers/AdrenoMetal/shaders/scanout_convert.ll'
    obj = temp / 'scanout.o'
    run('production-AIR-host-compile', ['/usr/lib/llvm-17/bin/clang', '-target', 'x86_64-unknown-linux-gnu',
        '-Wno-override-module', '-fsanitize=address,undefined', '-c', air, '-o', obj])
    cpp = temp / 'shader.cpp'
    cpp.write_text(r'''
#include <cassert>
#include <cstdint>
#include <vector>
typedef uint32_t xy __attribute__((ext_vector_type(2)));
extern "C" void scanout_opaque(const uint32_t*,uint32_t*,const uint32_t*,xy);
extern "C" void scanout_convert(const uint32_t*,uint32_t*,const uint32_t*,const uint32_t*,xy);
int main(){for(unsigned angle:{0u,90u,270u}){
 unsigned w=5,h=3,pw=angle?h:w,ph=angle?w:h;uint32_t p[4]={w,h|(angle<<16),w+1,pw+2};
 std::vector<uint32_t> src((w+1)*h),dst((pw+2)*ph,0xaa),half((w+1)*h*2),table(65536);
 for(unsigned i=0;i<table.size();i++)table[i]=i&255;
 for(unsigned y=0;y<h;y++)for(unsigned x=0;x<w;x++){
  src[y*(w+1)+x]=y*16+x;scanout_opaque(src.data(),dst.data(),p,xy{x,y});
  unsigned px=angle==90?y:angle==270?h-1-y:x,py=angle==90?w-1-x:angle==270?x:y;
  assert(dst[py*(pw+2)+px]==(0xff000000u|src[y*(w+1)+x]));
 }
 p[2]=(w+1)*2;
 for(unsigned y=0;y<h;y++)for(unsigned x=0;x<w;x++){
  half[y*p[2]+x*2]=0x00220011;half[y*p[2]+x*2+1]=0x0033;
  scanout_convert(half.data(),dst.data(),table.data(),p,xy{x,y});
  unsigned px=angle==90?y:angle==270?h-1-y:x,py=angle==90?w-1-x:angle==270?x:y;
  assert(dst[py*(pw+2)+px]==0xff112233);
 }
 for(unsigned y=0;y<ph;y++)assert(dst[y*(pw+2)+pw]==0xaa&&dst[y*(pw+2)+pw+1]==0xaa);
 scanout_opaque(src.data(),dst.data(),p,xy{99,99}); // out-of-grid threads do no write
}}
''')
    binary = temp / 'shader'
    run('production-AIR-link', ['/usr/lib/llvm-17/bin/clang++', '--gcc-install-dir=/usr/lib/gcc/x86_64-linux-gnu/13', '-std=c++17', '-fsanitize=address,undefined', cpp, obj, '-o', binary])
    run('production-AIR-rotation-and-half-colors', [binary])

usb = (P / 'QcomDwc3.cpp').read_text()
assert 'kUsbPortDebugOptions=0u' in usb and 'kUsbHostDebugOptions=0u' in usb
assert 'usb-debug' in function(usb, 'static uint32_t usbDebugMask(')
lane = usb[usb.index('if(dpEnabled&&B5qUsbHostRole::canReleaseSuperSpeed'):]
lane = lane[:lane.index('        if(dpEnabled&&!b5q_dp_link_stop')]
assert 'leaveRole(' not in lane and 'enterRole(' not in lane and 'selectUtmiClock()' in lane
assert '20u);continue;' in function(usb, 'static void hostIrqBridge(')
for needle in ['host-slot2', 'host-setup', 'hub-transfer-failed', '__atomic_fetch_add(&hubDumps']:
    assert needle in usb
checks.append(dict(name='usb-no-default-debug-hub-probes-and-retained-usb2', passed=True))

logger = (P / 'B5qUfs/B5qLogUfs.h').read_text()
assert 'nabuLogPause(4000)' in logger and 'nabuLogPause(1000)' not in logger
urgent = function(logger, 'extern "C" int b5q_log_flush_urgent(')
assert 'b5q_log_sync' in urgent and '300u' in urgent and 'IOLock' not in urgent
sync = function(logger, 'extern "C" unsigned b5q_log_sync(')
for word in ['ml_at_interrupt_context()', 'get_preemption_level()', 'nabu_log_urgent_end', 'nabu_log_committed_end']:
    assert word in sync
checks.append(dict(name='logger-4s-single-writer-bounded-urgent', passed=True))

sys.path.insert(0, str(R / 'UniXNU-b5q/scripts'))
import b5q_wifi
with tempfile.TemporaryDirectory(prefix='review18-wifi-', dir=W) as td:
    td = Path(td)
    network = b5q_wifi.prepare(R / 'sources/UniXNU-sheng', td)
    drain = function(network.read_text(), 'int drain_disconnect(')
    assert 'if (!nw_wifi_disconnect_pending()) disconnect_user();' in drain
    module = R / 'sources/UniXNU-sheng/drivers/Ath12kWifi/src'
    main = b5q_wifi.select_shared(module / 'nw_mainline.c', td).read_text()
    control = b5q_wifi.select_shared(module / 'nw_cfg80211_control.c', td).read_text()
    for needle in ['owner_connected=', 'radio_enabled=', 'begin_attempt_rc=', 'begin_attempt_ms=', 'event_send_rc=', 'ui_cleared=', 'before', 'after-begin', '-ENOTCONN', '-ERFKILL']:
        assert needle in main
    assert '__atomic_fetch_add' in main and '< 64u' in main
    assert 'b5q_owner_trace("opened")' in control and 'b5q_owner_trace("closed")' in control
checks.append(dict(name='wifi-production-generator-owner-dispatch-drain', passed=True))
# The production reuse decision must reject an old runtime and accept only a
# matching source stamp embedded in the addon, with no cache deletion.
import b5q_display
with tempfile.TemporaryDirectory(prefix='review18-reuse-',dir=W) as td:
    td=Path(td);(td/'scripts').mkdir();(td/'drivers/AdrenoMetal').mkdir(parents=True)
    (td/'scripts/addon-add-dir.py').write_bytes((R/'UniXNU/scripts/addon-add-dir.py').read_bytes())
    (td/'drivers/AdrenoMetal/probe.h').write_text('current')
    spec=importlib.util.spec_from_file_location('review18_addon_codec',td/'scripts/addon-add-dir.py')
    codec=importlib.util.module_from_spec(spec);spec.loader.exec_module(codec)
    addon=td/'addon.bin';name='System/Library/Extensions/NativeAdrenoMetal.bundle/Contents/Resources/gpu-build.json'
    stamp=dict(target='macos27',metal_source_sha256=b5q_display.runtime_source_id(td))
    codec.write(addon,[(name,0o644,json.dumps(stamp).encode())])
    assert b5q_display.runtime_reusable(td,addon)
    (td/'drivers/AdrenoMetal/probe.h').write_text('changed')
    assert not b5q_display.runtime_reusable(td,addon)
    # Execute the real payload builder's reuse-selection statements. A
    # current completed runtime wins over an old downloaded addon; when
    # both are stale, request a source build with caches retained.
    import ast
    from types import SimpleNamespace
    recipe=ast.parse((R/'UniXNU-b5q/scripts/build-b5q-payload.py').read_text())
    start=next(i for i,node in enumerate(recipe.body) if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='addon_input' for t in node.targets))
    selected=recipe.body[start:start+3]
    assert isinstance(selected[2],ast.If)
    code=compile(ast.Module(body=selected,type_ignores=[]),'production-addon-selection','exec')
    runtime=td/'runtime';runtime.mkdir();provided=td/'data.dbr'
    codec.write(td/'gpu-addon.bin',[(name,0o644,b'{}')])
    trust=td/'current-trust.bundle';trust.write_bytes(b'fixture-presence-only')
    (runtime/'generated.json').write_text(json.dumps(dict(gpu_addon=str(addon),trust_cache=str(trust))))
    (td/'drivers/AdrenoMetal/probe.h').write_text('current')
    context=dict(provided=provided,Path=Path,ctx=SimpleNamespace(tree=td),runtime=runtime,
                 runtime_reusable=b5q_display.runtime_reusable,json=json,a=SimpleNamespace(reuse_addon=True),print=lambda *a:None)
    exec(code,context)
    assert context['a'].reuse_addon and context['addon_input']==addon and context['owner_trust']==trust
    (td/'drivers/AdrenoMetal/probe.h').write_text('changed-again')
    context['a'].reuse_addon=True;exec(code,context);assert not context['a'].reuse_addon
checks.append(dict(name='runtime-addon-source-stamp-and-completed-pair-selection',passed=True))


dp = (P / 'B5qDpLink.cpp').read_text()
session = (P / 'B5qDpSession.h').read_text()
for needle in ['trace("map")', 'trace("gdsc")', 'trace("dpu-inspect")', 'trace("aux-gpio")', 'io.trace("scanout")', 'io.trace("iomfb")']:
    assert needle in dp
for needle in ['clock-aux', 'ctrl-reset', 'phy-aux-setup', 'aux-dpcd', 'edid', 'phy-train']:
    assert 'trace("' + needle + '")' in session
assert 'b5q_usb_dp_phy_ready()' in dp and 'branch(0x80a4)' in dp and 'branch(0xa020)' in dp
assert 'b5q_log_flush_urgent(250)' in dp and '__atomic_fetch_add(&traceCount' in dp
assert session.index('trace("clock-aux")') < session.index('trace("ctrl-reset")') < session.index('trace("phy-aux-setup")') < session.index('trace("aux-dpcd")') < session.index('trace("edid")')
checks.append(dict(name='dp-clock-prerequisites-and-ordered-urgent-breadcrumbs', passed=True))
legacy=(R/'UniXNU/drivers/GopFramebuffer/NativeLegacyDisplay.cpp').read_text()
assert '"scale-resolutions"' in legacy and 'B5qDisplay::hidpiMode' in legacy
assert '"IOMFBLogicalWidth"' not in legacy and '"IOFBHiDPI"' not in legacy
assert 'widthMm=156;heightMm=64' in legacy
checks.append(dict(name='native-timing-EDID-physical-size-and-standard-HiDPI-mode',passed=True))


base = json.loads((R / 'artifacts/b5q-review18-local/before.json').read_text())
for name, digest in base['protected_sha256'].items():
    if name == '.github/workflows/b5q-p0-p5.yml':
        # Owner-authorized release: only the new upstream pin and additive
        # archive/runtime uploads differ from the reviewed workflow.
        digest = '50360d5872a0271fc7817db7dcc27b3afdd506ee81cc66abcee6de992ddbd2dd'
    assert hashlib.sha256((R / name).read_bytes()).hexdigest() == digest, name
old_bt=subprocess.check_output(['git','show','HEAD:UniXNU-b5q/package/B5qBluetooth.cpp'],cwd=R).decode()
new_bt=(P/'B5qBluetooth.cpp').read_text()
old_bt=old_bt.replace('extern "C" void thread_yield_to_preemption(void);\n','').replace('        if(!deadline){thread_yield_to_preemption();continue;}\n        waitUntil(nullptr,deadline);','        waitUntil(nullptr,b5q_bt_worker_deadline(deadline,t));')
assert new_bt.replace('#include "B5qWorkerWait.h"\n','')==old_bt
old_touch=subprocess.check_output(['git','show','HEAD:UniXNU-b5q/package/B5qTouch.cpp'],cwd=R).decode()
new_touch=(P/'B5qTouch.cpp').read_text()
new_publish=function(new_touch,'void publish(');old_publish=function(old_touch,'void publish(')
# Normalize the Review18 declaration on both sides: HEAD may already include Review18.
rotation_decl='extern "C" uint32_t b5q_display_rotation(void);\n'
assert new_touch.replace('    thread_set_thread_name(current_thread(),"b5q-touch");\n','').replace(rotation_decl,'').replace(new_publish,old_publish)==old_touch.replace(rotation_decl,'')
checks.append(dict(name='touch-protocol-worker-click-flow-unchanged-outside-coordinate-transform',passed=True))

args = tomllib.loads((R / 'UniXNU-b5q/board.toml').read_text())['payload']['kernel_args']
assert len(' '.join(args).encode()) <= 1023
assert len(list((R / 'tests/b5q-ufs').glob('test-dp-*.py'))) == 26
checks.append(dict(name='protected68-inputs-and-BT-byte-identity-1023B-26DP', passed=True))

report = dict(status='HOST_VERIFIED_PENDING_HARDWARE', passed=True, hardware_verified=False, checks=checks,
              commit_performed=False, push_performed=False, ci_triggered=False, esp_created=False, phone_accessed=False)
(W / 'review18-tests.json').write_text(json.dumps(report, indent=2) + '\n')
print('PASS Review18 production host checks; hardware qualification pending')
