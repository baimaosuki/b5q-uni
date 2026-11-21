#!/usr/bin/env python3
"""Stage a pinned completed kernel and unchanged RAM Data for payload-only CI."""
import argparse
import json
import shutil
import struct
import subprocess
import sys
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--unixnu', type=Path, required=True)
p.add_argument('--device', type=Path, required=True)
p.add_argument('--artifact', type=Path, required=True)
p.add_argument('--data-out', type=Path, required=True)
p.add_argument('--source-run', type=int, required=True)
p.add_argument('--source-commit', required=True)
p.add_argument('--kernel-only', action='store_true', help='Reuse a successful kernel step when its payload construction failed')
a = p.parse_args()
core, device = a.unixnu.resolve(), a.device.resolve()
sys.path.insert(0, str(core / 'scripts'))
from unixnu.cli import parser
from unixnu.config import Context

ctx = Context(parser().parse_args(['build', 'payload', '--device', str(device),
                                 '--os', 'macos-27.3-26C5035r']))
if a.kernel_only:
    found = [path for path in a.artifact.rglob('kernel.macho') if path.parent.name == 'kernel']
    if len(found) != 1:
        raise SystemExit('Source artifact must contain one completed kernel')
    source = found[0].parent.parent
    prior_manifest = None
else:
    found = list(a.artifact.rglob('package.manifest.json'))
    if len(found) != 1:
        raise SystemExit('Completed source artifact must contain one package manifest')
    source = found[0].parent
    prior_manifest = json.loads(found[0].read_text())
destination = ctx.work / 'kernel'
destination.mkdir(parents=True, exist_ok=True)
for path in (source / 'kernel').glob('*'):
    if path.is_file():
        shutil.copyfile(path, destination / path.name)
record = dict(source_run=a.source_run,
              source_commit=a.source_commit,
              kernel_recompiled=False, prior_manifest=prior_manifest,
              source_kernel_step_completed=True, source_payload_reused=not a.kernel_only)
(ctx.work / 'kernel-reuse.json').write_text(json.dumps(record, indent=2) + '\n')
if a.kernel_only:
    print('Staged completed kernel; RAM Data is reused independently from v11')
    raise SystemExit(0)
out = a.data_out
out.mkdir(parents=True, exist_ok=True)
for src, dest in [('scratch-data.img', 'data.dbr'),
                  ('kernel.macho.trustcache', 'owner-trust.bundle'),
                  ('kernel.macho.gpuaddon','gpu-addon.bin')]:
    subprocess.run(['mcopy', '-i', str(source / 'payload/payload.img'),
                    '::/EFI/UniXNU/Payloads/' + src, str(out / dest)], check=True)
# Retain original Apple modules; the official runtime regenerates and signs
# its owner module together with its boot shim addon in the new payload.
trust = out / 'original-ipsw-trust.bundle'
data = (out/'owner-trust.bundle').read_bytes()
count = struct.unpack_from('<I', data)[0]
offsets = list(struct.unpack_from(f'<{count}I', data, 4)) + [len(data)]
mods = [data[offsets[i]:offsets[i + 1]] for i in range(3)]
trust.write_bytes(struct.pack('<4I', 3, 16, 16 + len(mods[0]),
                             16 + len(mods[0]) + len(mods[1])) + b''.join(mods))
shutil.copyfile(source / 'runtime/data-seed.json', out / 'data-seed.json')
(out / 'reuse.json').write_text(json.dumps(dict(source_run=a.source_run,
    data_regenerated=False, original_data_run=json.loads((out / 'data-seed.json').read_text()).get('ci_run', a.source_run),
    source_seed_metadata=json.loads((out / 'data-seed.json').read_text())), indent=2) + '\n')
print('Staged pinned completed kernel and unchanged sparse RAM Data; logical bytes:', json.loads((out / 'data-seed.json').read_text())['logical_bytes'])
