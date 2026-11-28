"""Stable b5q platform namespace, retained from the delivered Review21 ESP.

This is the build platform seed, not a hardware serial. Never log its value.
"""
from pathlib import Path
import os
UNIQUE_CHIP_ID = 'f5bae5fc62e80743'

def write_seed(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(UNIQUE_CHIP_ID + '\n')
    path.chmod(0o600)
    return UNIQUE_CHIP_ID
