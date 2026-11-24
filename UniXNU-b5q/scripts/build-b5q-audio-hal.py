#!/usr/bin/env python3
"""Build the b5q native macOS stereo HAL using the pinned shared implementation."""
import argparse,hashlib,json,os,plistlib,re,shutil,subprocess
from pathlib import Path
from b5q_audio import prepare_hal
from b5q_wireless import checkout
p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path);p.add_argument('target',choices=['macos27']);a=p.parse_args()
out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
tree=Path(os.environ.get('UNIXNU_TREE',Path.cwd()));reference=checkout(tree,'UniXNU-sheng','https://github.com/UniXNU/UniXNU-sheng.git','6c42e1055ffb3b335fda991190ad221edaa7af3c')
source,info,include=prepare_hal(reference,out/'source')
sdk=subprocess.check_output(['xcrun','--sdk','macosx','--show-sdk-path'],text=True).strip()
bundle=out/'B5qAudio.driver';shutil.rmtree(bundle,ignore_errors=True);contents=bundle/'Contents';(contents/'MacOS').mkdir(parents=True)
exe=contents/'MacOS/B5qAudio'
subprocess.run(['xcrun','clang','-target','arm64e-apple-macos27.0','-isysroot',sdk,*[v for p in include for v in ['-I',str(p)]],'-O2','-g0','-Wall','-Wextra','-Werror','-bundle','-fvisibility=hidden','-fstack-protector-strong','-framework','CoreFoundation','-framework','IOKit',str(source),'-o',str(exe)],check=True)
(contents/'Info.plist').write_bytes(plistlib.dumps(info))
subprocess.run(['codesign','--force','--sign','-','--pagesize','4096','--identifier','org.unixnu.b5q.audio',str(bundle)],check=True)
subprocess.run(['codesign','--verify','--strict',str(bundle)],check=True)
detail=subprocess.run(['codesign','--display','--verbose=4',str(exe)],check=True,capture_output=True,text=True).stderr
match=re.search(r'^CDHash=([0-9a-f]{40})$',detail,re.M)
if not match:raise ValueError('Missing signed HAL CDHash')
(out/'report.json').write_text(json.dumps(dict(built=True,target='arm64e-apple-macos27.0',cdhash=match[1],hardware_verified=False,profile='stereo speaker output only; absent microphone not published',files={str(p.relative_to(bundle)):hashlib.sha256(p.read_bytes()).hexdigest()for p in sorted(bundle.rglob('*'))if p.is_file()},sources={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in [source,reference/'hal/ShengAudioPlugIn.c',reference/'package/ShengAudioAbi.h']}),indent=2)+'\n')
print('Built signed native b5q stereo HAL; hardware qualification pending')
