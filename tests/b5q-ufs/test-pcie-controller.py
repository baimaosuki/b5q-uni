#!/usr/bin/env python3
import os,subprocess,tempfile
from pathlib import Path
R=Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix='b5q-pcie-controller-')as td:
    exe=Path(td)/'test'
    subprocess.run([os.environ.get('CXX','c++'),'-std=c++17','-O1','-g','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=address,undefined','-I'+str(R/'UniXNU-b5q/package'),str(Path(__file__).with_suffix('.cpp')),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
