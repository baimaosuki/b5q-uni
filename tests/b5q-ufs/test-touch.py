from pathlib import Path
import subprocess,tempfile
root=Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix='b5q-touch-') as td:
 out=Path(td)/'test'
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-fsanitize=address,undefined','-I',str(root/'UniXNU-b5q/package'),str(Path(__file__).with_suffix('.cpp')),str(root/'UniXNU-b5q/package/GeniI2c.c'),'-o',str(out)],check=True)
 subprocess.run([str(out)],check=True)
