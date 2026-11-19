#!/usr/bin/env python3
"""Bind four original macOS PMGR entry points without altering original code."""
import json,os,subprocess,tomllib
from pathlib import Path
from b5q_compile import ROOT,compile
from kernel_target import TRIPLE
out=ROOT/'build/ram-block';fixture=json.loads(Path(__file__).with_name('pmgr-26C5035r.json').read_text());profile=tomllib.loads(Path(os.environ['UNIXNU_OS_PROFILE']).read_text())
if fixture['kernelcache_sha256']!=profile['kernel']['prelink']['kernelcache_sha256']:raise SystemExit('PMGR fixture/profile mismatch')
text='.text\n.p2align 2\n';addresses='';slide=int(fixture['collection_slide'],16)
for key,r in fixture['bindings'].items():
 name='_b5q_original_pmgr_'+key;target=int(r['address'],16)+slide
 text+=f'.globl {name}\n{name}:\n bti c\n b {name}.original\n';addresses+=f'.globl {name}.original\n.set {name}.original, {target:#x}\n'
objects=[compile(ROOT/'kits/b5q/B5qPmgr.cpp',out/'B5qPmgr.o')]
for stem,source in [('pmgr-bindings',text),('pmgr-addresses',addresses)]:
 path=out/(stem+'.S');path.write_text(source);obj=out/(stem+'.o');subprocess.run(['xcrun','clang','-target',TRIPLE,'-c',str(path),'-o',str(obj)],check=True);objects.append(obj)
print(json.dumps([str(o) for o in objects]))
