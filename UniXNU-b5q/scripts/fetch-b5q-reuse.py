#!/usr/bin/env python3
"""Select the newest successful, nonexpired reusable build; use GH auth from env."""
import argparse,hashlib,json,re,shutil,subprocess,tempfile
from pathlib import Path
REQUIRED=('libAdreno740.a','kernel.macho','package.manifest.json','data-seed.json','payload.img')
def valid(root):
    found={name:list(root.rglob(name))for name in REQUIRED}
    return all(len(paths)==1 for paths in found.values())
def fetch(repo,out):
    pages=json.loads(subprocess.check_output(['gh','api','--paginate','--slurp',f'repos/{repo}/actions/artifacts?per_page=100'],text=True))
    data={'artifacts':[x for page in pages for x in page['artifacts']]}
    candidates=sorted((x for x in data['artifacts']if not x['expired']and re.fullmatch(r'b5q-build-\d+',x['name'])),key=lambda x:x['created_at'],reverse=True)
    failures=[]
    for item in candidates:
        run=item['workflow_run']['id']
        status=json.loads(subprocess.check_output(['gh','api',f'repos/{repo}/actions/runs/{run}'],text=True))
        if status['conclusion']!='success':continue
        with tempfile.TemporaryDirectory(prefix='b5q-reuse-candidate-')as td:
            stage=Path(td)
            result=subprocess.run(['gh','run','download',str(run),'--repo',repo,'--name',item['name'],'--dir',str(stage)],capture_output=True,text=True)
            if result.returncode or not valid(stage):failures.append(dict(run=run,reason='download failed or required reusable inputs missing'));continue
            out.mkdir(parents=True,exist_ok=True)
            if any(out.iterdir()):raise RuntimeError('Refuse nonempty reuse destination')
            for p in stage.iterdir():shutil.move(str(p),out/p.name)
            commit=status['head_sha'];assert re.fullmatch(r'[0-9a-f]{40}',commit)
            receipt=dict(run=run,commit=commit,artifact_id=item['id'],required_sha256={n:hashlib.sha256(next(out.rglob(n)).read_bytes()).hexdigest()for n in REQUIRED},skipped=failures)
            (out/'reuse-source.json').write_text(json.dumps(receipt,indent=2)+'\n');return receipt
    raise RuntimeError('No successful nonexpired artifact contains all reusable inputs; '+json.dumps(failures))
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--repo',required=True);p.add_argument('--out',required=True,type=Path);a=p.parse_args();print(json.dumps(fetch(a.repo,a.out)))
