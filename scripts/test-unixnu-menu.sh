#!/usr/bin/env bash
# Exercise the actual delivered AArch64 EFI binaries in QEMU, not the b5q hardware.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
OUT="$ROOT/artifacts/unixnu-b5q"
LOG="$ROOT/logs/unixnu"
RUNNER="$ROOT/sources/UniXNU/package/Scripts/qemu-run.py"
mkdir -p "$LOG"
python3 "$RUNNER" "$OUT/esp" --display-size 1080x2640 --finish-on-expect --timeout 55 \
  --log "$LOG/menu-qemu.log" --screenshot "$OUT/menu-qemu.png" \
  --expect 'UNIXNU: config: loaded' \
  --expect 'UNIXNU: ui: graphics 1080x2640.*portrait layout' \
  --expect 'UNIXNU: menu: shown 5 entries' --reject ASSERT
python3 "$RUNNER" "$OUT/esp" --display-size 1080x2640 --keys ret --finish-on-expect --timeout 55 \
  --log "$LOG/payload-qemu.log" \
  --expect 'UNIXNU-HELLO: Hello from the UniXNU test payload' \
  --expect 'UNIXNU-HELLO: RESULT PASS 0 passed 0 failed' \
  --expect 'UNIXNU: menu: entry 0 returned Success' --reject ASSERT
cp "$LOG/menu-qemu.clean.log" "$OUT/menu-qemu.log"
cp "$LOG/payload-qemu.clean.log" "$OUT/payload-qemu.log"
python3 - "$OUT" <<'PY'
import hashlib
import json
from pathlib import Path
import sys
out = Path(sys.argv[1])
checks = {
    'menu': ['UNIXNU: config: loaded', 'UNIXNU: ui: graphics 1080x2640, scale 4, portrait layout', 'UNIXNU: menu: shown 5 entries'],
    'payload': ['UNIXNU-HELLO: Hello from the UniXNU test payload', 'UNIXNU-HELLO: RESULT PASS 0 passed 0 failed', 'UNIXNU: menu: entry 0 returned Success'],
}
report = {'result': 'PASS', 'environment': 'QEMU virt / AAVMF, exact delivered EFI binaries', 'hardware_tested': False, 'checks': {}}
for name, expected in checks.items():
    path = out / f'{name}-qemu.log'
    text = path.read_text()
    if not all(value in text for value in expected) or 'ASSERT' in text:
        raise SystemExit(f'failed: {name}')
    report['checks'][name] = {'result': 'PASS', 'expected': expected, 'log_sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
report['efi_sha256'] = {name: hashlib.sha256((out / f'{name}.efi').read_bytes()).hexdigest() for name in ['UniXNU', 'HelloPayload']}
(out / 'qemu-report.json').write_text(json.dumps(report, indent=2) + '\n')
files = sorted(p for p in out.iterdir() if p.is_file() and p.name != 'SHA256SUMS')
(out / 'SHA256SUMS').write_text(''.join(f'{hashlib.file_digest(p.open("rb"), "sha256").hexdigest()}  {p.name}\n' for p in files))
PY
