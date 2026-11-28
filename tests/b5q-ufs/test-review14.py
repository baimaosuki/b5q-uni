#!/usr/bin/env python3
"""review14 compatibility entry; the host regression lives in scripts/b5q-install."""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parents[2] / 'scripts/b5q-install/test-review14.py'),
               run_name='__main__')
