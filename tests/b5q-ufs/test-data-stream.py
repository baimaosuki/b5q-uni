#!/usr/bin/env python3
"""Execute the production ADB write block against local files, raw and gzip."""
import hashlib,shutil,subprocess,tempfile
from pathlib import Path
from types import SimpleNamespace
R=Path(__file__).resolve().parents[2]
source=(R/'scripts/b5q-install/install-data-ufs.py').read_text()
a=source.index(' write_command=');b=source.index('\n actual=shell(',a)
block='\n'.join(line[1:]for line in source[a:b].splitlines())
with tempfile.TemporaryDirectory(prefix='b5q-data-stream-')as td:
 t=Path(td);image=t/'source.img';payload=b'NXSB-fixture'+bytes(8<<20)+b'partial-pipe-tail-97'*5;image.write_bytes(payload)
 # This wrapper emulates only "adb shell -T <command>" on local regular files.
 wrapper=t/'local-adb';wrapper.write_text('#!/bin/sh\n[ "$1" = shell ] && [ "$2" = -T ] || exit 99\nshift 2\nexec bash -c "$1"\n');wrapper.chmod(0o755)
 for mode in ('userdata','macosdata'):
  target=t/(mode+'.img');prefix=bytes([0x5a])*(1<<20);target.write_bytes(prefix)
  env=dict(a=SimpleNamespace(partition=mode,image=image),target=str(target),start=0,ENVELOPE_BLOCKS=256,adb=[str(wrapper)],shutil=shutil,subprocess=subprocess,shell=lambda command:'/usr/bin/gzip')
  exec(compile(block,'install-data-ufs.py production write block','exec'),env)
  output=target.read_bytes();assert output[:1<<20]==prefix and output[1<<20:]==payload
  assert hashlib.sha256(output[1<<20:]).digest()==hashlib.sha256(payload).digest()
print('PASS actual production transfer block: raw+gzip stream, complete zero region and partial final pipe block; prefix untouched; no device or archive output')
