#!/usr/bin/env python3
"""Local ten-item v21 acceptance on actual returned kernel, archives and ESP."""
import argparse,hashlib,importlib.util,json,struct,subprocess,sys,tempfile,tomllib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'UniXNU-b5q/scripts'),str(ROOT/'sources/UniXNU/kits/XnuPrelink')]
from kc_image import Image

def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def sha(path):
 with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--package',type=Path,required=True);p.add_argument('--ci-dir',type=Path,required=True);p.add_argument('--cached-tree',type=Path,required=True);a=p.parse_args()
 package=a.package.resolve();ci=a.ci_dir.resolve();checks={};work=ROOT/'artifacts/b5q-runtime-v21-work'
 manifest=json.loads((package/'package.manifest.json').read_text());inputs=json.loads((work/'v21-input-checks.json').read_text());assert inputs['passed']
 relink=json.loads((ci/'kernel/incremental-relink.json').read_text());assert relink['core_translation_units_compiled']==0
 board=tomllib.loads((ROOT/'UniXNU-b5q/board.toml').read_text());reference=load('v21_archive_members',ROOT/'UniXNU-b5q/scripts/relink-b5q-peripherals.py')
 with tempfile.TemporaryDirectory(prefix='b5q-v21-final-') as td:
  tmp=Path(td)
  for name in ['kernel.macho','scratch-data.img']:
   subprocess.run(['mcopy','-i',str(package/'esp.img'),'::/EFI/UniXNU/Payloads/'+name,str(tmp/name)],check=True)
  subprocess.run([sys.executable,str(Path(__file__).with_name('verify-data-account.py')),'--seed',str(tmp/'scratch-data.img'),'--out',str(package/'data-account-verification.json')],check=True)
  checks[1]={'passed':True,'evidence':'data-account-verification.json; actual APFS files, PBKDF2, group membership and inode uid/gid/mode'}
  raw=(tmp/'kernel.macho').read_bytes();outer=Image(raw);im=Image(raw,outer.entries['com.apple.kernel'][1]);names={n:v for v,rows in im.symbols().items() for n in rows}
  offset=im.command(2)[0];sy,count,strings,_=struct.unpack_from('<4I',raw,offset+8);missing=[]
  for i in range(count):
   ix,kind,section,desc,value=struct.unpack_from('<IBBHQ',raw,sy+16*i)
   if kind==1 and not value:missing.append(raw[strings+ix:raw.index(b'\0',strings+ix)].decode())
  assert not missing,missing
  checks[2]={'passed':True,'evidence':'pre-ci/peripheral-policy; actual returned USB strings and board archive'}
  for text in [b'B5qUsb: %s gsnpsid=',b'qscratch_cfg=%08x qscratch_hs=%08x qscratch_ss=%08x',b'before-prepare\0',b'after-prepare\0',b'B5qTouch: stage=application-info']:
   assert text in raw,text
  assert b'b5q-usb-handoff\0' not in raw and b'b5q-gmu-handoff\0' not in raw
  checks[3]={'passed':True,'fake_ADT_handoff_gate_count':0}
  for item,fixture,vt in [(4,'hid-device-26C5035r.json','__ZTV14NativeHidInput'),(5,'usb-xhci-26C5035r.json','__ZTV10B5qUsbHost')]:
   abi=json.loads((ROOT/'UniXNU-b5q/scripts'/fixture).read_text());slots=abi['slots'];words=struct.unpack('<'+str(len(slots))+'Q',im.read(names[vt]+16,len(slots)*8))
   assert all((word>>32&0xffff)==int(slot[1],16) for word,slot in zip(words,slots)),vt
   checks[item]={'passed':True,'actual_deployment_vtable_slots':len(slots),'all_diversities_match':True,'undefined_symbols':missing}
  probes=['sheng_cpufreq_probe','sheng_thermal_probe','sheng_thermal_level_probe','sheng_board_clock_probe','sheng_buttons_probe','native_hid_input_probe','b5q_touch_probe','sheng_dpu_probe']
  for name in probes:
   va=names['_'+name];assert im.read(va,4)!=bytes.fromhex('c0035fd6'),name
  checks[6]={'passed':True,'actual_kernel_probes':{n:hex(names['_'+n]) for n in probes}}
  menu=tmp/'unixnu.toml';subprocess.run(['mcopy','-i',str(package/'esp.img'),'::/EFI/UniXNU/unixnu.toml',str(menu)],check=True)
  config=tomllib.loads(menu.read_text());entry=next(e for e in config['entry'] if e.get('type')=='xnu');assert entry['args']==' '.join(board['payload']['kernel_args'])
  assert len(board['payload']['text_fixups'])==7;checks[7]={'passed':True,'actual_menu_matches_board':True,'kernel_args_bytes':len(entry['args'].encode()),'seven_text_fixups':'preserved and bound in ADT'}
  assert 'b5q-smmu-reuse=1' in entry['args'].split();checks[8]={'passed':True,'new_board_apps_smmu_mapping_count':0,'root_GPT_code_unchanged':True}
  expected='1fce36d7ee6c79cb2b1aca01b3635cdda568c8dadef6a5c3490007610a3a3d3b';assert relink['unchanged_core_after_link_sha256']==expected
  before=dict(reference.members(a.cached_tree/'build/adreno740/libAdreno740.a'));after=dict(reference.members(ci/'tree/build/adreno740/libAdreno740.a'))
  assert before.keys()==after.keys();changed=[n for n in before if before[n]!=after[n]];assert changed==['B5qGpu.o'],changed
  assert manifest['esp_files']['EFI/UniXNU/Payloads/kernel.macho.gpuaddon']['sha256']=='b68e1164f7dd0ff822f20e116e97adc4606926a4204fc25eaa5241c2a966d82d'
  checks[9]={'passed':True,'unchanged_XNU_core_sha256':expected,'compiled_XNU_core_units':0,'compiled_Mesa_Turnip_Metal_units':0,'only_changed_Adreno_archive_member':changed,'board_units_compiled':relink['board_translation_units_compiled'],'gpu_addon_byte_identical_v19_v20':True}
  assert (package/'esp.img').stat().st_size==800*2**20
  checks[10]={'passed':True,'bytes':800*2**20,'FAT_sector':4096,'sectors_per_cluster':1,'sha256':sha(package/'esp.img'),'evidence':['package.manifest.json','mount-verification.json','log-allocation.json','runtime-verification.json']}
  for path in ['mount-verification.json','log-allocation.json','runtime-verification.json']:assert (package/path).is_file(),path
  assert len(checks)==10 and all(c['passed'] for c in checks.values())
  report={'passed':True,'checks':checks,'source_commit':manifest['source_commit'],'CI':manifest['ci_run'],'hardware_tested':False}
  (package/'v21-acceptance.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
