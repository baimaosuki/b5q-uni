#!/usr/bin/env python3
"""Preflight external b5q inputs before enabling Samsung firmware or GPU recipes."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tomllib


def main():
    device = Path(os.environ.get('UNIXNU_DEVICE', Path(__file__).resolve().parents[1])).resolve()
    local_path = device / 'local.toml'
    local = tomllib.loads(local_path.read_text()) if local_path.is_file() else {}
    inputs = local.get('b5q_inputs', {})
    supplied = os.environ.get('B5Q_FIRMWARE_DIR') or inputs.get('samsung_firmware_dir')
    report = {'board': 'b5q', 'result': 'blocked', 'inputs': {}, 'missing': [], 'hardware_tested': False}
    if not supplied:
        report['missing'].append('B5Q_FIRMWARE_DIR: provide the local Samsung b5q firmware directory; Xiaomi ZAP firmware is not an acceptable replacement')
    else:
        root = Path(supplied).expanduser().resolve()
        if not root.is_dir():
            report['missing'].append('B5Q_FIRMWARE_DIR does not point to an existing directory')
        else:
            names = {'a740_zap.elf', 'a740_zap.mbn', 'a740_zap.mdt'}
            files = [p for p in root.rglob('*') if p.is_file() and p.name in names]
            if not files:
                report['missing'].append('Samsung a740_zap ELF/MBN/MDT input not found under the provided directory; supply the original firmware image if it has not been extracted')
            for path in files:
                report['inputs'][str(path.relative_to(root))] = {'bytes': path.stat().st_size, 'sha256': hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()}
            report['firmware_provenance_note'] = 'Model/version and signed-ZAP provenance must be recorded by the extraction recipe; finding a filename alone does not verify a signature'
    seed = os.environ.get('UNIXNU_UNIQUE_CHIP_ID')
    report['platform_seed_present'] = bool(seed)
    if not seed:
        report['missing'].append('UNIXNU_UNIQUE_CHIP_ID: the official payload requires the target platform seed; no seed is generated or copied from another device')
    report['result'] = 'blocked' if report['missing'] else 'inputs-located'
    report['scope'] = 'External input presence only; firmware extraction, board implementation and hardware qualification are separate porting records'
    # Input evidence belongs to the working report, not stdout secrets or a firmware binary.
    target = device / 'reports/input-preflight.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2) + '\n')
    print('b5q input preflight:', report['result'])
    for missing in report['missing']:
        print(' -', missing)
    return 2 if report['missing'] else 0


if __name__ == '__main__':
    sys.exit(main())
