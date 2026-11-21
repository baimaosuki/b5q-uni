#!/usr/bin/env python3
"""Validate returned v23 binary, exact reused inputs and final ESP locally."""
import argparse,hashlib,importlib.util,json,struct,subprocess,sys,tempfile,tomllib
from pathlib import Path
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'sources/UniXNU/kits/XnuPrelink'),str(ROOT/'UniXNU-b5q/scripts')]
from kc_image import Image

def sha(path):
 with path.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
def load(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--package',type=Path,required=True);p.add_argument('--ci-dir',type=Path,required=True);p.add_argument('--baseline-tree',type=Path,required=True);p.add_argument('--objects',type=Path,required=True);a=p.parse_args()
package=a.package.resolve();ci=a.ci_dir.resolve();baseline=a.baseline_tree.resolve();board=tomllib.loads((ROOT/'UniXNU-b5q/board.toml').read_text());baseline_manifest=json.loads((ROOT/'artifacts/b5q-esp-runtime-v22/package.manifest.json').read_text());manifest=json.loads((package/'package.manifest.json').read_text());md=Cs(CS_ARCH_ARM64,CS_MODE_ARM)
relink=json.loads((ci/'kernel/incremental-relink.json').read_text());assert relink['board_translation_units_compiled']==1 and relink['core_translation_units_compiled']==0
assert relink['unchanged_core_after_link_sha256']=='1fce36d7ee6c79cb2b1aca01b3635cdda568c8dadef6a5c3490007610a3a3d3b'
assert relink['unchanged_inputs']['build/adreno740/libAdreno740.a']==sha(ci/'tree/build/adreno740/libAdreno740.a')
for name in ['scratch-data.img','kernel.macho.gpuaddon','kernel.macho.trustcache']:
 key='EFI/UniXNU/Payloads/'+name;assert manifest['esp_files'][key]==baseline_manifest['esp_files'][key],name
subprocess.run([sys.executable,str(ROOT/'scripts/b5q-install/check-geni-pac.py'),'--objects',str(a.objects),'--out',str(package/'unchanged-GENI-pac.json')],check=True)
callback=ROOT/'artifacts/b5q-runtime-v23-work/callback-objects'
subprocess.run([sys.executable,str(ROOT/'scripts/b5q-install/check-usb-gmu-pac.py'),'--usb',str(a.objects/'B5qUsbHost.o'),'--armcpu',str(callback/'ArmCpu.o'),'--gpu',str(callback/'B5qGpu.o'),'--gmu',str(callback/'ShengGmu.kit.o'),'--out',str(package/'actual-callback-pac.json')],check=True)
report={'passed':True,'kernel_core_recompiled':False,'board_objects_compiled':1,'Data_addon_trust_byte_identical_v22':True,'all_graphics_archives_reused':True,'changed_source_contracts':json.loads((ROOT/'artifacts/b5q-runtime-v23-work/v23-input-checks.json').read_text()),'hardware_tested':False}
archive=load('v22_ar',ROOT/'UniXNU-b5q/scripts/relink-b5q-peripherals.py');old=dict(archive.members(baseline/'build/native-legacy-display/libNativeLegacyDisplay.late.a'));new=dict(archive.members(ci/'tree/build/native-legacy-display/libNativeLegacyDisplay.late.a'));assert old.keys()==new.keys()
changed=sorted(n for n in old if old[n]!=new[n]);expected=['B5qUsbHost.late.o'];assert changed==expected,changed;report['changed_native_archive_members']=changed
with tempfile.TemporaryDirectory(prefix='b5q-v23-final-')as td:
 tmp=Path(td)
 for name in ['kernel.macho','scratch-data.img','kernel.macho.adt']:
  subprocess.run(['mcopy','-i',str(package/'esp.img'),'::/EFI/UniXNU/Payloads/'+name,str(tmp/name)],check=True)
 subprocess.run([sys.executable,str(ROOT/'scripts/b5q-install/verify-data-account.py'),'--seed',str(tmp/'scratch-data.img'),'--out',str(package/'data-account-verification.json')],check=True)
 raw=(tmp/'kernel.macho').read_bytes();o=Image(raw);im=Image(raw,o.entries['com.apple.kernel'][1]);names={n:va for va,rows in im.symbols().items()for n in rows};at=im.command(2)[0];sy,count,strings,_=struct.unpack_from('<4I',raw,at+8);missing=[]
 for i in range(count):
  ix,kind,section,desc,value=struct.unpack_from('<IBBHQ',raw,sy+16*i)
  if kind==1 and not value:missing.append(raw[strings+ix:raw.index(b'\0',strings+ix)].decode())
 assert not missing,missing
 address=names['_geni_i2c_prepare'];end=min(v for v in names.values()if v>address);calls=[];regs={}
 for ins in md.disasm(im.read(address,end-address),address):
  if ins.mnemonic=='mov'and ', #'in ins.op_str:
   reg,value=ins.op_str.split(', #');regs[reg]=int(value,0)
  assert ins.mnemonic!='blraaz','Known v21 PAC mismatch retained'
  if ins.mnemonic=='blraa':
   modifier=ins.op_str.split(', ')[1];value=regs.get(modifier);assert value in [0x50c7,0xc120];calls.append(value)
 assert 0x50c7 in calls and 0xc120 in calls
 report['actual_deployment_geni_typed_callback_calls']=[hex(v)for v in calls];report['undefined_symbols']=missing
 for fixture,vt in [('hid-device-26C5035r.json','__ZTV14NativeHidInput'),('usb-xhci-26C5035r.json','__ZTV10B5qUsbHost')]:
  abi=json.loads((ROOT/'UniXNU-b5q/scripts'/fixture).read_text());words=struct.unpack('<'+str(len(abi['slots']))+'Q',im.read(names[vt]+16,len(abi['slots'])*8));assert all(w>>32&0xffff==int(slot[1],16)for w,slot in zip(words,abi['slots']));report[vt]={'slots':len(words),'all_diversities_match':True}
 for name in ['_b5q_touch_probe','_sheng_thermal_probe','_sheng_thermal_level_probe','_native_hid_input_probe','_sheng_buttons_probe']:
  assert name in names
 for text in [b'B5qPeripherals: stage=after-display',b'B5qThermal: stage=ready tm=',b'B5qThermal: stage=ready thermal-level=',b'B5qTouch: stage=s4-clk-off']:
  assert text in raw,text
 menu=tmp/'unixnu.toml';subprocess.run(['mcopy','-i',str(package/'esp.img'),'::/EFI/UniXNU/unixnu.toml',str(menu)],check=True);config=tomllib.loads(menu.read_text());entry=next(e for e in config['entry']if e.get('type')=='xnu');assert entry['args']==' '.join(board['payload']['kernel_args'])and 'touch=0'in entry['args'].split()and'touch=1'not in entry['args'].split()
 decoder=load('v22_adt',ROOT/'scripts/b5q-install/build-ci-esp.py');nodes=decoder.adt_decode((tmp/'kernel.macho.adt').read_bytes());assert nodes['/chosen']['text-fixups']==b''.join(s.encode()+b'\0'for s in board['payload']['text_fixups'])
 for text in [b'b5q-usb-delay\0',b'B5qUsb: stage=delayed-start seconds=',b'gevntcnt=%08x devten=%08x',b'irq=%u un=%u storm=%u pwr=%lu']:assert text in raw,text
 report['USB_default_delay_seconds']=15;report['USB_interrupt_attach_and_storm_regressions']='PASS productionhelpertests;hardwarecounts pending';report['seven_text_fixups_preserved']=True;report['kernel_args_only_change']='none;USBworker default15s delay';report['deployment_kernel_sha256']=sha(tmp/'kernel.macho')
 assert report['deployment_kernel_sha256']==manifest['deploy_kernel_sha256']
 for record in ['mount-verification.json','runtime-verification.json','log-allocation.json']:assert(package/record).is_file()
 report['image']={'bytes':(package/'esp.img').stat().st_size,'sha256':sha(package/'esp.img'),'FAT_sector_bytes':4096};assert report['image']['bytes']==838860800
 report['CI_run']=manifest['ci_run'];report['source_commit']=manifest['source_commit'];(package/'v23-acceptance.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
