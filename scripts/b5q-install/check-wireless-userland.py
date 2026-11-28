#!/usr/bin/env python3
"""Validate original 26C5035r Bluetooth patches and compile native tools."""
import hashlib,importlib,json,os,subprocess,sys,tempfile
from pathlib import Path
R=Path(__file__).resolve().parents[2];component=R/'sources/UniXNU-sheng/drivers/QcaBluetooth'
sys.path.insert(0,str(component/'tools'));native=importlib.import_module('native_macos27')
out=R/'artifacts/b5q-p2-work/user-target';out.mkdir(parents=True,exist_ok=True)
with tempfile.TemporaryDirectory(prefix='b5q-bt-native-')as td:
    thin=Path(td)/'bluetoothd'
    subprocess.run(['/usr/lib/llvm-17/bin/llvm-lipo',str(R/'artifacts/b5q-p2-work/os-root/usr/sbin/bluetoothd'),'-thin','arm64e','-output',str(thin)],check=True)
    original=hashlib.sha256(thin.read_bytes()).hexdigest();assert original==native.ORIGINAL_SHA256
    image=native.NativeImage(thin).vendor_routing().volatile_root_keys().h4_shutdown().capability_adapter()
    report=dict(status='PATCH_AND_ABI_VALIDATED',signed=False,hardware_verified=False,original_arm64e_sha256=original,patch=image.report())
    (out.parent/'native-macos27.json').write_text(json.dumps(report,indent=2)+'\n')
(out/'qbt_macos27_layout.h').write_text(native.layout_header())
cc=R/'tools/llvm21/usr/lib/llvm-21/bin/clang';sdk=R/'tools/macos-sdk/MacOSX26.5.sdk'
env=dict(os.environ,LD_LIBRARY_PATH=str(R/'tools/llvm21/usr/lib/x86_64-linux-gnu'));records=[]
for name in ['BlueTool','Type0']:
    source=component/'userland'/(name+'.c');obj=out/(name+'.o')
    command=[str(cc),'-target','arm64e-apple-macos27.0','-isysroot',str(sdk),'-O2','-Wall','-Wextra','-Werror','-fstack-protector-strong','-I',str(out),'-c',str(source),'-o',str(obj)]
    command+=['-fblocks']if name=='BlueTool'else['-fvisibility=hidden','-DQBT_LAYOUT_HEADER="qbt_macos27_layout.h"']
    result=subprocess.run(command,capture_output=True,text=True,env=env);(out/(name+'.log')).write_text(result.stdout+result.stderr)
    if result.returncode:raise SystemExit(result.stderr)
    records.append(dict(source=str(source),sha256=hashlib.sha256(source.read_bytes()).hexdigest(),object_sha256=hashlib.sha256(obj.read_bytes()).hexdigest(),command=command))
(out/'report.json').write_text(json.dumps(dict(passed=True,signed=False,CI_native_sign_and_link_required=True,hardware_verified=False,objects=records),indent=2)+'\n')
sys.path.insert(0,str(R/'UniXNU-b5q/scripts'));from b5q_wcn_firmware import stage
with tempfile.TemporaryDirectory(prefix='b5q-wcn-identity-')as td:
    assert len(stage('bluetooth',Path(td)/'bt'))==13 and len(stage('wifi',Path(td)/'wifi'))==11
print('PASS actual macOS27 bluetoothd SHA/UUID/native patches, BlueTool+Type0 target compilation,24originalSamsungfirmware identities; native signing/link still required')
