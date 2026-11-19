#!/usr/bin/env python3
"""Verify real b5q firstboot outputs, exact original PMGR branches and POST seal."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--directory', type=Path, required=True)
parser.add_argument('--ci-files', type=Path, required=True)
a = parser.parse_args()
workspace = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(workspace / 'UniXNU/kits/XnuPrelink'))
from kc_image import Image, signed
out = a.directory.resolve()
ci = a.ci_files.resolve()

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 << 20), b''):
            h.update(block)
    return h.hexdigest()

record = json.loads((ci / 'kernel/kernel.json').read_text())
assert record['mapping_complete'] and not record['missing'] and not record['allow_missing']
assert not record['stubbed'] and record['stub_symbol'] is None
fixture = json.loads((workspace / 'UniXNU-b5q/scripts/pmgr-26C5035r.json').read_text())
raw = (out / 'kernel.macho').read_bytes()
image = Image(raw)
branches = {}
for key, definition in fixture['bindings'].items():
    name = '_b5q_original_pmgr_' + key
    rows = [row for row in record['native_original_branches'] if row['symbol'] == name]
    assert len(rows) == 1, (name, rows)
    row = rows[0]
    assert row['owner'] == 'com.apple.driver.ApplePMGR'
    source = int(row['source'], 16)
    target = int(row['target'], 16)
    assert target == int(definition['address'], 16) + int(fixture['collection_slide'], 16)
    bti, branch = struct.unpack('<2I', image.read(source - 4, 8))
    assert bti == 0xd503245f and branch & 0xfc000000 == 0x14000000
    assert source + signed(branch & 0x3ffffff, 26) * 4 == target
    assert image.read(target, 32).hex() == definition['first_32_bytes']
    branches[name] = row

# The probe changes source text, so confirm the post-patch deployment kernel
# is already sealed. Run the official sealer only on an ephemeral copy.
import tomllib
config = tomllib.loads((out / 'esp-files/EFI/UniXNU/unixnu.toml').read_text())
entry = next(item for item in config['entry'] if item['type'] == 'xnu')
deploy = out / 'esp-files/EFI/UniXNU/Payloads/kernel.macho'
with tempfile.TemporaryDirectory(prefix='b5q-firstboot-post-') as temporary:
    copy = Path(temporary) / 'kernel.macho'
    copy.write_bytes(deploy.read_bytes())
    subprocess.run([sys.executable, str(workspace / 'UniXNU/scripts/seal-source-crypto-kernel.py'), str(copy), '--kernel-args', entry['args']], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert sha(copy) == sha(deploy), 'Deployment source POST seal was not already correct'
status = {'verification': 'PASS', 'mapping_complete': True, 'missing': {}, 'stubbed': [], 'actual_original_pmgr_branches': branches, 'deployment_source_POST_already_correct': True, 'hardware_boot_verified': False, 'scope': 'real built outputs; no runtime or desktop assertion'}
(out / 'build-verification.json').write_text(json.dumps(status, indent=2) + '\n')
print(json.dumps(status, indent=2))
