#!/usr/bin/env python3
"""Required physical-RAM, real ADT, sheng diff and launch-policy gates."""
import argparse,hashlib,importlib.util,json,re,subprocess,sys,tomllib
from pathlib import Path
R=Path(__file__).resolve().parents[2];W=R/'artifacts/b5q-v33b-fix-work';W.mkdir(exist_ok=True)
sys.path.insert(0,str(R/'UniXNU/scripts'))
from unixnu.cli import parser
from unixnu.config import Context
from unixnu import profiles
from unixnu.devicetree import generate,read_fdt
p=argparse.ArgumentParser();p.add_argument('--out',type=Path,default=W/'static-gates.json');a=p.parse_args()
def load(path):
 s=importlib.util.spec_from_file_location(path.stem,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
ctx=Context(parser().parse_args(['tree','--device',str(R/'UniXNU-b5q'),'--os','macos-27.3-26C5035r']))
dtb=W/'hardware.dtb';command=['dtc','-q','-I','dts','-O','dtb','-o',str(dtb)]
for path in ctx.board['device_tree']['include_dirs']:command+=['-i',str(profiles.resolve_path(ctx,path))]
subprocess.run([*command,str(profiles.resolve_path(ctx,ctx.board['device_tree']['source']))],check=True)
fs=load(R/'scripts/b5q-install/package-usb-dma-esp.py');variants={}
for recovery in [False,True]:
 adt=W/('recovery.adt'if recovery else'normal.adt');adt.write_bytes(generate(dtb,ctx.board,unique_chip_id='123456789abcdef',data=recovery,trust=True,addon=True,root_policies=True));variants[recovery]=fs.adt_nodes(adt.read_bytes())
nodes=variants[False];chosen=nodes['/chosen'][2]
assert nodes['/arm-io/bluetooth'][2]['transport-encoding']==(1).to_bytes(4,'little')
assert nodes['/arm-io/bluetooth'][2]['transport-speed']==(3200000).to_bytes(4,'little')
assert '/arm-io/wlan'in nodes
files=sorted(p for p in (R/'UniXNU-b5q/package').rglob('*')if p.suffix in ['.c','.h','.cpp'])
shared_roots=[R/'UniXNU/drivers'/n for n in ['ArmCpu','ArmDTPlatform','AppleKeyStoreState','GopFramebuffer','Adreno740','AdrenoMetal','RamBlock','SoftwareAES']]
shared_roots+=[R/'sources/UniXNU-sm8550-common/kits/Sm8550Platform',R/'artifacts/b5q-p4-work/target/generated-adsp',R/'artifacts/b5q-p4-work/target/generated-audio-service',R/'artifacts/b5q-p4-work/target/generated-video']
# This legacy generic GMU IOService is not selected by the b5q archive;
# its only implicit-cache map is a register window (never memset RAM).
# Verify its class remains absent from the returned native kernel as well.
legacy_unselected=R/'UniXNU/drivers/Adreno740/NativeAdrenoGmuService.cpp'
files=sorted(set(files+[p for d in shared_roots for p in d.rglob('*')if p.suffix in ['.c','.cpp','.h']and p!=legacy_unselected]))
# Inventory every device repository mapping. MMIO defaults remain inhibit;
# reserved pools must be explicit Normal WB. No default/zero cache accepted.
mappings=[];lookups=[];chosen_names=set();optional={
 'display-scale':'Optional UI scale: guarded read; loader runtime display geometry supplies default.',
 'display-rotation':'Optional rotation: guarded read; absent means0.',
 'ephemeral-storage':'Optional keystore stand-in admission property: absent refuses ephemeral service.',
}
for f in files:
 text=f.read_text()
 assert 'kIOMapDefaultCache'not in text,(f,'ambiguous cache')
 for m in re.finditer(r'->map\(([^;]+)',text):
  expr=m.group(1);line=text.count('\n',0,m.start())+1
  if 'kIOMapAnywhere'in expr:
   assert any(k in expr.replace(' ','').replace('\n','') for k in ['kIOMapInhibitCache','kIOMapCopybackCache','kIOMapWriteCombineCache','|cache']),(f,line,expr)
   mappings.append(dict(path=str(f),line=line,expression=expr))
 for m in re.finditer(r'IORegistryEntry::fromPath\s*\(\s*"([^"\n]+)"\s*,\s*gIODTPlane',text):
  name=m.group(1);assert name in nodes,(f,name,'missing actual ADT node');lookups.append(dict(source=str(f),path=name,line=text.count('\n',0,m.start())+1,actual_ADT=True))
 # Only accesses through the DT chosen handle, not unrelated media/service
 # properties such as UUID/Built-In/idVendor. Include typed readChosen calls.
 for m in re.finditer(r'(?:chosen|unitScaleChosen)->getProperty\("([^"\n]+)"|readChosen\(chosen,\s*"([^"\n]+)"',text):chosen_names.add(m.group(1)or m.group(2))
for name in chosen_names:assert name in chosen or name in optional,(name,'chosen property missing and not reviewed optional')
for name in ['B5qAudioDma.cpp','B5qVideoMemory.cpp']:
 assert 'kIOMapCopybackCache'in (R/'UniXNU-b5q/package'/name).read_text()
assert 'dma.open(dmaState.poolBase,dmaState.poolBytes,kIOMapCopybackCache)'in (R/'UniXNU-b5q/package/B5qWifiBoard.cpp').read_text()
assert 'pool.open(dma.PoolBase,unsigned(dma.PoolBytes),kIOMapCopybackCache)'in (R/'UniXNU-b5q/package/B5qDpLink.cpp').read_text()
# Automatic source diff against the *macOS* override, never iPadOS args.
sheng=tomllib.loads((R/'sources/UniXNU-sheng/board.toml').read_text());sargs=sheng['os_overrides']['macos-27.3-26C5035r']['payload']['kernel_args'];bargs=ctx.board['payload']['kernel_args'];bkeys={x.split('=')[0]for x in bargs}
resolved={
 'native-source-storage':'b5q authenticated root/Data providers replace sheng storage.',
 'native-ufs-root':'b5q warm-root transport selected by b5q-ufs-root.',
 'offline-mobile-graphics-client':'Removed deliberately: IOUserClient2022 old externalMethod panics; development probe not display registration.',
 'keyboard':'No Xiaomi keyboard; built-in buttons/touch and USB native HID are selected.',
 'log':'No Xiaomi diagnostic UI; B5QLOG2 is selected.',
 'data-persist':'b5q-data-ufs=2 validated B5QDATA1 userdata provider.',
 'backlight':'Feature ADT/mask63 selects B5qBacklight in full profile; daily/safe isolate via b5q-f=0.',
 'dpu-scanout':'Samsung primary GOP backend uses verified copy/Metal path; sheng direct-scanout allocation not authorized.',
 'disable-watchdogd':'Root-owned binary disabled.plist contains watchdogd and is migrated before launchd.',
 'adsp':'Feature ADT/mask63 selects the Samsung ADSP service.',
 'audio':'Feature ADT/mask63 selects Samsung AudioReach/TFA9878; sheng audio mode12 has different board routing.',
 'autoreset':'Development timeout deliberately absent; never reset a running desktop at7200s.',
 'uefi-watchdog':'No boot menu watchdog deadline requested; preserve accepted firmware baseline.',
 'diag':'B5QLOG2/ProcTop hardware logs replace Xiaomi diagnostic UI.',
 'diag-export':'No Xiaomi diagnostic control endpoint7140.',
 'gpu-trace':'Existing bounded GPU stage rows, no extra tracing/overhead requested.',
 'log-gpu':'Existing bounded GPU stage rows; verbosity not required for runtime.',
 'log-video':'B5qVideo explicit stage/failure output already present.',
 'log-bluetooth':'B5qBluetooth failure output unconditional; extra full-HCI buffer optional.',
 'build-tag':'Development source metadata identifies CI; do not copy sheng tag.',
}
missing=[]
for entry in sargs:
 key=entry.split('=')[0]
 if key not in bkeys:assert key in resolved,(key,'unreviewed sheng omission');missing.append(dict(key=key,resolution=resolved[key]))
assert {'bluetooth','wifi','vsync-fixed','usb','offline-hid-input'}<=bkeys
svalues={x.partition('=')[0]:x.partition('=')[2]for x in sargs};bvalues={x.partition('=')[0]:x.partition('=')[2]for x in bargs}
value_changes={k:(svalues[k],bvalues[k])for k in svalues.keys()&bvalues.keys()if svalues[k]!=bvalues[k]}
assert value_changes=={'touch':('4','1'),'vsync':('120','60')},value_changes
value_resolutions={'touch':'Samsung S3916A touch=1 selects IRQ GPIO-I2C; Xiaomi Novatek touch=4 prohibited.',
 'vsync':'b5q validated60Hz GOP mode, explicit vsync-fixed=1; do not copy Xiaomi120Hz panel rate.'}
component_omissions=sorted(set(sheng['os_overrides']['macos-27.3-26C5035r']['components']['include'])-set(ctx.board['components']['include']))
component_resolutions={'ShengPreflight':'Forbidden Xiaomi fastboot/preflight; b5q validated physical ESP/UEFI.', 'ShengUfs':'Samsung B5qUfs/B5qDataBlock authenticated exact geometry; no Xiaomi storage policy.'}
assert all(v in component_resolutions for v in component_omissions),component_omissions
sroot=read_fdt(subprocess.check_output(['dtc','-q','-I','dts','-O','dtb','-i',str(R/'sources/UniXNU-sm8550-common/dts'),str(R/'sources/UniXNU-sheng/dts/sheng.dts')]))
broot=read_fdt(dtb.read_bytes());root_delta=sorted(set(n.name for n in sroot.children)-set(n.name for n in broot.children))
assert not root_delta,root_delta
policy=load(R/'UniXNU-b5q/scripts/update-b5q-launchd-seed.py');lists=policy.policies();assert all('com.apple.iconservices.iconservicesagent'not in v for v in lists.values())
assert (len(lists['disabled.plist']),len(lists['disabled.501.plist']))==(58,25)
assert 'com.apple.watchdogd'in lists['disabled.plist']
for banned in ['com.apple.WindowServer','com.apple.loginwindow','com.apple.Dock','com.apple.finder']:
 assert all(banned not in v for v in lists.values())
# The original macOS override explicitly removes iPadOS launchd environment;
# record this fact instead of copying iPad-only behavior into this board.
assert 'payload.runtime.launchd_job_environment'in sheng['os_overrides']['macos-27.3-26C5035r']['remove']
sys.path.insert(0,str(R/'UniXNU-b5q/scripts'));from b5q_menu import profiles as menus
lengths={x['id']:len(x['args'].encode())for x in menus(bargs)};assert max(lengths.values())<=1023
report=dict(passed=True,hardware_verified=False,memory_mappings=mappings,ADT_lookups=lookups,chosen_properties={v:('present'if v in chosen else optional[v])for v in sorted(chosen_names)},
 DTB_SHA256=hashlib.sha256(dtb.read_bytes()).hexdigest(),ADT_SHA256={str(k):hashlib.sha256((W/('recovery.adt'if k else'normal.adt')).read_bytes()).hexdigest()for k in variants},
 sheng_revision=subprocess.check_output(['git','-C',str(R/'sources/UniXNU-sheng'),'rev-parse','HEAD'],text=True).strip(),
 sheng_shared_value_changes={k:dict(sheng=v[0],b5q=v[1],resolution=value_resolutions[k])for k,v in value_changes.items()},unselected_MMIO_source=dict(path=str(legacy_unselected),sha256=hashlib.sha256(legacy_unselected.read_bytes()).hexdigest(),reason='Generic GMU register-only service not selected by b5q; returned kernel class-absence checked'),source_sha256={str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest()for p in files},sheng_missing_args_resolved=missing,missing_root_nodes=root_delta,component_omissions={v:component_resolutions[v]for v in component_omissions},policy_counts={k:len(v)for k,v in lists.items()},iconservices_enabled=True,
 sheng_macOS_removes_ipad_launchd_environment=True,menu_args_bytes=lengths,scope='Actual compiled DTB and generated ADT, every board source map/fromPath/chosen inventory; selected component MMIO sources audited separately by target-object gates')
a.out.write_text(json.dumps(report,indent=2)+'\n');print('PASS explicit cache/source scan, realDTB/ADT lookups, macOSshengdiff,iconservices58/25,allmenu1024Bbounds')
