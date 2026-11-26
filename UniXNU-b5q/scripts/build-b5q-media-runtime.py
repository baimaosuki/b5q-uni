#!/usr/bin/env python3
"""Extend the existing runtime addon with native b5q HAL and original media FW."""
import argparse,hashlib,importlib.util,json,os,shutil,struct,subprocess,sys,tempfile
from pathlib import Path
from b5q_codesign import set_trust_category
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--request',type=Path,required=True);a=p.parse_args()
request=json.loads(a.request.read_text());tree=Path(request['tree']);device=Path(request['device']);out=Path(request['output']);seed=Path(request['data_ramdisk'])
def sha(path):
 with path.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
def run(*args):subprocess.run(list(map(str,args)),check=True,cwd=tree)
original_seed=sha(seed)
run(sys.executable,tree/'scripts/build-boot-runtime.py','--request',a.request)
generated=json.loads((out/'generated.json').read_text());base=Path(generated['gpu_addon']);trust=Path(generated['trust_cache'])
assert sha(seed)==original_seed,'Original Data seed changed'
bluetooth=json.loads((out/'bluetooth-service.json').read_text())
daemon=bluetooth['files']['bin/bluetoothd']
if daemon.get('code_directory_platform')!=27:raise ValueError('Bluetooth runtime lost the macOS platform CodeDirectory')
platform_trust=out/'bluetooth-platform-trust.bundle'
bluetooth_trust=set_trust_category(trust,platform_trust,daemon['cdhash'],1)
trust=platform_trust;generated['trust_cache']=str(trust)
sys.path.insert(0,str(tree/'scripts'))
spec=importlib.util.spec_from_file_location('runtime',tree/'scripts/build-boot-runtime.py');runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime)
spec=importlib.util.spec_from_file_location('addon',tree/'scripts/addon-add-dir.py');addon=importlib.util.module_from_spec(spec);spec.loader.exec_module(addon)
with tempfile.TemporaryDirectory(prefix='b5q-media-runtime-',dir=out)as td:
 work=Path(td);audio=work/'audio';run(sys.executable,device/'scripts/build-b5q-audio-hal.py',audio,'macos27')
 # Stock inputs are supplied privately by the build. Never read a device or
 # an unqualified fallback, and do not publish the proprietary FW in Git.
 firmware=Path(os.environ['B5Q_STOCK_MEDIA_FIRMWARE']);manifest=json.loads((device/'reports/p4-runtime-firmware.json').read_text())
 staged=work/'firmware';staged.mkdir()
 for name,item in manifest['files'].items():
  source=firmware/name
  if not source.is_file()or source.is_symlink()or source.stat().st_size!=item['bytes']or sha(source)!=item['sha256']:raise ValueError('Unqualified stock media input: '+name)
  shutil.copyfile(source,staged/name);(staged/name).chmod(0o644)
 candidate=work/'combined.bin'
 run(sys.executable,tree/'scripts/addon-add-dir.py',base,candidate,'Library/Audio/Plug-Ins/HAL/B5qAudio.driver',audio/'B5qAudio.driver','firmware/qcom/sm8550/b5q',staged)
 before={n:(m,b)for n,m,b in addon.read(base)};after={n:(m,b)for n,m,b in addon.read(candidate)}
 assert len(after)==len(addon.read(candidate))and all(after.get(n)==entry for n,entry in before.items()),'Existing runtime/GPU files changed'
 hashes=runtime.addon_hashes(candidate,work/'verified-addon')
 data=trust.read_bytes();count=struct.unpack_from('<I',data)[0]
 offsets=list(struct.unpack_from(f'<{count}I',data,4))+[len(data)];known=set()
 for index in range(count):
  module=data[offsets[index]:offsets[index+1]]
  version,_,entries=struct.unpack_from('<I16sI',module);stride={0:20,1:22,2:24}.get(version)
  if stride is None or len(module)!=24+entries*stride:raise ValueError('Invalid original trust module')
  known.update(module[24+i*stride:44+i*stride].hex()for i in range(entries))
 missing=sorted(set(hashes)-known);trusted=work/'trust.bundle'
 if missing:run(sys.executable,tree/'scripts/trust-append-module.py',trust,trusted,*missing)
 else:shutil.copyfile(trust,trusted)
 final_addon=out/'media-addon.bin';candidate.replace(final_addon);final_trust=out/'media-owner-trust.bundle';trusted.replace(final_trust)
 generated.update(gpu_addon=str(final_addon),trust_cache=str(final_trust))
 (out/'generated.json').write_text(json.dumps(generated,indent=2)+'\n')
 report=dict(passed=True,hardware_verified=False,unchanged_Data_sha256=original_seed,preserved_addon_entries=len(before),new_addon_entries=len(after)-len(before),audio=json.loads((audio/'report.json').read_text()),firmware=manifest['files'],bluetooth_trust=bluetooth_trust,addon_sha256=sha(final_addon),trust_sha256=sha(final_trust))
 (out/'media-runtime.json').write_text(json.dumps(report,indent=2)+'\n')
print('Preserved Data/GPU/existing runtime; native signed HAL + hash-locked Samsung media firmware appended')
