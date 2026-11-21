"""Validate the requested v23 source/configuration and exact retained inputs locally."""
from pathlib import Path
import hashlib,json,re,tomllib,sys
root=Path(__file__).resolve().parents[2];w=root/'artifacts/b5q-runtime-v23-work';device=root/'UniXNU-b5q'
board=tomllib.loads((device/'board.toml').read_text());old=json.loads((root/'artifacts/b5q-esp-runtime-v22/package.manifest.json').read_text())
args=board['payload']['kernel_args'];old_args=old['kernel_command_line'].split()
assert set(args)-set(old_args)=={'buttons=0','touch-hid=0','offline-hid-input=0'}
assert set(old_args)-set(args)=={'buttons=1','touch-hid=1','offline-hid-input=1'}
assert len(args)==len(set(args))
for arg in ['touch=0','cpufreq=3','thermal=1','thermal-ms=100','thermal-level=1','board-clock=1','b5q-dpi=425','offline-legacy-unit-scale=2','dpu=1','validation_disables=0x11040','timebase-user=1','ca-triple-buffer=1','ca-free-wakeup=1','b5q-usb=1']:assert arg in args,arg
rules=json.loads((root/'artifacts/b5q-runtime-v20-work/seven-rule-check.json').read_text())['rules']
assert board['payload']['text_fixups']==[f"dyld_shared_cache_arm64e.03,{r['offset']},{r['original']},{r['replacement']}"for r in rules]
source=(device/'package/B5qUsbHost.cpp').read_text();start=source.index(' IOReturn registerInterrupt(');end=source.index(' IOReturn unregisterInterrupt(',start);register=source[start:end]
assert register.index('owner=target;context=ref;action=handler;')<register.index('armcpu_spi_attach(')<register.index('const int masked=armcpu_spi_mask(')
assert 'if(!__atomic_load_n(&self->enabled' in source and '__atomic_store_n(&self->stormed,true' in source
assert 'if(__atomic_load_n(&stormed' in source and '__atomic_store_n(&unhandledCount,0u' in source
worker=source[source.index('static void worker('):];assert worker.index('IOSleep(delaySec*1000)')<worker.index('core.open(')
assert 'unsigned delaySec=35' in worker and 'if(delaySec>300)delaySec=300' in worker
assert 'irq=%u un=%u storm=%u pwr=%lu' in source and 'getPowerState()' in source
assert 'gIOCatalogue->startMatching(name)' in source
for off in ['0xc40c','0xc708']:assert off in source
policy=(device/'package/B5qUsbPolicy.h').read_text()
for text in ['write(0xc708,0)','write(0xc408,size|(1u<<31))','write(0xc40c,count&0xffffu)','(hardware&3u)==2u','write(0xcc0c,0)','read(0xcc08,pending)','write(0xcc08,pending)','delay(20000)','write(0xc110,gctl&~(1u<<11))']:assert text in policy,text
assert 'write(0xcc10' not in policy
workflow=(root/'.github/workflows/b5q-runtime.yml').read_text();assert '--changed B5qUsbHost.cpp,LegacyDisplayProbe.cpp,NativeHidInput.cpp --out' in workflow
assert '--source-run 44837528408' in workflow and 'build-data-seed.py'not in workflow and 'build-mesa'not in workflow
assert "if added:run(['xcrun','ar','r'" in (device/'scripts/relink-b5q-peripherals.py').read_text()
recipe=(device/'scripts/b5q_peripherals.py').read_text();assert "'-mkernel'" in recipe
hid=(device/'package/NativeHidInput.cpp').read_text();assert '#if (defined(XNU_TARGET_OS_OSX) && XNU_TARGET_OS_OSX)' in hid and 'static void install(IORegistryEntry *) {}' in hid
sys.path.insert(0,str(device/'scripts'));from b5q_abi import object_symbols
hid_symbols=[n for n,_,_ in object_symbols((w/'objects/NativeHidInput.o').read_bytes())]
for forbidden in ['vtableOf','originalDispatch','kSlotDiversity','kVptrDiscriminator','_ZN4edgeL8dispatch','_ZN4edgeL4call']:
 assert not any(forbidden in n for n in hid_symbols),forbidden
for log in ['target-check.log','full-cross-object-pac.json']:assert json.loads((w/log).read_text())['passed']
assert set(json.loads((w/'target-check.log').read_text())['objects'])=={'B5qUsbHost','LegacyDisplayProbe','NativeHidInput'}
data=json.loads((w/'actual-data-account.json').read_text());assert data['watchdogd_disabled_in_actual_plist'] is True and data['seed_sha256']=='e18547798efd726b0a42dc53cb828888e0772654e29e8c68b3a7c0d083df7948'
allowed={'UniXNU-b5q/package/'+s for s in ['B5qUsbHost.cpp','B5qUsbPolicy.h','LegacyDisplayProbe.cpp','NativeHidInput.cpp']}
for name,digest in json.loads((root/'UniXNU-b5q/reports/runtime-v22.json').read_text())['source_sha256'].items():
 if not name.startswith('UniXNU-b5q/package/') or name in allowed:continue
 assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest,('unexpected production change',name)
assert not re.search(r'0x0*15000000\b',source,re.I)
report={'passed':True,'kernel_args_changes':{'buttons':0,'touch':0,'touch-hid':0,'offline-hid-input':0},'unchanged_ADT_rules':True,'compiled_board_objects':['B5qUsbHost.cpp','LegacyDisplayProbe.cpp','NativeHidInput.cpp'],'all_other_production_sources_unchanged_v22':True,'IRQ_attach_mask_storm_and_disable_contract':True,'DWC3_Device_OTG_events_and_ordered_reset_release':True,'delay_default_seconds':35,'delay_override_max_seconds':300,'monitor_IRQ_and_power_state':True,'macOS_iPadOS_interposer_absent_from_object':True,'C_recipe_mkernel':True,'full_callback_PAC':'PASS actual object producer/consumer pairs','actual_readonly_Data_watchdogd_disabled':True,'hardware_tested':False}
(w/'v23-input-checks.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
