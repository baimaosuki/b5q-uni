from pathlib import Path
import hashlib,json,re,tomllib
root=Path(__file__).resolve().parents[2];device=root/'UniXNU-b5q';work=root/'artifacts/b5q-runtime-v22-work'
board=tomllib.loads((device/'board.toml').read_text());args=board['payload']['kernel_args']
assert args.count('touch=0')==1 and 'touch=1'not in args and len(' '.join(args).encode())<=1000
old=json.loads((root/'artifacts/b5q-esp-runtime-v21/package.manifest.json').read_text())
assert set(args)-set(old['kernel_command_line'].split())=={'touch=0'}
assert set(old['kernel_command_line'].split())-set(args)=={'touch=1'}
rules=json.loads((root/'artifacts/b5q-runtime-v20-work/seven-rule-check.json').read_text())['rules']
assert board['payload']['text_fixups']==[f"dyld_shared_cache_arm64e.03,{r['offset']},{r['original']},{r['replacement']}"for r in rules]
thermal=(device/'package/ThermalProbe.cpp').read_text()
for forbidden in ['gSrot','gGicd','kGicd','thermal_srot_base','kRegNearIntrClr']:assert forbidden not in thermal,forbidden
assert 'thermal_pick_valid' in thermal and 'B5qThermal: stage=ready' in thermal
assert 'B5qThermal: stage=ready'in(device/'package/ThermalLevel.cpp').read_text()
touch=(device/'package/B5qTouch.cpp').read_text();assert touch.index('B5qTouchClock::enable')<touch.index('se=map(2,')
assert 'se[0xe30/'not in touch and 'se[0xe18/'not in touch and 'se[0x7c/'not in touch
clock=(device/'package/B5qTouchClock.h').read_text();assert 's4=0x184e4'in clock and 'write(vote,read(vote)|enables)'in clock
legacy=(device/'package/LegacyDisplayProbe.cpp').read_text();start=legacy.index('void native_legacy_display_late_probe(void) {');late=legacy[start:]
assert 'sheng_thermal_probe();'not in late and 'native_hid_input_probe();'not in late
assert late.index('display->start(nub)')<late.index('startB5qPeripherals();')
assert 'kernel_thread_start(b5qPeripheralWorker'in legacy
usb=(device/'package/B5qUsbHost.cpp').read_text();assert usb.index('nub->registerService();')<usb.index('host->start(nub)')
buttons=(device/'package/ButtonProbe.cpp').read_text();assert buttons.count('*apidReg(apid, kIrqClear) = 0xff;')==2
package='\n'.join(p.read_text()for p in(device/'package').glob('*')if p.suffix in ['.c','.cpp','.h'])
assert not re.search(r'0x0*15000000\b',package,re.I) and not re.search(r'/chosen/b5q-[^"\s]*-handoff',package)
pac=json.loads((work/'geni-pac.json').read_text());target=json.loads((work/'target-check.log').read_text());assert pac['passed']and target['passed']
workflow=(root/'.github/workflows/b5q-runtime.yml').read_text();assert '--source-run 44831204824'in workflow and 'relink-b5q-peripherals.py'in workflow
assert 'make-macos-data-seed'not in workflow and 'build-data-seed.py'not in workflow
assert '--changed B5qUsbHost.cpp,LegacyDisplayProbe.cpp,ThermalProbe.cpp,ThermalLevel.cpp,ButtonProbe.cpp,B5qTouch.cpp,GeniI2c.c'in workflow
report={'passed':True,'source_contracts':['touch_default_off','bounded_real_GCC_branch_check_before_SE','no_privileged_SE_writes','thermal_TM_valid_only_no_SROT_GICD','foreign_arbiter_IRQ_clear','after_display_async_peripherals','USB_provider_registered_before_host_start','typed_C_CPP_PAC','unchanged_Data_Graphics_core_cache'],'kernel_args_bytes':len(' '.join(args).encode()),'only_arg_change':'touch=1 -> touch=0','hardware_tested':False}
(work/'v22-input-checks.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
