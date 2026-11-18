#!/usr/bin/env python3
"""Run the pinned actual RamBlock host tests in a disposable copy, never hardware."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--source', required=True, type=Path)
p.add_argument('--output', required=True, type=Path)
p.add_argument('--cxx', default=os.environ.get('CXX', 'c++'))
a = p.parse_args()
source, out = a.source.resolve(), a.output.resolve()
out.mkdir(parents=True, exist_ok=True)
report = dict(scope='host algorithm tests only', phone_ufs_enabled=False,
              ramblock_hardware_gate_passed=False, tests=[], source_sha256={})
with tempfile.TemporaryDirectory(prefix='b5q-ramblock-') as tmp:
    tree = Path(tmp)/'RamBlock'
    shutil.copytree(source, tree, ignore=shutil.ignore_patterns('.git'))
    sparse = tree/'Test/sparse.cpp'
    before = sparse.read_text()
    header = (tree/'SparseDisk.h').read_text()
    old = 'if(which==3)put64(bad,16,0x80001000);'
    # The pinned parser explicitly supports logical images through 1 TiB.
    # Its old test still expects 2 GiB+4 KiB to be rejected. Change only the
    # disposable test input to 1 TiB+4 KiB; never weaken the parser or assert.
    if old in before and 'size>(1ULL<<40)' in header:
        sparse.write_text(before.replace(old, 'if(which==3)put64(bad,16,(1ULL<<40)+4096);'))
        report['test_correction'] = dict(file='Test/sparse.cpp',
            reason='stale 2GiB limit; parser maximum is 1TiB',
            original_sha256=hashlib.sha256(before.encode()).hexdigest(),
            corrected_sha256=hashlib.sha256(sparse.read_bytes()).hexdigest(),
            parser_modified=False, upstream_original_result='assertion failure at line 30')
    for path in sorted(source.rglob('*')):
        if path.is_file() and path.suffix in ('.cpp','.h'):
            report['source_sha256'][str(path.relative_to(source))]=hashlib.sha256(path.read_bytes()).hexdigest()
    for name in ('sparse','persist','direct','writeback','concurrent'):
        command=[a.cxx,'-std=c++17','-O1','-g','-pthread','-fsanitize=address,undefined',
                 '-fno-omit-frame-pointer',str(tree/'Test'/f'{name}.cpp'),'-o',str(out/name)]
        record=dict(name=name, command=command)
        with (out/f'{name}.log').open('w') as log:
            try:
                result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=240)
                record['compile_returncode']=result.returncode
                if not result.returncode:
                    result=subprocess.run([str(out/name)],stdout=log,stderr=subprocess.STDOUT,timeout=300)
                    record['test_returncode']=result.returncode
                record['passed']=record.get('test_returncode')==0
            except subprocess.TimeoutExpired:
                record.update(passed=False,error='timeout')
        report['tests'].append(record)
        print(name, 'PASS' if record['passed'] else 'FAIL', flush=True)
report['passed']=all(r['passed'] for r in report['tests'])
(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
raise SystemExit(0 if report['passed'] else 1)
