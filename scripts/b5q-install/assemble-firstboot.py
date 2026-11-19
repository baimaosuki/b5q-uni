#!/usr/bin/env python3
"""Assemble a first-boot candidate using the user's already booted menu transport.

Firmware/kernel transport bytes are preserved. Only the FAT payload is replaced;
new build output, original Apple root windows and matching template Data are
checked before a manifest is published. No device connection or write occurs.
"""
import argparse,hashlib,importlib.util,json,os,shutil,struct,subprocess,sys,tomllib
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--ci-files',type=Path,required=True);p.add_argument('--root-dir',type=Path,required=True);p.add_argument('--template',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();workspace=Path(__file__).resolve().parents[2];core=workspace/'UniXNU';sys.path.insert(0,str(core/'scripts'))
from unixnu import ramdisk
f=a.ci_files.resolve();roots=a.root_dir.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as stream:
  for block in iter(lambda:stream.read(8<<20),b''):h.update(block)
 return h.hexdigest()
manifest=json.loads((f/'package.manifest.json').read_text());report=json.loads((f/'payload/payload.json').read_text());kernel=json.loads((f/'kernel/kernel.json').read_text());index=json.loads((f/'transfer-index.json').read_text());seed=json.loads((f/'runtime/data-seed.json').read_text());root=json.loads((roots/'delivery/macosroot.json').read_text())
assert manifest['os_profile']=='macos-27.3-26C5035r' and manifest['storage']['ufs_controller'] and manifest['storage']['persistent_block_writes'] is False
assert kernel['mapping_complete'] and kernel['missing']=={} and not kernel['allow_missing'] and kernel['stub_symbol'] is None
assert seed['volume_uuid']=='1552CFEE-78FF-48D8-8A6C-694B867D61AC' and seed['template_owners_preserved'] and seed['logical_bytes']==29*2**30
for name,src in [('kernel.macho',f/'kernel/kernel.macho'),('payload.img',f/'payload/payload.img')]:
 assert src.stat().st_size==manifest['outputs'][name]['bytes'] and sha(src)==manifest['outputs'][name]['sha256'];shutil.copyfile(src,out/name)
assert root['image_bytes']==17603493888 and root['image_sha256']==sha(roots/'delivery/macosroot.img')
os.link(roots/'delivery/macosroot.img',out/'macosroot.img');shutil.copyfile(roots/'delivery/macosroot.json',out/'macosroot.json');shutil.copytree(roots/'delivery/policies',out/'policies')
stage=out/'esp-files';stage.mkdir();subprocess.run(['mcopy','-s','-i',str(out/'payload.img'),'::/EFI',str(stage)],check=True)
config=tomllib.loads((stage/'EFI/UniXNU/unixnu.toml').read_text());entry=next(x for x in config['entry'] if x.get('type')=='xnu');assert 'b5q-root=1' in entry['args'];assert entry['initrd']=='Payloads/scratch-data.img'
member=stage/'EFI/UniXNU/Payloads';assert sha(member/'kernel.macho')==report['payload_kernel_sha256'];assert sha(member/'kernel.macho.adt')==report['adt_sha256'];assert sha(member/'scratch-data.img')==seed['sha256'];assert sha(member/'kernel.macho.trustcache')==report['trust_cache_sha256']
# Preserve proven application and loader modules from the existing transport's
# source files. Their SHA256 is recorded explicitly; they are not rebuilt.
existing=workspace/'artifacts/unixnu-b5q';apps={'EFI/BOOT/BOOTAA64.EFI':existing/'UniXNU.efi','EFI/UniXNU/Drivers/DarwinBoot.efi':existing/'DarwinBoot.efi'}
for rel,src in apps.items():
 target=stage/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,target)
 subprocess.run(['mmd','-i',str(out/'payload.img'),'::/'+str(Path(rel).parent).replace('\\','/')],check=False,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 subprocess.run(['mcopy','-o','-i',str(out/'payload.img'),str(src),'::/'+rel],check=True)
# Main manifest describes the locally assembled FAT after adding the transport apps.
# The original CI payload report is retained separately.
shutil.copyfile(f/'payload/payload.json',out/'ci-payload.json');shutil.copyfile(f/'package.manifest.json',out/'ci-package.manifest.json');shutil.copyfile(f/'runtime/data-seed.json',out/'data-seed.json')
template=a.template.resolve();original=template.read_bytes();assert original[:8]==b'ANDROID!';assert sha(template)=='3b216aab477e8ca486aa36f9a0e1937db0308689babed153f133d84239ccc8b4';version=struct.unpack_from('<I',original,40)[0];assert version==4
ks,rs,_,hs=struct.unpack_from('<4I',original,8);sig=struct.unpack_from('<I',original,1580)[0];assert hs==1584 and sig in (0,4096)
ramstart=4096+((ks+4095)//4096)*4096;assert ramstart+rs<=len(original)
compressed=out/'payload.packed';tools=workspace/'sources/Mu-Silicium/Mu_Basecore';ramdisk.encode(out/'payload.img',compressed,tools)
roundtrip=out/'payload.roundtrip';ramdisk.decode(compressed,roundtrip,tools);assert sha(roundtrip)==sha(out/'payload.img');roundtrip.unlink()
header=bytearray(original[:ramstart]);struct.pack_into('<I',header,12,compressed.stat().st_size);struct.pack_into('<I',header,1580,0);boot=out/'boot.img'
with boot.open('wb') as target:
 target.write(header)
 with compressed.open('rb') as source:shutil.copyfileobj(source,target,8<<20)
 target.write(bytes((-compressed.stat().st_size)%4096))
assert boot.stat().st_size<=100663296
built=boot.read_bytes();assert built[4096:4096+ks]==original[4096:4096+ks];assert struct.unpack_from('<I',built,12)[0]==compressed.stat().st_size
assert hashlib.sha256(built[ramstart:ramstart+compressed.stat().st_size]).hexdigest()==sha(compressed)
compressed.unlink()
readiness={'scope':'first hardware boot candidate, not a proven macOS desktop','ci_run':index['run'],'source_commit':index['commit'],'host_build_complete':True,'flash_candidate_ready':True,'hardware_boot_verified':False,'macos_desktop_verified':False,'root_read_only':True,'data_volatile':True,'protected_partition_access_in_driver':False,'macosroot_first_lba':49692663,'macosroot_last_lba':62275574,'macosroot_capacity':51539607552,'boot_capacity':100663296,'esp_capacity':838860800,'transport_template_sha256':sha(template),'transport_kernel_sha256':hashlib.sha256(original[4096:4096+ks]).hexdigest(),'transport_kernel_preserved':True,'new_v4_boot_signature_bytes':0,'old_transport_signature_reused':False,'payload_chunk_roundtrip_verified':True,'new_kernel_symbols_missing':kernel['missing'],'new_data_uuid':seed['volume_uuid'],'root_policies_bound':'three local signed headers and anchor compiled in B5qRootPolicies.h; table digests verified on actual reads','original_loader_files':{rel:{'bytes':src.stat().st_size,'sha256':sha(src)} for rel,src in apps.items()},'limitations':['Controller/link must remain powered at firmware handoff; no cold-reset or QMP-PHY init is attempted.','Actual Samsung SMMU stream and free-bank ownership checked at boot, refusal is displayed on panic screen.','No Adreno power/Metal desktop or input hardware success is claimed.','Data modifications disappear on reboot.','No local phone flashing was performed.']}
(out/'BUILD-STATUS.json').write_text(json.dumps(readiness,indent=2)+'\n')
manifest['scope']=readiness['scope'];manifest['build_status']=readiness;manifest['outputs']={name:{'bytes':(out/name).stat().st_size,'sha256':sha(out/name)} for name in ['kernel.macho','payload.img','boot.img','macosroot.img']};manifest['deploy_kernel_sha256']=sha(member/'kernel.macho');manifest['ci_payload_sha256']=report['payload_sha256'];manifest['hardware_tested']=False
(out/'package.manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
(out/'SHA256SUMS').write_text(''.join(sha(path)+'  '+str(path.relative_to(out))+'\n' for path in sorted(out.rglob('*')) if path.is_file() and path.name!='SHA256SUMS'))
print(json.dumps({'directory':str(out),'outputs':manifest['outputs'],'boot_verified':True,'hardware_tested':False},indent=2))
