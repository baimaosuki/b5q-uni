#!/usr/bin/env python3
"""Execute actual sparse-init transfer against a stale local disk; no device."""
import gzip,hashlib,json,subprocess,sys,tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
R=Path(__file__).resolve().parents[2]
source=(R/'scripts/b5q-install/install-data-ufs.py').read_text()
start=source.index(' if sparse_plan:\n  validate_source_receipt(a.image')
end=source.index('\n # Both writes use',start)
block='\n'.join(line[1:]for line in source[start:end].splitlines())
with tempfile.TemporaryDirectory()as td:
 t=Path(td);image=t/'source.img';image.write_bytes(b'A'*4096+bytes(4096)+b'B'*4096)
 segments=[dict(block=0,blocks=3,sha256=hashlib.sha256(image.read_bytes()).hexdigest())]
 wrapper=t/'adb';wrapper.write_text('#!/bin/sh\nshift 2\nexec bash -c "$1"\n');wrapper.chmod(0o755)
 realrun=subprocess.run
 for failure in (None,'readback','validator'):
  target=t/'userdata';target.write_bytes(b'\xa5'*((256+4)*4096));mirror=t/('readback-'+str(failure)+'.img');writes=[]
  def run(args,**kwargs):
   if args[0]==sys.executable:
    if failure=='validator':raise subprocess.CalledProcessError(1,args)
    assert mirror.read_bytes()==image.read_bytes();return subprocess.CompletedProcess(args,0)
   writes.append(args[-1]);return realrun(args,**kwargs,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  def read(path,offset,count):
   assert path==str(target)
   with target.open('rb')as f:f.seek(offset*4096);body=f.read(count*4096)
   return bytes(len(body))if failure=='readback'else body
  calls=[]
  env=dict(a=SimpleNamespace(image=image,source_receipt=None,readback_image=mirror),m=dict(bytes=image.stat().st_size),sparse_plan=dict(segments=segments),validate_source_receipt=lambda *args:None,identity=dict(first=3406336,last=47595510),target=str(target),adb=[str(wrapper)],shell=lambda cmd:calls.append(cmd),subprocess=subprocess,ENVELOPE_BLOCKS=256,hashlib=hashlib,gzip=gzip,read=read,Path=Path,sys=sys,__file__=str(R/'scripts/b5q-install/install-data-ufs.py'))
  try:
   with patch.object(subprocess,'run',side_effect=run):exec(compile(block,'production sparse transfer','exec'),env)
  except (ValueError,subprocess.CalledProcessError):assert failure
  else:assert failure is None
  assert len(writes)==2 and 'count='not in writes[1] and 'seek=256'in writes[1]
  assert calls==[f'toybox blkdiscard -o 0 -l 180998860800 {target}']
  assert not any('B5QDATA1'in c for c in writes)
print('PASS production sparse transfer: stale allocated-zero overwrite, bounded segment, readback/validator failures stop before envelope')
