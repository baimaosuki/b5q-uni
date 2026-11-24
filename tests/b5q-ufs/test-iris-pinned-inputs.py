#!/usr/bin/env python3
"""Pinned public Iris dependencies require no network and reject corruption."""
import hashlib,importlib.util,json,os,socket,sys,tempfile,urllib.request
from pathlib import Path
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'UniXNU-b5q/scripts'))
from b5q_video import pinned_linux
lock=json.loads((R/'sources/UniXNU-sheng/drivers/QcomIris/tools/source-lock.json').read_text())['linux']
def no_network(*args,**kwargs):raise AssertionError('No network needed for pinned Iris inputs')
urllib.request.urlopen=no_network;socket.create_connection=no_network
for name,digest in lock['files'].items():assert hashlib.sha256(pinned_linux(lock,name)).hexdigest()==digest
with tempfile.TemporaryDirectory(prefix='b5q-iris-cache-')as td:
 os.environ['UNIXNU_DEVICE']=td
 name=next(iter(lock['files']));path=Path(td)/'inputs/iris-linux'/lock['commit']/name;path.parent.mkdir(parents=True);path.write_bytes(b'corrupt')
 try:pinned_linux(lock,name)
 except ValueError:pass
 else:raise AssertionError('Corrupt source accepted')
 path.unlink()
 try:pinned_linux(lock,name)
 except FileNotFoundError:pass
 else:raise AssertionError('Missing source accepted')
 os.environ.pop('UNIXNU_DEVICE')
print('PASS all4 actual pinned Iris inputs offline; exact commit/SHA, corrupted/missing input rejected, no network request')
