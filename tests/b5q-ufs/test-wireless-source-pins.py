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
