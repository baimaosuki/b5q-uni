#!/usr/bin/env python3
"""Build the unchanged native macOS supplicant with original b5q firmware."""
import argparse,hashlib,json,os,plistlib,re,shutil,subprocess,sys
from pathlib import Path
from b5q_wcn_firmware import stage
from b5q_wireless import checkout
p=argparse.ArgumentParser(description=__doc__);p.add_argument('output',type=Path);p.add_argument('target',choices=['macos27']);a=p.parse_args()
out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
tree=Path(os.environ.get('UNIXNU_TREE',Path.cwd()))
component=checkout(tree,'Ath12kWifi','https://github.com/UniXNU/Ath12kWifi.git','f087c7ddac07e945f20d199dbaf6c95c6db3346a')
firmware=stage('wifi',out/'firmware')
subprocess.run([sys.executable,str(component/'tools/build-supplicant.py'),'--target','macos'],check=True)
for name in ('bin','etc/wifi','daemons'):(out/name).mkdir(parents=True,exist_ok=True)
binary=out/'bin/unixnu-wpa_supplicant';shutil.copy2(component/'out/wpa-macos/bin/wpa_supplicant',binary);binary.chmod(0o755)
entitlements=out/'entitlements.plist';entitlements.write_bytes(plistlib.dumps({}))
subprocess.run(['codesign','--force','--sign','-','--pagesize','4096','--identifier','org.unixnu.wifi.supplicant','--entitlements',str(entitlements),str(binary)],check=True)
subprocess.run(['codesign','--verify','--strict',str(binary)],check=True)
detail=subprocess.run(['codesign','--display','--verbose=4',str(binary)],check=True,capture_output=True,text=True).stderr
match=re.search(r'^CDHash=([0-9a-f]{40})$',detail,re.M)
if not match:raise ValueError('Signed native supplicant missing CDHash')
(out/'etc/wifi/wpa_supplicant.conf').write_text('# Native Wi-Fi control supplies networks.\nap_scan=1\n')
job={'Label':'org.unixnu.wifi.supplicant','ProgramArguments':['/private/var/ngpu/bin/unixnu-wpa_supplicant','-Dsheng','-ien0','-c/private/var/ngpu/etc/wifi/wpa_supplicant.conf','-q','-s'],
    'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':3,'UserName':'root','Umask':0o77,'ProcessType':'Interactive'}
(out/'daemons/org.unixnu.wifi.supplicant.plist').write_bytes(plistlib.dumps(job))
report=dict(built=True,target=a.target,cdhash=match[1],hardware_verified=False,firmware_prefix='firmware/ath11k/WCN6855/hw2.0',daemons_prefix='Library/LaunchDaemons',firmware=firmware,
    files={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest()for n in ('bin','etc/wifi','daemons','firmware')for p in sorted((out/n).rglob('*'))if p.is_file()},
    supplicant=json.loads((component/'out/wpa-macos/report.json').read_text()))
(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
print('Built signed native macOS supplicant with hash-locked Samsung firmware')
