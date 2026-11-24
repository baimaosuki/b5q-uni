#!/usr/bin/env python3
from pathlib import Path
import subprocess,tempfile
R=Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix='b5q-media-loader-')as td:
    target=Path(td)/'test'
    subprocess.run(['cc','-std=c11','-O1','-g','-fsanitize=address,undefined',
        '-I'+str(R/'UniXNU/drivers/DarwinBoot/DarwinBootPkg/Driver'),
        '-I'+str(R/'uefi-b5q/Platforms/Samsung/b5qPkg/Drivers/B5qHandoffDxe'),
        str(Path(__file__).with_suffix('.c')),'-o',str(target)],check=True)
    subprocess.run([str(target)],check=True)
