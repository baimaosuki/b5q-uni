#!/usr/bin/env python3
"""Exercise the real final-verifier hash reuse gate, including restored mtime."""
import ast,hashlib,json,os,tempfile,time
from pathlib import Path
R=Path(__file__).resolve().parents[2]
source=(R/'scripts/b5q-install/verify-batch2-images.py').read_text()
node,=[n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef)and n.name=='validate_digest_receipt']
ns={'json':json};exec(compile(ast.Module(body=[node],type_ignores=[]),source,'exec'),ns)
validate=ns['validate_digest_receipt']
with tempfile.TemporaryDirectory()as td:
 p=Path(td)/'image.img';receipt=Path(td)/'receipt.json';p.write_bytes(b'actual-image')
 sha=hashlib.sha256(p.read_bytes()).hexdigest();stat=p.stat()
 valid=dict(path=str(p.resolve()),sha256=sha,full_image_SHA256_calculated=True,stat={k:getattr(stat,k)for k in ('st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')})
 def check(value,expected=True):
  receipt.write_text(json.dumps(value))
  try:validate(p,receipt,sha)
  except AssertionError:assert not expected;return
  assert expected
 check(valid)
 check(dict(valid,path=str(p.with_name('other.img'))),False)
 check(dict(valid,sha256='0'*64),False)
 check(dict(valid,full_image_SHA256_calculated=False),False)
 time.sleep(.002);p.write_bytes(b'actual-IMAGE');os.utime(p,ns=(stat.st_atime_ns,stat.st_mtime_ns))
 assert p.stat().st_size==stat.st_size and p.stat().st_mtime_ns==stat.st_mtime_ns
 check(valid,False)
 p.unlink();p.write_bytes(b'actual-image');os.utime(p,ns=(stat.st_atime_ns,stat.st_mtime_ns));check(valid,False)
print('PASS 6 actual verifier receipt cases: unchanged, wrong path/hash/full flag, modified bytes with restored mtime, replaced file')
