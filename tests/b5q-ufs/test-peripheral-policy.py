#!/usr/bin/env python3
"""Run actual board USB/GMU policies with the local Samsung firmware fixture."""
from pathlib import Path
import subprocess
import tempfile
root = Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix='b5q-peripheral-policy-') as temp:
    target = Path(temp) / 'test'
    subprocess.run(['c++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
        '-Wno-misleading-indentation', '-fsanitize=address,undefined',
        '-I', str(root / 'UniXNU-b5q/package'),
        '-I', str(root / 'sources/UniXNU/drivers/Adreno740'),
        '-I', str(root / 'sources/UniXNU/kits/AdrenoFirmware'),
        str(root / 'tests/b5q-ufs/test-peripheral-policy.cpp'),
        str(root / 'sources/UniXNU/drivers/Adreno740/NativeAdrenoSha256.cpp'),
        str(root / 'sources/UniXNU/kits/AdrenoFirmware/AdrenoFirmware.c'),
        '-o', str(target)], check=True)
    subprocess.run([str(target), str(root / 'artifacts/firmware-b5q/F7310ZCS7EYF3/gpu/gmu_gen70200.bin')], check=True)
