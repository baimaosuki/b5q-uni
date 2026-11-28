#!/usr/bin/env python3
"""Pair the actual full-stage FD loader with its ESP, preserving other FAT files."""
import argparse,hashlib,importlib.util,json,subprocess,sys,tempfile
from pathlib import Path
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'UniXNU/scripts'))
from unixnu.boot_template import loader_pe
p=argparse.ArgumentParser(description=__doc__)
for key in ['fd','esp','package','out']:p.add_argument('--'+key,type=Path,required=True)
a=p.parse_args()
def sha(path):
 with path.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
def record(path):return dict(bytes=path.stat().st_size,sha256=sha(path))
spec=importlib.util.spec_from_file_location('espfs',R/'scripts/b5q-install/package-usb-dma-esp.py');fs=importlib.util.module_from_spec(spec);spec.loader.exec_module(fs)
metadata=json.loads(a.package.read_text());assert metadata['esp']==record(a.esp)
loader=loader_pe(a.fd.read_bytes(),'1b64af87-8415-4b57-9b16-680d70913b9f')
name='EFI/UniXNU/Drivers/DarwinBoot.efi'
with tempfile.TemporaryDirectory(prefix='b5q-stage-loader-pair-')as td:
 t=Path(td);before=fs.members(a.esp,t/'before');assert before==metadata['members']
 source=t/'DarwinBoot.efi';source.write_bytes(loader)
 if before[name]!=record(source):subprocess.run(['mcopy','-o','-i',str(a.esp),str(source),'::/'+name],check=True)
 after=fs.members(a.esp,t/'after');changed=[n for n in before if before[n]!=after[n]]
 assert changed in [[],[name]],changed
 assert (t/'after'/name).read_bytes()==loader
 report=dict(passed=True,scope='Pair newly compiled source-qualified loader from actual CI FD with ESP; no kernel/addon/Data/ADT/arguments change',
             input_ESP=metadata['esp'],output_ESP=record(a.esp),firmware=record(a.fd),changed_FAT_members=changed,
             old_loader=before[name],new_loader=after[name],hardware_verified=False)
 metadata['members']=after;metadata['esp']=record(a.esp);metadata['firmware_pairing']=report
 a.package.write_text(json.dumps(metadata,indent=2)+'\n');a.out.write_text(json.dumps(report,indent=2)+'\n')
 print('PASS actual FD/ESP loader paired; all other',len(after)-1,'FAT members unchanged')
