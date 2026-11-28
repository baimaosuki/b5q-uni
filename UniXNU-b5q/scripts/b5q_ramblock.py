"""Prepare the pinned RamBlock driver for full and incremental storage builds."""
from pathlib import Path
import shutil,subprocess

def prepare_source(source,destination):
    source,destination=Path(source),Path(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(source,destination)
    for name in ('b5q-volatile-data-4g.patch','b5q-storage-provider.patch'):
        subprocess.run(['patch','--batch','--fuzz=0',str(destination)],
                       input=Path(__file__).with_name(name).read_bytes(),check=True)
    return destination
