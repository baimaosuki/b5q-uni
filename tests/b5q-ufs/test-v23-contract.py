from pathlib import Path
import hashlib,json,re,tomllib
root=Path(__file__).resolve().parents[2];w=root/'artifacts/b5q-runtime-v23-work';device=root/'UniXNU-b5q'
board=tomllib.loads((device/'board.toml').read_text());old=json.loads((root/'artifacts/b5q-esp-runtime-v22/package.manifest.json').read_text())
assert ' '.join(board['payload']['kernel_args'])==old['kernel_command_line']
rules=json.loads((root/'artifacts/b5q-runtime-v20-work/seven-rule-check.json').read_text())['rules']
assert board['payload']['text_fixups']==[f"dyld_shared_cache_arm64e.03,{r['offset']},{r['original']},{r['replacement']}"for r in rules]
source=(device/'package/B5qUsbHost.cpp').read_text();start=source.index(' IOReturn registerInterrupt(');end=source.index(' IOReturn unregisterInterrupt(',start);register=source[start:end]
assert register.index('owner=target;context=ref;action=handler;')<register.index('armcpu_spi_attach(')<register.index('const int masked=armcpu_spi_mask(')
assert 'if(!__atomic_load_n(&self->enabled' in source and '__atomic_store_n(&self->stormed,true' in source
assert 'if(__atomic_load_n(&stormed' in source and '__atomic_store_n(&unhandledCount,0u' in source
worker=source[source.index('static void worker('):];assert worker.index('IOSleep(delaySec*1000)')<worker.index('core.open(')
assert 'unsigned delaySec=15' in worker and 'if(delaySec>300)delaySec=300' in worker
assert 'irq=%u un=%u storm=%u pwr=%lu' in source and 'getPowerState()' in source
for off in ['0xc40c','0xc708']:assert off in source
policy=(device/'package/B5qUsbPolicy.h').read_text()
for text in ['write(0xc708,0)','write(0xc408,size|(1u<<31))','write(0xc40c,count&0xffffu)','(hardware&3u)==2u','write(0xcc0c,0)','read(0xcc08,pending)','write(0xcc08,pending)','delay(20000)']:assert text in policy,text
assert 'write(0xcc10' not in policy
workflow=(root/'.github/workflows/b5q-runtime.yml').read_text();assert '--changed B5qUsbHost.cpp --out' in workflow
assert '--source-run 44837528408' in workflow and 'build-data-seed.py'not in workflow and 'build-mesa'not in workflow
for log in ['target-check.log','callback-pac.json']:assert json.loads((w/log).read_text())['passed']
assert list(json.loads((w/'target-check.log').read_text())['objects'])==['B5qUsbHost']
for name,digest in json.loads((root/'UniXNU-b5q/reports/runtime-v22.json').read_text())['source_sha256'].items():
 if name in ['UniXNU-b5q/package/B5qUsbHost.cpp','UniXNU-b5q/package/B5qUsbPolicy.h']:continue
 assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest,('non-USB production change',name)
assert not re.search(r'0x0*15000000\b',source,re.I)
report={'passed':True,'unchanged_board_args_and_ADT_rules':True,'compiled_board_objects':['B5qUsbHost.cpp'],'all_other_production_sources_unchanged_v22':True,'IRQ_attach_mask_storm_and_disable_contract':True,'DWC3_Device_OTG_events_and_20ms_reset':True,'delay_default_seconds':15,'delay_override_max_seconds':300,'monitor_IRQ_and_power_state':True,'callback_PAC':'USB->ArmCpu andall6GMU_IO_Services fields match actualobjects','hardware_tested':False}
(w/'v23-input-checks.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
