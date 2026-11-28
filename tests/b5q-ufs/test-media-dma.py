#!/usr/bin/env python3
"""Run the actual shared firmware tables and OS media handoff validation."""
from pathlib import Path
import subprocess,tempfile
R=Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix='b5q-media-dma-')as td:
    target=Path(td)/'test'
    subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-O1','-g',
        '-fsanitize=address,undefined','-I'+str(R/'UniXNU-b5q/package'),
        '-I'+str(R/'uefi-b5q/Platforms/Samsung/b5qPkg/Drivers/B5qHandoffDxe'),
        str(Path(__file__).with_suffix('.cpp')),'-o',str(target)],check=True)
    subprocess.run([str(target)],check=True)
