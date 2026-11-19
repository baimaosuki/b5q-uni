#!/usr/bin/env python3
"""Exercise the real installer with a mock ADB transport; never open a device."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

root = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('installer', root / 'scripts/b5q-install/install-firstboot.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

with tempfile.TemporaryDirectory(prefix='b5q-install-test-') as tmp:
    directory = Path(tmp)
    outputs = {}
    for name, (filename, _, _) in module.PARTITIONS.items():
        image = directory / filename
        image.write_bytes((name + '\n').encode() * 16)
        outputs[filename] = {'bytes': image.stat().st_size, 'sha256': module.digest(image)}
    manifest = {'os_profile': 'macos-27.3-26C5035r', 'build_status': {'flash_candidate_ready': True, 'root_read_only': True, 'data_volatile': True, 'esp_install_required': True}, 'outputs': outputs}
    (directory / 'package.manifest.json').write_text(json.dumps(manifest))

    def case(flag, *, wrong_start=None, wrong_readback=None, expect_failure=False):
        writes = []
        reads = []
        def output(args, **kwargs):
            cmd = args[-1]
            reads.append(cmd)
            basic = {'id -u': '0', 'getprop ro.twrp.version': '3.7.1', 'getprop ro.product.device': 'b5q', 'getprop ro.product.model': 'SM-F7310'}
            if cmd in basic:
                return basic[cmd]
            if 'done < /proc/mounts' in cmd:
                return ''
            for name, (_, offset, size) in module.PARTITIONS.items():
                if cmd == module.partition_probe(name):
                    return f'sda{37 if name == "macosroot" else 21}\n{offset // 512 + (1 if wrong_start == name else 0)}\n{size // 512}\n{size}\n'
                if f'head -c ' in cmd and f'/by-name/{name} ' in cmd:
                    return ('0' * 64 if wrong_readback == name else outputs[module.PARTITIONS[name][0]]['sha256']) + '  -'
            raise AssertionError(cmd)
        def run(args, *, stdin, check):
            cmd = args[-1]
            assert cmd.startswith('dd of=/dev/block/by-name/')
            target = cmd.split('/by-name/')[1].split()[0]
            assert target in module.PARTITIONS
            assert stdin.read() == (target + '\n').encode() * 16
            writes.append(target)
        argv = ['installer', '--directory', str(directory), flag]
        failed = False
        with patch.object(sys, 'argv', argv), patch.object(module.subprocess, 'check_output', side_effect=output), patch.object(module.subprocess, 'run', side_effect=run), contextlib.redirect_stdout(io.StringIO()):
            try:
                module.main()
            except SystemExit:
                failed = True
        assert failed == expect_failure
        return writes, reads

    assert case('--check')[0] == []
    assert case('--root')[0] == ['macosroot']
    assert case('--boot')[0] == ['boot']
    assert case('--esp')[0] == ['esp']
    assert case('--repair')[0] == ['esp', 'boot']
    assert case('--all')[0] == ['macosroot', 'esp', 'boot']
    assert case('--repair', wrong_start='esp', expect_failure=True)[0] == []
    assert case('--repair', wrong_readback='esp', expect_failure=True)[0] == ['esp']
    assert case('--all', wrong_start='boot', expect_failure=True)[0] == []
    assert case('--all', wrong_readback='macosroot', expect_failure=True)[0] == ['macosroot']
    (directory / 'boot.img').write_bytes(b'corrupt')
    assert case('--all', expect_failure=True)[0] == []
print('PASS: real installer rejects wrong GPT/hash before writes; readback failure prevents boot write; check mode writes nothing')
