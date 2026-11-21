#!/usr/bin/env python3
"""Run the real shared GENI/QUP code as C and C++ with ASan/UBSan."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
package = root / 'UniXNU-b5q/package'
with tempfile.TemporaryDirectory(prefix='b5q-v26-geni-') as tmp:
    tmp = Path(tmp)
    common = ['-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined', '-fno-omit-frame-pointer', '-I', str(package)]
    obj = tmp / 'GeniI2c.o'
    subprocess.run(['cc', '-std=c11', *common, '-c', str(package / 'GeniI2c.c'), '-o', str(obj)], check=True)
    binary = tmp / 'geni'
    subprocess.run(['c++', '-std=c++17', *common, str(Path(__file__).with_suffix('.cpp')), str(obj), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
