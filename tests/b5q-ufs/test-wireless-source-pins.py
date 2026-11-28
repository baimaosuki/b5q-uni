#!/usr/bin/env python3
"""A moving release ref must not replace the production dependency commit."""
from pathlib import Path
import subprocess,sys,tempfile
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'UniXNU-b5q/scripts'))
from b5q_wireless import checkout
def git(path,*args):return subprocess.check_output(['git','-C',str(path),*args],stderr=subprocess.DEVNULL,text=True).strip()
with tempfile.TemporaryDirectory(prefix='b5q-wireless-source-pins-')as td:
    td=Path(td);remote=td/'remote';remote.mkdir();git(remote,'init','-q')
    git(remote,'config','user.email','source-test@example.invalid');git(remote,'config','user.name','Source fixture')
    (remote/'sys/sys').mkdir(parents=True);header=remote/'sys/sys/types.h';header.write_text('locked\n')
    git(remote,'add','.');git(remote,'commit','-qm','locked');locked=git(remote,'rev-parse','HEAD')
    header.write_text('moving-tip\n');git(remote,'commit','-qam','moving tip');moved=git(remote,'rev-parse','HEAD')
    git(remote,'branch','releng/15.1');tree=td/'tree'
    path=checkout(tree,'dependency',str(remote),locked,['/sys/sys/'])
    assert git(path,'rev-parse','HEAD')==locked and (path/'sys/sys/types.h').read_text()=='locked\n'
    assert checkout(tree,'dependency',str(remote),locked,['/sys/sys/'])==path
    path=checkout(tree,'dependency',str(remote),moved,['/sys/sys/'])
    assert git(path,'rev-parse','HEAD')==moved
    (path/'sys/sys/types.h').write_text('local-edit\n')
    try:checkout(tree,'dependency',str(remote),locked,['/sys/sys/'])
    except ValueError as e:assert 'preserve checkout'in str(e)
    else:raise AssertionError('dirty source silently discarded')
    assert git(path,'rev-parse','HEAD')==moved and (path/'sys/sys/types.h').read_text()=='local-edit\n'
print('PASS production source checkout: exact commit over moving ref, sparse import, idempotence, clean update, dirty source preserved/rejected')
# CI places the independent component and the sheng reference next to each
# other. The header directory must not be inferred from component parents.
from b5q_bluetooth import prepare as bluetooth_sources
with tempfile.TemporaryDirectory(prefix='b5q-wireless-CI-layout-')as td:
    td=Path(td);cache=td/'tree/.cache/b5q-wireless';cache.mkdir(parents=True)
    component=cache/'QcaBluetooth';component.symlink_to(R/'sources/UniXNU-sheng/drivers/QcaBluetooth',target_is_directory=True)
    reference=cache/'UniXNU-sheng';reference.symlink_to(R/'sources/UniXNU-sheng',target_is_directory=True)
    sources,include=bluetooth_sources(component,R/'UniXNU-b5q/package',R/'sources/UniXNU-sm8550-common/kits/Sm8550Platform',td/'out',reference)
    assert reference/'package'in include and component.parents[1]/'package'not in include
    assert all(p.is_dir()for p in include)
    src=td/'headers.c';src.write_text('#include "QcomQmp.h"\n#include "QcomScm.h"\nQcomQmp peer;\n')
    subprocess.run(['cc','-std=c11','-Werror',*[v for p in include for v in ['-I',str(p)]],'-c',str(src),'-o',str(td/'headers.o')],check=True)
print('PASS production Bluetooth recipe with actual CI sibling-cache layout:explicit lockedreference supplies QMP/SCM headers')
