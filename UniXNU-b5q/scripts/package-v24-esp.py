#!/usr/bin/env python3
"""Package the official payload as the device's 800MiB native4K FAT32 ESP."""
import argparse,json,subprocess,sys,tempfile,tomllib
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--unixnu',type=Path,required=True);p.add_argument('--inputs',type=Path,required=True);a=p.parse_args()
core=a.unixnu.resolve();root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(core/'scripts'))
from unixnu.cli import parser
from unixnu.config import Context
from unixnu import ramdisk
ctx=Context(parser().parse_args(['build','payload','--device',str(root/'UniXNU-b5q'),'--os','macos-27.3-26C5035r']))
work=ctx.work;payload=work/'payload/payload.img';esp=work/'esp.img'
with tempfile.TemporaryDirectory(prefix='b5q-4kn-package-')as td:
 temp=Path(td);stage=temp/'files';stage.mkdir()
 if ramdisk.packed(payload):
  raw=temp/'payload.fat';ramdisk.decode(payload,raw);payload=raw
 subprocess.run(['mcopy','-s','-i',str(payload),'::/EFI',str(stage)],check=True)
 import shutil
 for old,rel in [('BOOTAA64.EFI','EFI/BOOT/BOOTAA64.EFI'),('DarwinBoot.efi','EFI/UniXNU/Drivers/DarwinBoot.efi')]:
  dest=stage/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(a.inputs/old,dest)
 cfg=stage/'EFI/UniXNU/unixnu.toml';text=cfg.read_text()
 if not tomllib.loads(text).get('driver'):text=text.replace('[[entry]]','[[driver]]\npath = "Drivers/DarwinBoot.efi"\n\n[[entry]]',1)
 cfg.write_text(text)
 (stage/'startup.nsh').write_text('\\EFI\\BOOT\\BOOTAA64.EFI\r\n')
 subprocess.run([sys.executable,str(root/'scripts/b5q-install/make-xnu2log.py'),'--out',str(stage/'XNU2LOG.BIN'),'--token','411839cbaebac4088c251c0ea57579a2'],check=True)
 with esp.open('wb')as f:f.truncate(800*2**20)
 # mtools size code5 = 128<<5=4096 bytes; same BPB as -S4096 -s1.
 subprocess.run(['mformat','-i',str(esp),'-T','204800','-S','5','-c','1','-F','-v','B5QMACOS','::'],check=True)
 for name in ['EFI','startup.nsh','XNU2LOG.BIN']:subprocess.run(['mcopy','-s','-i',str(esp),str(stage/name),'::/'],check=True)
print('Packaged800MiB4KnESP; final integrity/symbol/PAC checks run locally after artifact download')
