#!/usr/bin/env python3
"""Exercise the production non-DMA panel transport and debounced lid state."""
from pathlib import Path
import subprocess,tempfile
R=Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix='b5q-panel-lid-')as td:
    out=Path(td)/'test'
    subprocess.run(['c++','-std=c++17','-O1','-g','-Wall','-Wextra','-Werror',
        '-fsanitize=address,undefined','-I'+str(R/'UniXNU-b5q/package'),
        str(R/'tests/b5q-ufs/test-panel-lid.cpp'),'-o',str(out)],check=True)
    subprocess.run([str(out)],check=True)
