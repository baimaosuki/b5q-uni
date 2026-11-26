#!/usr/bin/env python3
"""Validate emitted production TOML and native command-line buffer boundaries."""
import sys,tomllib,re
from pathlib import Path
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'UniXNU-b5q/scripts'))
from b5q_menu import config,line
b=tomllib.loads((R/'UniXNU-b5q/board.toml').read_text());args=b['payload']['kernel_args'];doc=tomllib.loads(config(args));entries={e['id']:e for e in doc['entry']if e['type']=='xnu'}
assert set(entries)=={'xnu','daily','safe','ram-fallback'}and doc['boot']['default']=='xnu'
assert entries['xnu']['args']==' '.join(args)
for name,e in entries.items():
 values=e['args'].split();assert len(e['args'].encode())+1<=1024
 assert 'offline-mobile-graphics-client=1'not in values
 if name=='xnu':assert not any(v.startswith('b5q-f=')for v in values);assert 'b5q-dp=1'in values and 'log-bluetooth=2'in values
 else:assert 'b5q-dp=0'in values and 'b5q-f=0'in values and not any(v.startswith('log-bluetooth=')for v in values)
 if name in ['xnu','daily']:assert {'usb=1','wifi=5','bluetooth=1','b5q-data-ufs=2'}<=set(values)
 else:assert {'usb=0','wifi=0','bluetooth=0'}<=set(values)
 if name=='ram-fallback':assert 'b5q-data-ufs=0'in values and e['initrd']=='Payloads/scratch-data.img'
 else:assert 'initrd'not in e and e['path']=='Payloads/kernel.macho'
for n in range(990,1030):
 for default in [False,True]:
  try:value=line(['x'*n],default)
  except ValueError:assert n>1023
  else:assert len(value)==n<=1023
for values in [['中'],['x\x00y']]:
 try:line(values)
 except ValueError:pass
 else:raise AssertionError(values)
# Both exact loader and XNU declarations must retain their native1024B buffer.
assert 'CHAR8                           CommandLine[1024];'in(R/'UniXNU/drivers/DarwinBoot/DarwinBootPkg/Driver/DarwinBoot.c').read_text()
assert re.search(r'#define\s+BOOT_LINE_LENGTH\s+1024', (R/'sources/UniXNU/out/feeds/xnu-3199e8bc/pexpert/pexpert/arm64/boot.h').read_text())
print('PASS4productionTOMLprofiles/native1024Bbounds/80boundarycases/nonASCII/NUL; identicalkernelpathdaily/safe and independent4GiBRAMrecovery')
