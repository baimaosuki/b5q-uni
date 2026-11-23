#!/usr/bin/env python3
"""Exercise the production Samsung FIFO transport with ASan and UBSan."""
import os,subprocess,tempfile
from pathlib import Path
R=Path(__file__).resolve().parents[2]
cc=os.environ.get('CC','cc');cxx=os.environ.get('CXX','c++')
includes=['-I'+str(R/'UniXNU-b5q/package'),'-I'+str(R/'sources/UniXNU-sheng/drivers/QcaBluetooth/src')]
with tempfile.TemporaryDirectory(prefix='b5q-bt-fifo-') as td:
    obj=Path(td)/'fifo.o';exe=Path(td)/'test'
    flags=['-g','-O1','-fsanitize=address,undefined','-fno-omit-frame-pointer',*includes]
    subprocess.run([cc,*flags,'-std=c11','-c',str(R/'UniXNU-b5q/package/B5qBtFifo.c'),'-o',str(obj)],check=True)
    subprocess.run([cxx,*flags,'-std=c++17',str(Path(__file__).with_suffix('.cpp')),str(obj),'-o',str(exe)],check=True)
    subprocess.run([str(exe)],check=True)
