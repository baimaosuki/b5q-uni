#!/usr/bin/env python3
"""Review15 host regression entrypoint."""
import runpy
from pathlib import Path
runpy.run_path(str(Path(__file__).resolve().parents[2] / 'scripts/b5q-install/test-review15.py'), run_name='__main__')
