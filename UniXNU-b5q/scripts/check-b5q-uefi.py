#!/usr/bin/env python3
"""Check b5q firmware source wiring, independently of payload identity/GPU inputs."""
import hashlib
import json
import os
from pathlib import Path
import sys

root=Path(os.environ.get('UNIXNU_UEFI','')).resolve()
device=Path(os.environ.get('UNIXNU_DEVICE',Path(__file__).resolve().parents[1])).resolve()
board=root/'Platforms/Samsung/b5qPkg'
required=['UniXNUPkg/Application/UniXNU/UniXNU.inf','UniXNUPkg/Driver/UniXNUDxe/UniXNUDxe.inf','UniXNUPkg/Driver/UniXNURamDiskDxe/UniXNURamDiskDxe.inf','DarwinBootPkg/Driver/DarwinBoot.inf','b5qPkg/Drivers/B5qHandoffDxe/B5qHandoffDxe.inf']
report={'scope':'Static b5q DSC/FDF wiring check, not binary vendor-I/O or runtime validation','result':'FAIL','files':{},'errors':[]}
ufs_inf='Binaries/b5q/QcomPkg/Drivers/UFSDxe/UFSDxe.inf'
ufs_sha256='f33a84726dacd79bb243d4131f1ab25cf55aa686e1f980a59285bd024cc38d7a'
for name in ['b5q.dsc','b5q.fdf','Include/DXE.inc','Include/APRIORI.inc']:
 path=board/name
 if not path.is_file():report['errors'].append('Missing '+name);continue
 report['files'][name]=hashlib.sha256(path.read_bytes()).hexdigest()
if not report['errors']:
 dsc=(board/'b5q.dsc').read_text();dxe=(board/'Include/DXE.inc').read_text();apriori=(board/'Include/APRIORI.inc').read_text();fdf=(board/'b5q.fdf').read_text()
 for name in required:
  if name not in dsc or 'INF '+name not in dxe:report['errors'].append('Required DSC/FDF wiring missing: '+name)
 for name in ['MdeModulePkg/Universal/Disk/DiskIoDxe/DiskIoDxe.inf','FatPkg/EnhancedFatDxe/Fat.inf']:
  if name not in dxe:report['errors'].append('Required filesystem missing: '+name)
 for name,content in [('DXE.inc',dxe), ('APRIORI.inc',apriori)]:
  if sum(line.split()==['INF',ufs_inf] for line in content.splitlines())!=1:
   report['errors'].append('Expected the v8 UFSDxe in '+name)
 ufs=(root/ufs_inf).with_name('UFSDxe.patched.efi')
 if not ufs.is_file() or hashlib.sha256(ufs.read_bytes()).hexdigest()!=ufs_sha256:
  report['errors'].append('UFSDxe differs from the v8 firmware PE32')
 else:report['files'][str(ufs.relative_to(root))]=ufs_sha256
 reserved=(board/'Library/MemoryMapLib/MemoryMapLib.c').read_text()
 if ('/RamManagerDxe/' in fdf) and not all(row in reserved for row in
      ('0x880100000ULL, 0xa02000ULL', '0x880c00000ULL, 0xad00000ULL',
       '0x8b9a00000ULL, 0x200000ULL', '0x8bba00000ULL, 0x4600000ULL')):
  report['errors'].append('RamManager requires all four b5q live high-memory reservations')
 for name in ('ButtonsDxe', 'DisplayDxe', 'HALIOMMUDxe', 'CmdDbDxe', 'RpmhDxe'):
  if f'/{name}/' not in dxe:report['errors'].append('Required firmware module missing: '+name)
 for line in (dxe+'\n'+apriori+'\n'+fdf).splitlines():
  line=line.strip()
  if line.startswith('#'):continue
  if any(x in line for x in ['/SdccDxe/','/UsbMsdDxe/','/PILDxe/','/PILProxyDxe/','/SPSSDxe/',
      '/UsbConfigDxe/','/UsbDeviceDxe/','/UsbInitDxe/','/XhciPciEmulationDxe/','/XhciDxe/',
      '/UsbfnDwc3Dxe/','/UsbPwrCtrlDxe/','/UsbBusDxe/','/UsbKbDxe/','/UsbMassStorageDxe/']):report['errors'].append('Forbidden default dispatch: '+line)
 if 'Binaries/sheng/' in dsc+dxe+apriori+fdf:report['errors'].append('Xiaomi binary input in b5q firmware')
report['result']='FAIL' if report['errors'] else 'PASS'
target=device/'reports/uefi-source-preflight.json';target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(report,indent=2)+'\n')
print('b5q firmware source preflight:',report['result'])
for error in report['errors']:print(error)
sys.exit(bool(report['errors']))
