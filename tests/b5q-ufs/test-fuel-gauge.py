#!/usr/bin/env python3
"""Run the production original-Samsung fuel-gauge decoder without hardware."""
from pathlib import Path
import subprocess
import tempfile
R=Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix='b5q-fuel-gauge-')as td:
    output=Path(td)/'test'
    subprocess.run(['c++','-std=c++17','-O1','-g','-Wall','-Wextra','-Werror',
        '-fsanitize=address,undefined','-I'+str(R/'UniXNU-b5q/package'),
        str(R/'tests/b5q-ufs/test-fuel-gauge.cpp'),'-o',str(output)],check=True)
    subprocess.run([str(output)],check=True)
