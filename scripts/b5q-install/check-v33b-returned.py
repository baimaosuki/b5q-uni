#!/usr/bin/env python3
"""Accept actual CI payload/objects before creating any final ESP."""
import argparse,hashlib,importlib.util,json,plistlib,subprocess,sys,tempfile,tomllib
from pathlib import Path
R=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(R/'UniXNU/scripts'),str(R/'UniXNU-b5q/scripts'),str(R/'sources/UniXNU/kits/XnuPrelink')]
from unixnu import ramdisk
from kc_image import Image
p=argparse.ArgumentParser();p.add_argument('--ci',type=Path,required=True);p.add_argument('--firmware-receipt',type=Path,required=True);p.add_argument('--fd',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();a.out.mkdir(parents=True,exist_ok=True)
def sha(p):
 with p.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
def load(path):
 s=importlib.util.spec_from_file_location(path.stem,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
checks=[]
def run(name,*command):
 with(a.out/(name+'.log')).open('w')as f:r=subprocess.run(list(map(str,command)),cwd=R,stdout=f,stderr=subprocess.STDOUT)
 if r.returncode:raise SystemExit('FAIL '+name+'; '+str(a.out/(name+'.log')))
 checks.append(name);print('PASS',name,flush=True)
ci=a.ci.resolve();payload=ci/'payload/payload.img';transfer=json.loads((ci/'transfer-index.json').read_text());assert transfer['artifact']['github_digest_verified']
manifest=json.loads((ci/'package.manifest.json').read_text())
for n,rel in [('kernel.macho','kernel/kernel.macho'),('payload.img','payload/payload.img')]:assert dict(bytes=(ci/rel).stat().st_size,sha256=sha(ci/rel))==manifest['outputs'][n]
local=R/'artifacts/b5q-v33b-fix-work'
for name in ['local-gates.json','static-gates.json','failure-gates.json']:assert json.loads((local/name).read_text())['passed'],name
bound=json.loads((local/'local-gates.json').read_text())['source_sha256'];assert all(sha(R/n)==v for n,v in bound.items()),'source changed after local gates'
static=json.loads((local/'static-gates.json').read_text());assert sha(ci/'device-tree/hardware.dtb')==static['DTB_SHA256']
firmware=json.loads(a.firmware_receipt.read_text());assert firmware['passed']and firmware['github_digest_verified']
assert firmware['source_commit']==transfer['commit']and firmware['FD']['sha256']==sha(a.fd),'Firmware/kernel must match same actual CI source and transfer SHA'
fd_bytes=a.fd.read_bytes()
for index in range(12):assert ('b5q low no-map '+str(index)).encode()+b'\0'in fd_bytes,('missing actual FD reservation',index)
from unixnu.boot_template import loader_pe
handoff=loader_pe(fd_bytes,'f8a45ce9-92de-48cc-8e19-e97c28b724a0')
for marker in [b'stock-reserved-guard=before-zero',b'stock-reserved-filter=1']:assert marker in handoff,marker
with tempfile.TemporaryDirectory(prefix='b5q-payload-accept-')as td:
 t=Path(td);fat=payload
 if ramdisk.packed(payload):fat=t/'payload.fat';ramdisk.decode(payload,fat)
 subprocess.run(['fsck.fat','-n',str(fat)],check=True)
 fs=load(R/'scripts/b5q-install/package-usb-dma-esp.py');fs.members(fat,t/'files')
 assets=t/'files/EFI/UniXNU/Payloads';kernel=assets/'kernel.macho';raw=kernel.read_bytes();outer=Image(raw);core=Image(raw,outer.entries['com.apple.kernel'][1]);symbols={n:v for v,names in core.symbols().items()for n in names}
 for n in ['_b5q_launchd_policy_blob','_sm8550_gcc_trigger32','_sheng_cpu_idle_mach','_native_ram_block_volume_seed']:
  assert n in symbols,n
 assert '__ZTV22NativeAdrenoGmuService'in symbols
 helper,=ci.rglob('mmio-helper.json');helper_proof=json.loads(helper.read_text());assert helper_proof['passed']
 assert helper_proof['only_recompiled_member']=='NativeAdrenoGmuService.o'
 assert helper_proof['members_before'].keys()==helper_proof['members_after'].keys()
 assert helper_proof['members_before']['NativeAdrenoGmuService.o']!=helper_proof['members_after']['NativeAdrenoGmuService.o']
 helper_object,=ci.rglob('NativeAdrenoGmuService.o');assert sha(helper_object)==helper_proof['members_after']['NativeAdrenoGmuService.o']
 assert all(v==helper_proof['members_after'][n]for n,v in helper_proof['members_before'].items()if n!='NativeAdrenoGmuService.o')
 for marker in [b'B5qLaunchd: stage=before-launchd',b'B5qKeyStorePlatformGrant',b'b5q-wifi-ready',b'host DMA64=',b'B5qTouch: HID mode=']:
  assert marker in raw,marker
 policy=load(R/'UniXNU-b5q/scripts/update-b5q-launchd-seed.py')
 for labels in policy.policies().values():assert policy.merge(b'',labels)in raw
 adt=fs.adt_nodes((assets/'kernel.macho.adt').read_bytes());assert adt['/chosen/asmb'][2]['lp-sip0']==(2).to_bytes(8,'little')
 for node,values in [('/arm-io/bluetooth',{'transport-encoding':1,'transport-speed':3200000}),('/arm-io/wlan',{})]:
  assert node in adt
  for k,v in values.items():assert adt[node][2][k]==v.to_bytes(4,'little')
 fixups=tomllib.loads((R/'UniXNU-b5q/board.toml').read_text())['payload']['text_fixups'];assert len(fixups)==2
 assert adt['/chosen'][2]['text-fixups']==b''.join(v.encode()+b'\0'for v in fixups)
 meta=json.loads((ci/'runtime/data-seed.json').read_text());assert sha(assets/'scratch-data.img')==meta['sha256']
 addon=load(R/'UniXNU/scripts/addon-add-dir.py');content={n:(mode,body)for n,mode,body in addon.read(assets/'kernel.macho.gpuaddon')}
 job=plistlib.loads(content['Library/LaunchDaemons/org.unixnu.wifi.supplicant.plist'][1]);assert job['RunAtLoad']is False and job['ThrottleInterval']>=60 and job['KeepAlive']=={'PathState':{'/private/var/run/b5q-wifi-ready':True}}
 native=load(R/'UniXNU/drivers/DarwinBoot/Test/packed_ramdisk.py');logical,regions=native.regions((assets/'scratch-data.img').read_bytes());assert logical==4<<30
 seed=t/'seed.apfs'
 with seed.open('wb')as f:
  f.truncate(logical)
  for off,data in regions:f.seek(off);f.write(data)
 run('APFS-existing-policy-account-trust',sys.executable,R/'scripts/b5q-install/verify-apfs-init-readback.py','--image',seed,'--trust-cache',assets/'kernel.macho.trustcache','--out',a.out/'apfs.json')
 run('reserved-RAM-actual-map-options',sys.executable,R/'scripts/b5q-install/check-returned-cache.py','--ci',ci,'--out',a.out/'NormalWB.json')
 run('linked-PAC',sys.executable,R/'scripts/b5q-install/check-stage-linked-PAC.py','--kernel',kernel,'--out',a.out/'linked-PAC.json')
 run('actual-new-core-callbacks-zeroMMIO',sys.executable,R/'scripts/b5q-install/check-stage-returned-objects.py','--ci',ci,'--out',a.out/'board-objects')
 hid,=ci.rglob('NativeHidInput.o')
 run('media-DP-HID-callbacks',sys.executable,R/'scripts/b5q-install/check-media-callback-pac.py','--ci',ci,'--dp','--hid',hid,'--out',a.out/'callback-PAC.json')
 run('wireless-closure',sys.executable,R/'scripts/b5q-install/check-wireless-target-closure.py','--ci',ci,'--esp',fat,'--out',a.out/'wireless-closure.json')
 run('media-closure',sys.executable,R/'scripts/b5q-install/check-media-target-closure.py','--ci',ci,'--esp',fat,'--out',a.out/'media-closure.json')
 run('DP-native-ABI',sys.executable,R/'scripts/b5q-install/check-dp-returned.py','--ci',ci,'--esp',fat,'--fd',a.fd,'--source-root',R/'UniXNU-b5q/package','--out',a.out/'DP')
receipt=dict(passed=True,returned_binaries_verified=True,hardware_verified=False,source_sha256=bound,payload_sha256=sha(payload),kernel_sha256=hashlib.sha256(raw).hexdigest(),DTB_sha256=static['DTB_SHA256'],checks=checks,ci_commit=transfer['commit'],ci_run=transfer['run'],policies={'system':58,'gui':25},readiness_gated_wireless=True,ESP_created=False)
(a.out/'package-ready.json').write_text(json.dumps(receipt,indent=2)+'\n');print('PASS all five offline gates; final ESP assembly now permitted')
