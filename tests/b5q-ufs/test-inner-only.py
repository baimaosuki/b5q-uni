#!/usr/bin/env python3
"""No hall/lid power policy or cover display can enter the board build."""
import json,subprocess,tempfile,tomllib
from pathlib import Path
R=Path(__file__).resolve().parents[2];P=R/'UniXNU-b5q/package';b=tomllib.loads((R/'UniXNU-b5q/board.toml').read_text());assert b['adt']['chosen']['u32']['b5q-feature-mask']==61
for n in ['B5qDaily.cpp','B5qBacklight.cpp','B5qDpLink.cpp','B5qFeatures.h']:
 s=(P/n).read_text()
 for forbidden in ['lidWorker','b5q_backlight_lid','b5q_dp_lid_online','gClosed','kIOPMClamshellClosed','kIOPMClamshellOpened','kIOPMEnableClamshell','kIOPMDisableClamshell','B5qFeatures::Lid']:
  assert forbidden not in s,(n,forbidden)
assert 'Lid='not in (P/'B5qFeatures.h').read_text()
# Inner DSI command MMIO is the only board backlight transport.
s=(P/'B5qBacklight.cpp').read_text();assert 'withRange(0xae94000,0x1000)'in s and 'const uint32_t target=wanted;'in s
for p in [P/'B5qDaily.cpp',P/'B5qBacklight.cpp',P/'B5qDpLink.cpp']:
 s=p.read_text().lower()
 assert '0xae96000'not in s and 'dsi1'not in s
# Execute the actual production target calculation: brightness is independent
# of every hall polarity and existing DP state.
line=next(l for l in (P/'B5qBacklight.cpp').read_text().splitlines()if 'const uint32_t target='in l)
with tempfile.TemporaryDirectory(prefix='b5q-inner-only-')as td:
 t=Path(td);(t/'test.cpp').write_text('#include <cstdint>\n#include <cassert>\nint main(){for(uint32_t wanted=0;wanted<=256;wanted++){'+line+'\nassert(target==wanted);}}')
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(t/'test.cpp'),'-o',str(t/'test')],check=True);subprocess.run([str(t/'test')],check=True)
print('PASS user-directed inner-panel-only policy:mask61,no lid worker/bit/notifications/DPcoupling,257actualbrightness requests independent,noDSI1 MMIO')
