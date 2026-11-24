#!/usr/bin/env python3
"""Repeat all P5 host contracts; never equate these scopes with a P5 release."""
from pathlib import Path
import concurrent.futures,hashlib,json,subprocess,sys,time
R=Path(__file__).resolve().parents[2]
OUT=R/'artifacts/b5q-p5-work/local-regression'
OUT.mkdir(parents=True,exist_ok=True)
tests=sorted((R/'tests/b5q-ufs').glob('test-dp-*.py'))
assert len(tests)==26,'Explicitly review new/removed DP host groups'
inputs=tests+sorted((R/'UniXNU-b5q/package').glob('B5qDp*.h'))+[
 R/'UniXNU-b5q/package/QcomDwc3.cpp',R/'UniXNU-b5q/package/B5qUsbBoard.cpp',R/'UniXNU-b5q/package/B5qDpLink.cpp',R/'UniXNU-b5q/package/B5qDpIrq.cpp',
 R/'UniXNU-b5q/package/B5qDpDisplay.cpp',R/'UniXNU-b5q/scripts/build-b5q-gop-27.py',R/'UniXNU-b5q/scripts/legacy-display-26C5035r.json',
 R/'sources/UniXNU/drivers/GopFramebuffer/NativeLegacyDisplay.cpp',R/'sources/UniXNU/drivers/GopFramebuffer/NativeLegacyRequest.h']
def snapshot():return {str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest()for p in inputs}
before=snapshot()
def run(path):
 start=time.monotonic()
 result=subprocess.run([sys.executable,str(path)],cwd=R,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=180)
 name=path.stem.removeprefix('test-dp-');(OUT/(name+'.log')).write_text(result.stdout)
 return dict(name=name,passed=result.returncode==0,exit_code=result.returncode,
             seconds=round(time.monotonic()-start,2),test_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),output=result.stdout)
with concurrent.futures.ThreadPoolExecutor(max_workers=4)as pool:
 results=list(pool.map(run,tests))
stable=before==snapshot()
report=dict(passed=stable and all(r['passed']for r in results),source_inputs_stable=stable,source_sha256=before,hardware_verified=False,implementation_complete=True,
            checks=results,scope='Production GOP-tail DMA/loader, native link/IRQ/presentation/IOMFB/lid integration and baseline contracts; physical qualification pending')
(OUT/'report.json').write_text(json.dumps(report,indent=2)+'\n')
for result in results:
 print(('PASS 'if result['passed']else'FAIL ')+result['name'])
 if not result['passed']:print(result['output'])
print('P5 host groups:',len(results),'native implementation checked; CI/image acceptance and physical qualification remain')
sys.exit(0 if report['passed']else 1)
