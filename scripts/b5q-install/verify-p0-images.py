#!/usr/bin/env python3
"""Read actual full-build P0 ESP/UEFI bytes and preserve desktop invariants."""
import argparse,ast,hashlib,importlib.util,json,struct,subprocess,sys,tempfile,tomllib
from pathlib import Path
R=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(R/'sources/UniXNU/kits/XnuPrelink'),str(R/'UniXNU-b5q/scripts')]
from kc_image import Image
def load(path):
 spec=importlib.util.spec_from_file_location(path.stem,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def sha(p):
 with p.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
def run(*cmd):subprocess.run(list(map(str,cmd)),check=True)
def main():
 p=argparse.ArgumentParser(description=__doc__)
 for key in ['esp','ci','fd','out']:p.add_argument('--'+key,type=Path,required=True)
 p.add_argument('--board',type=Path,default=R/'UniXNU-b5q/board.toml',help='Source configuration for this exact image revision')
 p.add_argument('--wireless',action='store_true',help='Also verify P2/P3 runtime against the accepted GPU addon')
 p.add_argument('--media',action='store_true',help='Verify P4 menu, media HAL, firmware and ADT slots')
 p.add_argument('--v33b',action='store_true',help='Verify repaired icon policy, readiness-gated wireless job and transport nodes')
 p.add_argument('--dp',action='store_true',help='Verify final P5 native display, GOP tail handoff and menu isolation')
 a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
 fs=load(R/'scripts/b5q-install/package-usb-dma-esp.py');fs.image_format(a.esp)
 run('fsck.fat','-n',a.esp)
 run(sys.executable,R/'scripts/b5q-install/verify-esp-log.py','--esp',a.esp,'--out',a.out/'log-allocation.json')
 run(sys.executable,R/'scripts/b5q-install/check-usb-dma-fv.py','--fd',a.fd,'--out',a.out/'firmware-FV.json')
 meta,=a.ci.rglob('kernel.json');kmeta=json.loads(meta.read_text())
 assert kmeta['mapping_complete'] and not kmeta['missing'] and not kmeta['stubbed'] and not kmeta['allow_missing']
 package,=a.ci.rglob('batch2-package.json');expected=json.loads(package.read_text())
 with tempfile.TemporaryDirectory(prefix='b5q-p0-readback-')as td:
  t=Path(td);members=fs.members(a.esp,t/'files')
  assert members==expected['members'] and sha(a.esp)==expected['esp']['sha256']
  boot=t/'files/EFI/UniXNU';assets=boot/'Payloads';board=tomllib.loads(a.board.read_text())
  menu=tomllib.loads((boot/'unixnu.toml').read_text());entries={e['id']:e for e in menu['entry']if e['type']=='xnu'}
  assert menu['boot']['default']=='xnu' and set(entries)==({'xnu','daily','safe','ram-fallback'}if a.media else{'xnu','ram-fallback'})
  if a.media:
   sys.path.insert(0,str(R/'UniXNU-b5q/scripts'));from b5q_menu import profiles as menu_profiles
   assert list(entries.values())==menu_profiles(board['payload']['kernel_args'])
  if a.dp:
   assert a.media
   for name,entry in entries.items():assert ('b5q-dp=1'if name=='xnu'else'b5q-dp=0')in entry['args'].split()
  assert entries['xnu']['args']==' '.join(board['payload']['kernel_args']) and len(entries['xnu']['args'].encode())<=1023
  assert 'b5q-data-ufs=2' in entries['xnu']['args'].split() and 'initrd' not in entries['xnu']
  assert 'offline-mobile-graphics-client' not in entries['xnu']['args']
  assert 'b5q-data-ufs=0' in entries['ram-fallback']['args'].split()
  assert entries['ram-fallback']['initrd']=='Payloads/scratch-data.img'
  profiles={}
  for name,entry in entries.items():
   kernel=boot/entry['path'];nodes=fs.adt_nodes(kernel.with_suffix('.macho.adt').read_bytes());chosen=nodes['/chosen'][2]
   assert nodes['/chosen/asmb'][2]['lp-sip0']==struct.pack('<Q',2)
   assert chosen['darwinboot-memory-size']==struct.pack('<Q',(4 if name=='ram-fallback' else 6)<<30)
   assert chosen['text-fixups']==b''.join(v.encode()+b'\0'for v in board['payload']['text_fixups']) and len(board['payload']['text_fixups'])==2
   assert sum('cluster-type'in v[2]for k,v in nodes.items()if k.startswith('/cpus/'))==8
   maps=nodes['/chosen/memory-map'][2]
   if name!='ram-fallback':
    assert 'RAMDisk'not in maps and 'PackedRAMDisk'not in maps
    assert len(chosen['darwinboot-memory-excluded'])==128*16 and len(chosen['darwinboot-memory-outside'])==16*16
   else:assert 'PackedRAMDisk'in maps and 'darwinboot-memory-outside'not in chosen
   if a.media:
    assert chosen['b5q-feature-mask']==struct.pack('<I',0 if name=='ram-fallback' else 61)
    for subsystem in ['audio','video']:
     assert chosen['b5q-'+subsystem+'-dma-ready']==bytes(4)
     assert chosen['b5q-'+subsystem+'-dma-state']==bytes(104)
   if a.dp:
    assert chosen['b5q-dp-dma-ready']==bytes(4)and chosen['b5q-dp-dma-state']==bytes(80)
   from b5q_gpu_adt import verify as verify_gpu_firmware
   verify_gpu_firmware(chosen)
   profiles[name]=dict(kernel_sha256=sha(kernel),args_bytes=len(entry['args'].encode()),lp_sip0_hex=chosen.get('lp-sip0',nodes['/chosen/asmb'][2]['lp-sip0']).hex(),RAM_seed_loaded='initrd'in entry)
  assert len({v['kernel_sha256']for v in profiles.values()})==1
  kernel=assets/'kernel.macho';raw=kernel.read_bytes();outer=Image(raw);core=Image(raw,outer.entries['com.apple.kernel'][1]);symbols={n:v for v,names in core.symbols().items()for n in names}
  required=['_native_ram_block_provider_seed','_native_ram_block_volume_seed','_native_ram_block_volume_device','_b5q_power_start','_sheng_cpu_idle_mach','_ml_outside_memory_pages','_ml_outside_memory_refused','_native_touch_recovered','_native_touch_set_sink']
  assert all(n in symbols for n in required),[n for n in required if n not in symbols]
  if a.dp:
   required_dp=['_b5q_dp_link_update','_b5q_dp_link_stop','_b5q_dp_irq_start','_b5q_dp_irq_stop',
    '_b5q_dp_display_create','_b5q_dp_display_disconnect','_b5q_dp_display_frame','__ZTV12B5qDpDisplay']
   assert all(n in symbols for n in required_dp),[n for n in required_dp if n not in symbols]
   for marker in [b'scanout=online',b'b5q-dp-dma-state',b'B5qDP: EDID pool-filter',b'B5qDP: vsync frame=',b'scanout=online']:
    assert marker in raw,marker
   assert b'scanout=unattached'not in raw
  assert not any('B5qTouchPointer'in n for n in symbols)
  assert not any('lidWorker'in n or 'backlight_lid'in n or 'dp_lid_online'in n for n in symbols)
  assert b'B5qLid:'not in raw and b'clamshell-sleep-disabled='not in raw
  for marker in [b'B5qTouch: mode=%02x',b'c2=%u release_all=%u hid=%u',b'stage=release-all',b'report-recovery',b'FUA-still-accepted',b'outside adopted=',b'4.5 GiB',b'TOP6..10',b'B5qPower:',b'persistent Data media/UUID/BSD readiness timeout or duplicate UUID']:
   assert marker in raw,marker
  for marker in [b'policy=firmware-negotiated',b'external-hub=%u',b'QMP orientation=unknown',b'qcom-dwc3: device dctl=']:
   assert marker in raw,marker
  run(sys.executable,R/'scripts/b5q-install/check-stage-linked-PAC.py','--kernel',kernel,'--out',a.out/'linked-PAC.json')
  if a.v33b:
   seed_meta,=a.ci.rglob('runtime/data-seed.json')
   assert sha(assets/'scratch-data.img')==json.loads(seed_meta.read_text())['sha256']
   for name,entry in entries.items():
    nodes=fs.adt_nodes((boot/entry['path']).with_suffix('.macho.adt').read_bytes())
    assert '/arm-io/wlan'in nodes
    assert nodes['/arm-io/bluetooth'][2]['transport-encoding']==struct.pack('<I',1)
    assert nodes['/arm-io/bluetooth'][2]['transport-speed']==struct.pack('<I',3200000)
    assert 'vsync-fixed=1'in entry['args'].split()
   assert '_b5q_launchd_policy_blob'in symbols
   policy=load(R/'UniXNU-b5q/scripts/update-b5q-launchd-seed.py')
   for labels in policy.policies().values():assert policy.merge(b'',labels)in raw
   for marker in [b'B5qLaunchd: stage=before-launchd',b'B5qKeyStorePlatformGrant',b'NativeSandboxGrantProcess',b'b5q-wifi-ready',b'host DMA64=']:
    assert marker in raw,marker
  else:assert sha(assets/'scratch-data.img')=='d2e32a5f7dd37807a816d857d8b62eba41615c5da9ac335c2322e3c7a35ffc70' 
  if a.wireless or a.media:
   from uuid import UUID
   import plistlib
   addon=load(R/'UniXNU/scripts/addon-add-dir.py')
   actual_entries=addon.read(assets/'kernel.macho.gpuaddon')
   content={name:(mode,body)for name,mode,body in actual_entries}
   assert len(content)==len(actual_entries),'Duplicate addon paths'
   previous=t/'old-addon'
   run('mcopy','-i',R/'artifacts/b5q-p1-work/ci45167257160/esp.img','::/EFI/UniXNU/Payloads/kernel.macho.gpuaddon',previous)
   preserved=addon.read(previous)
   assert all(content.get(name)==(mode,body)for name,mode,body in preserved),'Baseline addon changed'
   funcs=[n for n in ast.parse((R/'scripts/b5q-install/verify-mount-runtime.py').read_text()).body if isinstance(n,ast.FunctionDef)and n.name in ('modules','codesign')]
   helpers=dict(struct=struct,hashlib=hashlib)
   exec(compile(ast.Module(body=funcs,type_ignores=[]),'signature-verifier','exec'),helpers)
   modules=helpers['modules']((assets/'kernel.macho.trustcache').read_bytes())
   trusted={m[i:i+20]for m in modules for i in range(24,len(m),24)}
   signed={}
   for name,(mode,body)in content.items():
    if body[:4]==b'\xcf\xfa\xed\xfe':
     hashes=helpers['codesign'](body);assert all(h in trusted for h in hashes),name
     signed[name]=[h.hex()for h in hashes]
   for name in ['sbin/BlueTool','sbin/bluetoothd','lib/QcaBTType0.dylib','bin/unixnu-wpa_supplicant']:assert name in signed,name
   marker=json.loads(content['sbin/QcaBluetooth.runtime'][1])
   assert marker['native_input_sha256']=='82e244d5dcafbc150e820416ac7037debc9def106eae043ee51ed4e2c84e7721'
   manifest=json.loads((R/'UniXNU-b5q/reports/wcn-stock-firmware.json').read_text())
   for key,item in manifest['files'].items():
    radio,name=key.split('/',1);prefix='firmware/qca'if radio=='bluetooth'else'firmware/ath11k/WCN6855/hw2.0'
    mode,body=content[prefix+'/'+name]
    assert mode==0o644 and len(body)==item['bytes']and hashlib.sha256(body).hexdigest()==item['sha256'],key
   job=plistlib.loads(content['Library/LaunchDaemons/org.unixnu.wifi.supplicant.plist'][1])
   assert job['Label']=='org.unixnu.wifi.supplicant'and job['UserName']=='root'
   if a.v33b:
    assert job['KeepAlive']=={'PathState':{'/private/var/run/b5q-wifi-ready':True}}
    assert job['RunAtLoad']is False and job['ThrottleInterval']>=60
   else:assert job['KeepAlive']is True
   assert job['ProgramArguments'][0]=='/private/var/ngpu/bin/unixnu-wpa_supplicant'
   daemon=Image(content['sbin/bluetoothd'][1])
   patch=json.loads((R/'artifacts/b5q-p2-work/native-macos27.json').read_text())['patch']
   assert daemon.data.count(UUID(patch['input_uuid']).bytes)==1
   for row in patch['patches']:
    words=row['patched'];assert daemon.read(int(row['address'],16),len(words)*4)==struct.pack('<'+'I'*len(words),*[int(v,16)for v in words]),row['address']
   required_wireless=['_b5q_wifi_probe','_b5q_bluetooth_probe','_nw_wifi_start','_b5q_wcn_power_get','_nwk_b5q_ath11k_pci_init']
   assert all(n in symbols for n in required_wireless),[n for n in required_wireless if n not in symbols]
   for marker in [b'B5qWireless: bluetooth library=',b'B5qWireless: wifi launchd=',b'B5qWifi',b'B5qBluetooth: transport=FIFO']:assert marker in raw,marker
   for name,entry in entries.items():
    assert ({'wifi=0','bluetooth=0','usb=0'}if a.media and name in ('safe','ram-fallback')else{'wifi=5','bluetooth=1'})<=set(entry['args'].split())
   for entry in entries.values():
    chosen=fs.adt_nodes((boot/entry['path']).with_suffix('.macho.adt').read_bytes())['/chosen'][2]
    assert chosen['b5q-pcie-dma-ready']==bytes(4)and chosen['b5q-pcie-dma-state']==bytes(88)
   if a.media:
    # Read the build's producer manifest, never an acceptance report from an
    # earlier run of this verifier in the same downloaded artifact tree.
    media_path,=a.ci.rglob('runtime/media-runtime.json');media=json.loads(media_path.read_text())
    assert media['passed']
    counts=(media['preserved_addon_entries'],media['new_addon_entries'])
    if counts==(57,0):
     # An already complete media addon is idempotently reused. Verify every
     # actual uploaded reuse input byte, not just its self-declared counts.
     reused,=a.ci.rglob('gpu-addon.bin')
     assert sha(reused)==media['addon_sha256']
     prior=addon.read(reused)
     assert len(prior)==57 and len(content)==57
     assert all(content.get(n)==(m,b)for n,m,b in prior)
    else:assert counts==(50,7)
    assert len(content)==57
    assert sha(assets/'kernel.macho.gpuaddon')==media['addon_sha256']
    assert sha(assets/'kernel.macho.trustcache')==media['trust_sha256']
    previous_wireless=t/'p2p3-addon'
    run('mcopy','-i',R/'artifacts/b5q-esp-p2-p3/esp.img','::/EFI/UniXNU/Payloads/kernel.macho.gpuaddon',previous_wireless)
    previous_content=addon.read(previous_wireless)
    assert len(previous_content)==50
    changes=[n for n,m,b in previous_content if content.get(n)!=(m,b)]
    assert changes==(['Library/LaunchDaemons/org.unixnu.wifi.supplicant.plist']if a.v33b else[]),changes
    stock=json.loads((R/'UniXNU-b5q/reports/p4-runtime-firmware.json').read_text())
    assert media['firmware']==stock['files']
    for name,item in stock['files'].items():
     mode,body=content['firmware/qcom/sm8550/b5q/'+name]
     assert mode==0o644 and len(body)==item['bytes']and hashlib.sha256(body).hexdigest()==item['sha256']
    hal='Library/Audio/Plug-Ins/HAL/B5qAudio.driver/'
    for name,digest in media['audio']['files'].items():
     mode,body=content[hal+name];assert hashlib.sha256(body).hexdigest()==digest
    assert media['audio']['cdhash']in signed[hal+'Contents/MacOS/B5qAudio']
    required_media=['_b5q_daily_probe','_b5q_backlight_probe','_sheng_audio_probe','_sheng_video_probe','_sheng_adsp_probe']
    assert all(n in symbols for n in required_media),[n for n in required_media if n not in symbols]
    for marker in [b'B5qBattery:',b'B5qBacklight:',b'B5qAudio',b'B5qVideo:']:
     assert marker in raw,marker
    media_result=dict(passed=True,previous_wireless_entries_preserved=50,original_firmware_files=stock['files'],audio_cdhash=media['audio']['cdhash'],ADT_media_slots_zero=True,menu_profile_selection=True,hardware_verified=False)
    (a.out/'media-runtime.json').write_text(json.dumps(media_result,indent=2)+'\n')
   wireless_result=dict(passed=True,baseline_addon_files_unchanged=len(preserved),new_signed_and_trusted=signed,stock_firmware_files=len(manifest['files']),native_bluetoothd_patch_sites=len(patch['patches']),PCIe_ADT_slots_initially_zero=True,hardware_verified=False)
   (a.out/'wireless-runtime.json').write_text(json.dumps(wireless_result,indent=2)+'\n')
  else:assert sha(assets/'kernel.macho.gpuaddon')=='b68e1164f7dd0ff822f20e116e97adc4606926a4204fc25eaa5241c2a966d82d'
  sys.path.insert(0,str(R/'UniXNU/scripts'));from unixnu.boot_template import loader_pe
  assert (boot/'Drivers/DarwinBoot.efi').read_bytes()==loader_pe(a.fd.read_bytes(),'1b64af87-8415-4b57-9b16-680d70913b9f')
  builtin=json.loads((R/'UniXNU-b5q/package/B5qBootPolicy.c').read_text().splitlines()[-1].rstrip(';'))
  assert core.read(symbols['_PE_builtin_boot_args'],len(builtin)+1)==builtin.encode()+b'\0' and 'endpointsecurity'not in builtin
  run(sys.executable,R/'tests/b5q-ufs/test-post-seal.py','--kernel',kernel,'--out',a.out/'POST.json')
  sys.path.insert(0,str(R/'sources/UniXNU/drivers/DarwinBoot/Test'));from packed_ramdisk import regions
  size,extents=regions((assets/'scratch-data.img').read_bytes());assert size==4<<30
  recovery=t/'recovery.img'
  with recovery.open('wb')as stream:
   stream.truncate(size)
   for offset,body in extents:stream.seek(offset);stream.write(body)
  run(sys.executable,R/'scripts/b5q-install/verify-apfs-init-readback.py','--image',recovery,'--trust-cache',assets/'kernel.macho.trustcache','--out',a.out/'APFS.json')
  result=dict(passed=True,stage='P5'if a.dp else'P4'if a.media else'P2+P3'if a.wireless else'P0+P1',ESP=dict(bytes=a.esp.stat().st_size,sha256=sha(a.esp)),FD=dict(bytes=a.fd.stat().st_size,sha256=sha(a.fd)),profiles=profiles,required_symbols={n:hex(symbols[n])for n in required},FAT_members=len(members),all_real_link_inputs_resolved=True,Data_GPU_unchanged=True,loader_matches_actual_rebuilt_FD=True,hardware_qualification='HOST_VERIFIED_PENDING_HARDWARE',physical_Data_accessed=False)
  (a.out/'images.json').write_text(json.dumps(result,indent=2)+'\n')
  print(json.dumps(result,indent=2))
if __name__=='__main__':main()
