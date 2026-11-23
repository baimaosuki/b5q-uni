#!/usr/bin/env python3
"""Stage the original macOS Bluetooth runtime with Samsung WCN6855 firmware."""
import argparse,hashlib,json,os,subprocess,sys
from pathlib import Path
from b5q_wcn_firmware import stage
p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path);p.add_argument('target',choices=['macos27']);p.add_argument('--os-root',type=Path,required=True);p.add_argument('--component',type=Path,required=True);a=p.parse_args()
out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
subprocess.run([sys.executable,str(a.component/'tools/build-userland.py'),str(out/'userland'),
    '--bluetoothd',str(a.os_root/'usr/sbin/bluetoothd'),'--os',a.target],check=True)
firmware=stage('bluetooth',out/'firmware/qca')
report=json.loads((out/'userland/report.json').read_text())
marker=dict(native_input_sha256=report['native_input_sha256'],files={n:v['sha256']for n,v in report['files'].items()})
(out/'userland/bin/QcaBluetooth.runtime').write_text(json.dumps(marker,sort_keys=True)+'\n')
report['directories']={'sbin':'userland/bin','lib':'userland/lib','firmware/qca':'firmware/qca'}
report['firmware']=dict(firmware_prefix='firmware/qca',files=firmware,hardware_verified=False)
report['runtime_marker_sha256']=hashlib.sha256((out/'userland/bin/QcaBluetooth.runtime').read_bytes()).hexdigest()
(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
print('Built signed native macOS Bluetooth runtime with hash-locked Samsung firmware')
