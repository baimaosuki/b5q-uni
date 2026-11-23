#!/usr/bin/env python3
import subprocess,tempfile
from pathlib import Path
R=Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix='b5q-wcn-') as td:
    exe=Path(td)/'test'
    subprocess.run(['c++','-std=c++17','-O1','-g','-fsanitize=address,undefined','-I'+str(R/'UniXNU-b5q/package'),str(Path(__file__).with_suffix('.cpp')),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
