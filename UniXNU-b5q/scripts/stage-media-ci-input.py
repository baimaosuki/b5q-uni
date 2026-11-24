#!/usr/bin/env python3
"""Fetch the private original-firmware build input and verify every file."""
import argparse,hashlib,json,os,struct,urllib.error,urllib.parse,urllib.request,zlib
from pathlib import Path
DEVICE=Path(__file__).resolve().parents[1]
ASSET=784899975
SHA256='634cec06429aa12a9da586785e9fa7cfd942696741d2cce451086f5cba0dbb54'
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
token=os.environ['GH_TOKEN'];base='https://api.github.com/repos/baimaosuki/b5q-uni/releases/assets/'+str(ASSET)
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None
request=urllib.request.Request(base,headers={'Authorization':'Bearer '+token,'Accept':'application/octet-stream','User-Agent':'b5q-stock-input'})
try:response=urllib.request.build_opener(NoRedirect).open(request,timeout=45)
except urllib.error.HTTPError as e:
    if e.code!=302:raise
    url=e.headers['Location'];parts=urllib.parse.urlsplit(url)
    if parts.scheme!='https' or not (parts.hostname or '').endswith('.githubusercontent.com'):raise ValueError('Unexpected firmware input redirect')
    response=urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'b5q-stock-input'}),timeout=45)
with response:packed=response.read(32*1024*1024)
if hashlib.sha256(packed).hexdigest()!=SHA256:raise ValueError('Firmware CI input SHA256 mismatch')
decoder=zlib.decompressobj();raw=decoder.decompress(packed,64*1024*1024)
if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:raise ValueError('Invalid bounded firmware input')
manifest=json.loads((DEVICE/'reports/p4-runtime-firmware.json').read_text())
expected=manifest['files']
if raw[:8]!=b'B5QMED01' or struct.unpack_from('<I',raw,8)[0]!=len(expected):raise ValueError('Firmware container format changed')
at=12;seen=set();a.out.mkdir(parents=True,exist_ok=True)
while at<len(raw):
    if len(raw)-at<8:raise ValueError('Truncated firmware record')
    nameBytes,size=struct.unpack_from('<II',raw,at);at+=8
    if not nameBytes or nameBytes>128 or nameBytes+size>len(raw)-at:raise ValueError('Firmware record bounds')
    name=raw[at:at+nameBytes].decode('ascii');at+=nameBytes;data=raw[at:at+size];at+=size
    if name not in expected or name in seen:raise ValueError('Unapproved or duplicate firmware file')
    item=expected[name]
    if size!=item['bytes']or hashlib.sha256(data).hexdigest()!=item['sha256']:raise ValueError('Original firmware file identity mismatch')
    seen.add(name);target=a.out/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data);target.chmod(0o644)
if seen!=set(expected):raise ValueError('Incomplete firmware input')
(a.out/'receipt.json').write_text(json.dumps(dict(sha256=SHA256,files=len(seen),hardware_verified=False),indent=2)+'\n')
print('Verified original Samsung media CI input:',len(seen),'files; no firmware committed to git')
