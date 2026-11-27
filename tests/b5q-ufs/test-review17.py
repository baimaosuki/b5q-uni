#!/usr/bin/env python3
"""Review17 host regression entrypoint."""
import runpy
from pathlib import Path
runpy.run_path(str(Path(__file__).resolve().parents[2] / 'scripts/b5q-install/test-review17.py'), run_name='__main__')
