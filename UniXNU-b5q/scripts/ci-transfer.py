#!/usr/bin/env python3
"""Encrypted CI result relay using this repository's Checks API.

The runner receives only an RSA public key. Payloads/identity data never enter
public annotations in plaintext. No PAT is needed or persisted. Large signed
artifact redirects remain unused. This is a transport, not a build-success check.
"""
import argparse,base64,gzip,hashlib,hmac,io,json,os,secrets,subprocess,tarfile,tempfile,urllib.request
from pathlib import Path
CHUNK=36000

def request(repo,path,body=None,token=None,method=None):
 if not repo or len(repo.split('/'))!=2:raise ValueError('Repository required')
 headers={'Accept':'application/vnd.github+json','User-Agent':'b5q-encrypted-results','X-GitHub-Api-Version':'2022-11-28'}
 if token:headers['Authorization']='Bearer '+token
 data=None if body is None else json.dumps(body).encode()
 if data:headers['Content-Type']='application/json'
 req=urllib.request.Request('https://api.github.com/repos/'+repo+path,data=data,headers=headers,method=method)
 with urllib.request.urlopen(req,timeout=120) as r:return json.load(r)

def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()

def pack(root,public,out):
 out.mkdir(parents=True,exist_ok=True)
 archive=out/'results.tar.gz'
 files=[]
 for relative in ['kernel/kernel.macho','kernel/kernel.map.json','kernel/kernel.json','kernel/kernel.failed.json','payload/payload.img','payload/payload.json','package.manifest.json','payload/.complete.json']:
  p=root/relative
  if p.is_file():files.append((p,relative))
 native=root/'tree/build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837.unstripped.noctf'
 if native.is_file():files.append((native,'native/mach.development.bcm2837.unstripped.noctf'))
 for p in sorted((root/'kernel').glob('*.json')) if (root/'kernel').exists() else []:
  pair=(p,'kernel/'+p.name)
  if pair not in files:files.append(pair)
 # Actual logs, not a reconstructed list: preserve full failing linker output.
 for p in sorted((root/'logs').rglob('*.log')) if (root/'logs').exists() else []:
  if p.stat().st_size<=160*1024*1024:files.append((p,'logs/'+str(p.relative_to(root/'logs'))))
 index={'files':{name:{'bytes':p.stat().st_size,'sha256':sha(p)} for p,name in files},'run':os.environ.get('GITHUB_RUN_ID'),'commit':os.environ.get('GITHUB_SHA')}
 with tarfile.open(archive,'w:gz',compresslevel=6) as tar:
  raw=json.dumps(index,indent=2).encode();entry=tarfile.TarInfo('transfer-index.json');entry.size=len(raw);tar.addfile(entry,io.BytesIO(raw))
  for p,name in files:tar.add(p,arcname=name,recursive=False)
 password=secrets.token_hex(32).encode();auth=secrets.token_bytes(32)
 wrapped=subprocess.run(['openssl','pkeyutl','-encrypt','-pubin','-inkey',str(public),'-pkeyopt','rsa_padding_mode:oaep','-pkeyopt','rsa_oaep_md:sha256'],input=password+b'\n'+auth,stdout=subprocess.PIPE,check=True).stdout
 cipher=out/'results.enc'
 subprocess.run(['openssl','enc','-aes-256-ctr','-pbkdf2','-iter','200000','-pass','stdin','-in',str(archive),'-out',str(cipher)],input=password+b'\n',check=True)
 digest=hmac.new(auth,digestmod='sha256')
 with cipher.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):digest.update(b)
 header=dict(version=1,algorithm='RSA3072-OAEP-SHA256 + PBKDF2/AES256-CTR + HMAC-SHA256',wrapped=base64.b64encode(wrapped).decode(),bytes=cipher.stat().st_size,sha256=sha(cipher),hmac=digest.hexdigest(),chunks=(cipher.stat().st_size+CHUNK-1)//CHUNK)
 (out/'header.json').write_text(json.dumps(header)+'\n')
 return header,cipher

def publish(header,cipher,repo,commit,run,token):
 def annotation(title,message):return dict(path='encrypted-ci-results',start_line=1,end_line=1,annotation_level='notice',title=title,message=message)
 annotations=[annotation('b5q-transfer-header',json.dumps(header,separators=(',',':')))]
 with cipher.open('rb') as f:
  for i in range(header['chunks']):annotations.append(annotation(f'b5q-transfer-chunk-{i:06}',base64.b64encode(f.read(CHUNK)).decode()))
 for group,start in enumerate(range(0,len(annotations),250)):
  rows=annotations[start:start+250]
  check=request(repo,'/check-runs',dict(name=f'b5q-transfer-{run}-{group:03}',head_sha=commit,status='in_progress',output=dict(title='Encrypted CI result transfer',summary='Recipient-encrypted result bytes; this check is not a kernel success claim.',annotations=rows[:50])),token)
  for at in range(50,len(rows),50):
   request(repo,'/check-runs/'+str(check['id']),dict(output=dict(title='Encrypted CI result transfer',summary='Recipient-encrypted bytes.',annotations=rows[at:at+50])),token,method='PATCH')
  request(repo,'/check-runs/'+str(check['id']),dict(status='completed',conclusion='success'),token,method='PATCH')
 print('Published encrypted result relay:',header['bytes'],'bytes,',header['chunks'],'chunks',flush=True)

def unpack(header,cipher,private,dest):
 if cipher.stat().st_size!=header['bytes'] or sha(cipher)!=header['sha256']:raise ValueError('Ciphertext size/digest mismatch')
 wrapped=base64.b64decode(header['wrapped'])
 secret=subprocess.run(['openssl','pkeyutl','-decrypt','-inkey',str(private),'-pkeyopt','rsa_padding_mode:oaep','-pkeyopt','rsa_oaep_md:sha256'],input=wrapped,stdout=subprocess.PIPE,check=True).stdout
 password,auth=secret.split(b'\n',1)
 digest=hmac.new(auth,digestmod='sha256')
 with cipher.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):digest.update(b)
 if not hmac.compare_digest(digest.hexdigest(),header['hmac']):raise ValueError('Ciphertext authentication failed')
 dest.mkdir(parents=True,exist_ok=True)
 with tempfile.TemporaryDirectory(prefix='b5q-decrypt-') as tmp:
  archive=Path(tmp)/'results.tar.gz'
  subprocess.run(['openssl','enc','-d','-aes-256-ctr','-pbkdf2','-iter','200000','-pass','stdin','-in',str(cipher),'-out',str(archive)],input=password+b'\n',check=True)
  with tarfile.open(archive,'r:gz') as tar:
   members=tar.getmembers()
   for item in members:
    target=(dest/item.name).resolve()
    if not target.is_relative_to(dest.resolve()) or not (item.isfile() or item.isdir()):raise ValueError('Unsafe result archive path/type')
   tar.extractall(dest,members=members,filter='data')
 index=json.loads((dest/'transfer-index.json').read_text())
 for name,record in index['files'].items():
  path=dest/name
  if path.stat().st_size!=record['bytes'] or sha(path)!=record['sha256']:raise ValueError('Plaintext digest mismatch: '+name)
 print('Decrypted and verified',len(index['files']),'real CI files into',dest,flush=True)
 return index

def receive(repo,run,private,out):
 info=request(repo,'/actions/runs/'+str(run));commit=info['head_sha']
 checks=request(repo,'/commits/'+commit+'/check-runs?per_page=100')['check_runs']
 checks=sorted([c for c in checks if c['name'].startswith(f'b5q-transfer-{run}-')],key=lambda c:c['name'])
 if not checks or any(c['status']!='completed' for c in checks):raise ValueError('Encrypted result transfer not complete')
 header=None;chunks={}
 for check in checks:
  for page in range(1,10):
   rows=request(repo,'/check-runs/'+str(check['id'])+f'/annotations?per_page=100&page={page}')
   for row in rows:
    title=row.get('title','')
    if title=='b5q-transfer-header':header=json.loads(row['message'])
    elif title.startswith('b5q-transfer-chunk-'):chunks[int(title.rsplit('-',1)[1])]=row['message']
   if len(rows)<100:break
 if not header or set(chunks)!=set(range(header['chunks'])):raise ValueError('Incomplete encrypted chunk set')
 out.mkdir(parents=True,exist_ok=True);cipher=out/'results.enc'
 with cipher.open('wb') as f:
  for i in range(header['chunks']):f.write(base64.b64decode(chunks[i],validate=True))
 (out/'header.json').write_text(json.dumps(header,indent=2)+'\n')
 return unpack(header,cipher,private,out/'files')

def main():
 p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
 send=sub.add_parser('send');send.add_argument('--root',type=Path,required=True);send.add_argument('--public',type=Path,required=True);send.add_argument('--out',type=Path,required=True);send.add_argument('--publish',action='store_true')
 recv=sub.add_parser('receive');recv.add_argument('--repo',required=True);recv.add_argument('--run',required=True);recv.add_argument('--private',type=Path,required=True);recv.add_argument('--out',type=Path,required=True)
 test=sub.add_parser('unpack');test.add_argument('--header',type=Path,required=True);test.add_argument('--cipher',type=Path,required=True);test.add_argument('--private',type=Path,required=True);test.add_argument('--out',type=Path,required=True)
 a=p.parse_args()
 if a.command=='send':
  header,cipher=pack(a.root,a.public,a.out)
  if a.publish:publish(header,cipher,os.environ['GITHUB_REPOSITORY'],os.environ['GITHUB_SHA'],os.environ['GITHUB_RUN_ID'],os.environ['GH_TOKEN'])
 elif a.command=='receive':receive(a.repo,a.run,a.private,a.out)
 else:unpack(json.loads(a.header.read_text()),a.cipher,a.private,a.out)
if __name__=='__main__':main()
