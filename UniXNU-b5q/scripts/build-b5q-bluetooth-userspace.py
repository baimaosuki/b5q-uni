#!/usr/bin/env python3
"""Stage the original macOS Bluetooth runtime with Samsung WCN6855 firmware."""
import argparse,hashlib,json,os,re,subprocess,sys
from pathlib import Path
from b5q_wcn_firmware import stage
from b5q_codesign import set_platform
p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path);p.add_argument('target',choices=['macos27']);p.add_argument('--os-root',type=Path,required=True);p.add_argument('--component',type=Path,required=True);a=p.parse_args()
out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
subprocess.run([sys.executable,str(a.component/'tools/build-userland.py'),str(out/'userland'),
    '--bluetoothd',str(a.os_root/'usr/sbin/bluetoothd'),'--os',a.target],check=True)
firmware=stage('bluetooth',out/'firmware/qca')
report=json.loads((out/'userland/report.json').read_text())
daemon=out/'userland/bin/bluetoothd'
platform=set_platform(daemon,27)
subprocess.run(['codesign','--verify','--strict',str(daemon)],check=True)
detail=subprocess.run(['codesign','--display','--verbose=4',str(daemon)],check=True,capture_output=True,text=True).stderr
actual=re.search(r'^CDHash=([0-9a-f]{40})$',detail,re.M)
if not actual or actual[1] not in platform['cdhashes']:raise ValueError('codesign reported a different patched bluetoothd CDHash')
report['files']['bin/bluetoothd'].update(cdhash=actual[1],sha256=hashlib.sha256(daemon.read_bytes()).hexdigest(),bytes=daemon.stat().st_size,
    code_directory_platform=27,code_pages_valid=platform['page_hashes_valid'])
report['bluetoothd_code_directory']=platform
(out/'userland/report.json').write_text(json.dumps(report,indent=2)+'\n')
marker=dict(native_input_sha256=report['native_input_sha256'],files={n:v['sha256']for n,v in report['files'].items()})
(out/'userland/bin/QcaBluetooth.runtime').write_text(json.dumps(marker,sort_keys=True)+'\n')
report['directories']={'sbin':'userland/bin','lib':'userland/lib','firmware/qca':'firmware/qca'}
report['firmware']=dict(firmware_prefix='firmware/qca',files=firmware,hardware_verified=False)
report['runtime_marker_sha256']=hashlib.sha256((out/'userland/bin/QcaBluetooth.runtime').read_bytes()).hexdigest()
(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
print('Built signed native macOS Bluetooth runtime with hash-locked Samsung firmware')
