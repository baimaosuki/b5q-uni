"""Local v21 input contract; final image/account/binary checks are post-build."""
from pathlib import Path
import hashlib,importlib.util,json,re,subprocess,tempfile,tomllib
root=Path(__file__).resolve().parents[2];device=root/'UniXNU-b5q';work=root/'artifacts/b5q-runtime-v21-work'
board=tomllib.loads((device/'board.toml').read_text());args=board['payload']['kernel_args'];line=' '.join(args)
required='timebase-user=1 sched_preemption_disable_debug_mode=0 interrupt-masked-debug-mode=0 validation_disables=0x11040 ca-triple-buffer=1 ca-free-wakeup=1 cpufreq=3 thermal=1 thermal-ms=100 thermal-level=1 board-clock=1 offline-hid-input=1 offline-hid-home=1 buttons=1 touch=1 touch-hid=1 b5q-dpi=425 dpu=1 offline-legacy-unit-scale=2'.split()
assert all(args.count(x)==1 for x in required) and len(line.encode())<=1000
old=json.loads((root/'artifacts/b5q-runtime-v20-work/seven-rule-check.json').read_text())
expected=[f"dyld_shared_cache_arm64e.03,{r['offset']},{r['original']},{r['replacement']}" for r in old['rules']]
assert board['payload']['text_fixups']==expected and len(expected)==7
source_files=sorted(p for p in (device/'package').glob('*') if p.suffix in ['.h','.c','.cpp'])
source='\n'.join(p.read_text() for p in source_files)
assert not re.search(r'/chosen/b5q-[^\s"\']*-handoff',source)
assert not re.search(r'0x0*15000000\b',source,re.I)
dpu=(device/'package/DisplayTimingProbe.cpp').read_text();assert 'gLevel >= 3' not in dpu and 'gLevel>=3' not in dpu
assert 'enabled != 1' in dpu
usb=(device/'package/B5qUsbHost.cpp').read_text();policy=(device/'package/B5qUsbPolicy.h').read_text()
assert 'B5qUsbPolicy::scratch' in usb and 'b5q_usb_repeater_host' in usb
for off in ['0xc120','0xc110','0xc704','0xc70c','0xc200','0xc2c0','0x808','0x810','0x830','0x10']:assert off in usb,off
assert '0x7fd' in (device/'package/B5qSpmi.cpp').read_text()
for name in ['sheng_cpufreq_probe','sheng_thermal_probe','sheng_thermal_level_probe','sheng_board_clock_probe','sheng_buttons_probe','native_hid_input_probe','b5q_touch_probe','sheng_dpu_probe']:assert name+'()' in source,name
workflow=(root/'.github/workflows/b5q-runtime.yml').read_text()
for token in ['--user baimao:1234 --real-name baimao --auto-login','reuse-completed-build.py','--reuse-addon','44828924826','44794616634','fetch xnu IOHIDFamily']:assert token in workflow,token
assert 'unixnu build kernel' not in workflow and 'build-mesa' not in workflow and 'build-adreno-metal' not in workflow
target=json.loads((work/'target-check.log').read_text());assert target['passed'] and target['XHCI_slots']==427
hid=json.loads((work/'hid-bindings.json').read_text());assert hid['slots']==334 and hid['all_diversities_checked']
assert json.loads((device/'scripts/hid-bindings-26C5035r.json').read_text())==hid
result={'passed':True,'input_checks':[2,3,4,5,7,8,9],'Data_official_writers_tested_separately':True,
 'required_post_build_checks':[1,4,5,6,9,10],'kernel_args_bytes':len(line.encode()),'seven_rules_unchanged':True,
 'apps_smmu_new_board_mapping_count':0,'fake_handoff_gate_count':0,
 'source_sha256':{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files},'hardware_tested':False}
(work/'v21-input-checks.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result|{'source_sha256':'recorded'},indent=2))
