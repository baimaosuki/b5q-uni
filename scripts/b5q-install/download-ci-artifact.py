#!/usr/bin/env python3
"""Download ordinary Actions artifacts; validate and unpack in local staging."""
import argparse,hashlib,json,os,stat,subprocess,tempfile,time,urllib.request,urllib.error,urllib.parse,zipfile
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',type=int,required=True);p.add_argument('--out',type=Path,required=True)
p.add_argument('--esp-only',action='store_true',help='Stage build returns one ESP containing kernel/addon/seed; verify kernel from its actual FAT bytes')
a=p.parse_args()
repo='baimaosuki/b5q-uni';token=os.environ.get('GH_TOKEN') or (Path.home()/'.config/gh/token').read_text().strip()
base='https://api.github.com/repos/'+repo
headers={'Authorization':'Bearer '+token,'User-Agent':'b5q-build-download','Accept':'application/vnd.github+json'}
def api(path):
 with urllib.request.urlopen(urllib.request.Request(base+path,headers=headers),timeout=90) as r:return json.load(r)
def sha(path):
 with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
info=api('/actions/runs/'+str(a.run));assert info['status']=='completed','Wait for this build to finish'
artifacts=api('/actions/runs/'+str(a.run)+'/artifacts?per_page=100')['artifacts'];found=[v for v in artifacts if v['name']==f'b5q-build-{a.run}' and not v['expired']];assert len(found)==1,'Expected one ordinary build artifact'
artifact=found[0]
class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None
with tempfile.TemporaryDirectory(prefix='b5q-artifact-') as tmp:
 archive=Path(tmp)/'artifact.zip';expected=artifact.get('digest')
 for attempt in range(3):
  try:
   try:response=urllib.request.build_opener(NoRedirect).open(urllib.request.Request(base+'/actions/artifacts/'+str(artifact['id'])+'/zip',headers=headers),timeout=90)
   except urllib.error.HTTPError as e:
    if e.code!=302:raise
    url=e.headers['Location'];parts=urllib.parse.urlsplit(url);host=parts.hostname or ''
    assert parts.scheme=='https' and any(host.endswith(s) for s in ['.githubusercontent.com','.blob.core.windows.net','.amazonaws.com'])
    response=urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'b5q-build-download'}),timeout=120)
   with response,archive.open('wb') as output:
    while block:=response.read(1024*1024):output.write(block)
   digest=sha(archive)
   if expected:assert expected=='sha256:'+digest,'Actions artifact digest mismatch'
   break
  except Exception:
   if attempt==2:raise
   print('Retrying artifact download; verification remains required',flush=True);time.sleep(2)
 with zipfile.ZipFile(archive) as z:
  members=z.infolist();manifests=[v for v in members if Path(v.filename).name=='package.manifest.json'];assert len(manifests)==1
  prefix=Path(manifests[0].filename).parent;dest=a.out.resolve();dest.mkdir(parents=True,exist_ok=False)
  files={}
  for member in members:
   if member.is_dir():continue
   name=Path(member.filename);assert not name.is_absolute() and '..' not in name.parts
   assert stat.S_IFMT(member.external_attr>>16)!=stat.S_IFLNK
   rel=name.relative_to(prefix)if name.is_relative_to(prefix)else Path('extra')/name
   target=dest/rel;assert not target.exists(),'Duplicate artifact path';target.parent.mkdir(parents=True,exist_ok=True)
   with z.open(member) as source,target.open('wb') as output:
    while block:=source.read(1024*1024):output.write(block)
   files[rel.as_posix()]={'bytes':target.stat().st_size,'sha256':sha(target)}
 manifest=json.loads((dest/'package.manifest.json').read_text())
 if a.esp_only:
  metadata=json.loads((dest/'batch2-package.json').read_text())
  assert files['esp.img']==metadata['esp']
  kernel=Path(tmp)/'readback-kernel'
  subprocess.run(['mcopy','-i',str(dest/'esp.img'),'::/EFI/UniXNU/Payloads/kernel.macho',str(kernel)],check=True)
  # The payload seals its deployment copy after prelink. The build manifest
  # identifies that pre-seal collection; actual deploy bytes belong to the
  # package member map and its paired HMAC report, both checked here.
  deployed=dict(bytes=kernel.stat().st_size,sha256=sha(kernel))
  assert deployed==metadata['members']['EFI/UniXNU/Payloads/kernel.macho']
  seal=json.loads(subprocess.check_output(['mtype','-i',str(dest/'esp.img'),'::/EFI/UniXNU/Payloads/kernel.macho.crypto-hmac.json']))
  assert seal['kernel_sha256']==deployed['sha256']
 else:
  for name,rel in [('kernel.macho','kernel/kernel.macho'),('payload.img','payload/payload.img')]:assert files[rel]==manifest['outputs'][name],name
 index={'run':str(a.run),'commit':info['head_sha'],'artifact':{'id':artifact['id'],'archive_sha256':digest,'github_digest_verified':bool(expected)},'files':files}
 (dest/'transfer-index.json').write_text(json.dumps(index,indent=2)+'\n')
 print(json.dumps({'run':a.run,'artifact_id':artifact['id'],'files':len(files),'outputs':manifest['outputs'],'directory':str(dest)},indent=2))
