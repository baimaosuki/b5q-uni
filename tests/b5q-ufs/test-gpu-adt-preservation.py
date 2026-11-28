#!/usr/bin/env python3
"""Exercise actual local ADT regeneration against delivered GPU-loss regression."""
import copy,hashlib,importlib.util,json,subprocess,sys,tomllib
from pathlib import Path
R=Path(__file__).resolve().parents[2];sys.path[:0]=[str(R/'UniXNU-b5q/scripts'),str(R/'UniXNU/scripts')]
from b5q_gpu_adt import preserve,verify
from unixnu.devicetree import generate
spec=importlib.util.spec_from_file_location('fs',R/'scripts/b5q-install/package-usb-dma-esp.py');fs=importlib.util.module_from_spec(spec);spec.loader.exec_module(fs)
ci=R/'artifacts/b5q-v33b-fix-work/ci45426905030'
raw=subprocess.check_output(['mtype','-i',str(ci/'payload/payload.img'),'::/EFI/UniXNU/Payloads/kernel.macho.adt']);chosen=fs.adt_nodes(raw)['/chosen'][2]
b=tomllib.loads((R/'UniXNU-b5q/board.toml').read_text());assert not any(k.startswith('b5q-g')and k.endswith('-fw')for k in b['adt']['chosen'].get('bytes',{}))
expected=preserve(b,chosen);assert len(expected)==3
seed='1234567890abcdef'
for fallback in [False,True]:
 config=copy.deepcopy(b)
 if fallback:
  config['payload']['adt']['persistent_data']=False;config['payload']['adt']['owned_memory_size']='0x100000000'
  for k in ['owned_memory_outside_ranges','owned_memory_outside_reserved']:config['payload']['adt'].pop(k,None)
  config['adt']['chosen']['u32']['b5q-feature-mask']=0
 output=generate(ci/'device-tree/hardware.dtb',config,unique_chip_id=seed,data=fallback,trust=True,addon=True,root_policies=False)
 assert verify(fs.adt_nodes(output)['/chosen'][2])==expected
for name in expected:
 for mode in ['missing','short','corrupt']:
  damaged=dict(chosen)
  if mode=='missing':del damaged[name]
  elif mode=='short':damaged[name]=damaged[name][:-1]
  else:damaged[name]=bytes([damaged[name][0]^1])+damaged[name][1:]
  try:preserve(copy.deepcopy(b),damaged)
  except ValueError:pass
  else:raise AssertionError((name,mode,'accepted invalid firmware'))
# The exact old final ESP must be rejected, despite having a valid FAT/ADT.
old=subprocess.check_output(['mtype','-i',str(R/'artifacts/b5q-esp-v33b-repair/esp.img'),'::/EFI/UniXNU/Payloads/kernel.macho.adt'])
try:verify(fs.adt_nodes(old)['/chosen'][2])
except ValueError:pass
else:raise AssertionError('Known-bad delivered ESP falsely accepted')
print('PASS actual payload -> bareboard persistent/RAM ADT preserves all3stockfirmware SHA;9missing/short/corrupt cases +oldbadESP rejected')
