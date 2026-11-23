#!/usr/bin/env python3
"""Compile board Wi-Fi sources with the same PAC/SDK recipe as the kernel."""
import hashlib,json,os,subprocess,sys,tempfile
from pathlib import Path
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'UniXNU-b5q/scripts'))
from b5q_peripherals import flags,compile_object
from b5q_wifi import prepare
out=R/'artifacts/b5q-p3-work/board-target';out.mkdir(parents=True,exist_ok=True)
sdk=R/'tools/macos-sdk/MacOSX26.5.sdk';llvm=R/'tools/llvm21/usr/lib/llvm-21/bin'
os.environ['LD_LIBRARY_PATH']=str(R/'tools/llvm21/usr/lib/x86_64-linux-gnu')
with tempfile.TemporaryDirectory(prefix='b5q-wifi-target-')as td:
    td=Path(td);header=sdk/'System/Library/Frameworks/Kernel.framework/Headers'
    p=td/'libkern/c++/OSMetaClass.h';p.parent.mkdir(parents=True)
    p.write_text((header/'libkern/c++/OSMetaClass.h').read_text().replace('#if TARGET_OS_IPHONE && !TARGET_OS_SIMULATOR','#if !XNU_TARGET_OS_OSX').replace('#if TARGET_OS_OSX && defined(__arm64__)','#if XNU_TARGET_OS_OSX && defined(__arm64__)'))
    p=td/'os/base.h';p.parent.mkdir(exist_ok=True);p.write_text((header/'os/base.h').read_text().replace(', "authenticates-null-values"',''))
    xnu=R/'sources/UniXNU/out/feeds/xnu-3199e8bc'
    p=td/'sys/kern_control_private.h';p.parent.mkdir(exist_ok=True);p.write_bytes((xnu/'bsd/sys/kern_control_private.h').read_bytes())
    options=flags(sdk,td,header,R/'UniXNU-b5q/package',R/'sources/UniXNU',xnu,True)
    options += ['-I',str(R/'sources/UniXNU-sheng/drivers/Ath12kWifi/include'),
        '-I',str(R/'sources/UniXNU-sheng/drivers/Ath12kWifi/src'),
        '-Wno-misleading-indentation','-Wno-missing-field-initializers','-Wno-c99-designator',
        '-Wno-missing-designated-field-initializers']
    network=td/'IOKit/network';network.parent.mkdir(parents=True,exist_ok=True);network.symlink_to(R/'sources/IONetworkingFamily-188')
    abi=json.loads((R/'UniXNU-b5q/scripts/net-ether-26C5035r.json').read_text())
    options+=['-DB5Q_ETHERNET_CONTROLLER_SIZE='+abi['instance_size'],
        '-DB5Q_ETHERNET_INTERFACE_SIZE='+abi['interface_instance_size']]
    # This exact private type is in pinned XNU bsd/net/kpi_interface.h:866;
    # the full source build supplies it before IONetworkingFamily headers.
    p=td/'network-private.h';p.write_text('#include <sys/types.h>\ntypedef u_int32_t ifnet_ctl_cmd_t;\n#define IFNET_SUBFAMILY_WIFI 3\n')
    p.write_text(p.read_text()+'\n#include <net/if.h>\n#pragma pack(push,4)\nstruct ifmediareq { char ifm_name[16]; int ifm_current,ifm_mask,ifm_status,ifm_active,ifm_count; int *ifm_ulist; };\n#pragma pack(pop)\n')
    options+=['-include',str(p)]
    objects=[]
    for name in ['B5qWifiBoard.cpp','WifiFirmware.c','B5qWcnPower.cpp','B5qEthernet.cpp','WifiNet.cpp']:
        source=R/'UniXNU-b5q/package'/name
        if name=='WifiNet.cpp':source=prepare(R/'sources/UniXNU-sheng',out/'generated')
        objects.append(compile_object(llvm/'clang++',options+['-I',str(R/'sources/UniXNU-sheng/package')],source,out/(source.stem+'.o'),llvm))
    result=dict(passed=True,complete_stage=False,hardware_verified=False,
        objects={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in objects})
    (out/'report.json').write_text(json.dumps(result,indent=2)+'\n')
print('PASS Wi-Fi board arm64e objects; combined symbol/PAC and image gates remain required')
