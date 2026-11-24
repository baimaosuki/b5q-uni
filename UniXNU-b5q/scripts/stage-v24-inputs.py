#!/usr/bin/env python3
"""Materialize runner-local binary inputs and reuse unchanged GPU artifacts."""
import argparse,base64,gzip,json,os,shutil,subprocess,sys,tempfile,tomllib
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--unixnu',type=Path,required=True);p.add_argument('--artifact',type=Path,required=True);p.add_argument('--inputs',type=Path,required=True);p.add_argument('--data-out',type=Path,required=True);a=p.parse_args()
root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(a.unixnu.resolve()/'scripts'));from unixnu import ramdisk
inputs=a.inputs.resolve();inputs.mkdir(parents=True,exist_ok=True)
files=[('gmu_gen70200.bin',2),('a740_sqe.fw',2),('a740_zap.mbn',1),('BOOTAA64.EFI',2),('DarwinBoot.efi',1)]
chunk=0
for name,count in files:
 text=''.join(os.environ['B5Q_V24_INPUT_'+str(i)]for i in range(chunk,chunk+count));chunk+=count
 (inputs/name).write_bytes(gzip.decompress(base64.b64decode(text)))
# Private Samsung bytes enter only the temporary board config on this runner.
# They are never added to Git; the official ADT generator carries them.
board=root/'UniXNU-b5q/board.toml'
from b5q_gpu_adt import verify
verify({key:(inputs/name).read_bytes()for name,key in [('gmu_gen70200.bin','b5q-gmu-fw'),('a740_sqe.fw','b5q-sqe-fw'),('a740_zap.mbn','b5q-zap-fw')]})
text=board.read_text()
section='[adt.chosen.bytes]'
lines=[]
from b5q_gpu_adt import verify as verify_gpu_firmware
verify_gpu_firmware({key:(inputs/name).read_bytes()for name,key in [('gmu_gen70200.bin','b5q-gmu-fw'),('a740_sqe.fw','b5q-sqe-fw'),('a740_zap.mbn','b5q-zap-fw')]})
for name,key in [('gmu_gen70200.bin','b5q-gmu-fw'),('a740_sqe.fw','b5q-sqe-fw'),('a740_zap.mbn','b5q-zap-fw')]:
 lines.append(key+' = "'+(inputs/name).read_bytes().hex()+'"')
if section in text:text=text.replace(section,section+'\n'+'\n'.join(lines),1)
else:text+='\n'+section+'\n'+'\n'.join(lines)+'\n'
tomllib.loads(text)
board.write_text(text)
source=next(a.artifact.rglob('package.manifest.json')).parent
archive=next(source.glob('tree/build/adreno740/libAdreno740.a'));shutil.copyfile(archive,inputs/archive.name)
a.data_out.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='b5q-gpu-reuse-')as td:
 payload=source/'payload/payload.img'
 if ramdisk.packed(payload):
  raw=Path(td)/'payload.fat';ramdisk.decode(payload,raw);payload=raw
 for old,new in [('kernel.macho.gpuaddon','gpu-addon.bin'),('kernel.macho.trustcache','owner-trust.bundle')]:
  subprocess.run(['mcopy','-i',str(payload),'::/EFI/UniXNU/Payloads/'+old,str(a.data_out/new)],check=True)
print('Staged Samsung b5q inputs, existing menu/loader and unchanged GPU archive/addon')
