#!/usr/bin/env python3
"""Run shared H4/IBS and original btqca with actual WCN6855 selection.

The shared controller fixture is adapted only at the simulated radio's identity,
firmware names and expected fallback count. Production Linux is byte-identical.
"""
import importlib.util,os,subprocess,tempfile
from pathlib import Path
R=Path(__file__).resolve().parents[2];C=R/'sources/UniXNU-sheng/drivers/QcaBluetooth'
spec=importlib.util.spec_from_file_location('bt_recipe',R/'UniXNU-b5q/scripts/b5q_bluetooth.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
with tempfile.TemporaryDirectory(prefix='b5q-bt6855-') as td:
    td=Path(td);sources,include=m.prepare(C,R/'UniXNU-b5q/package',R/'sources/UniXNU-sm8550-common/kits/Sm8550Platform',td,R/'sources/UniXNU-sheng')
    text=(C/'tests/runtime.c').read_text().replace('WCN7850','WCN6855')
    text=text.replace('qca/hmtbtfw20.tlv','qca/hpbtfw21.tlv').replace('qca/hmtnv20.bin','qca/hpnv21.bin').replace('qca/hmtnv20.b1234','qca/hpnv21.b1234')
    text=text.replace('put16(response+9,0x0200)','put16(response+9,0x0201)').replace('put32(response+11,0x400c0200)','put32(response+11,0x400c0201)')
    text=text.replace('info.rom==0x0200','info.rom==0x0201')
    # Linux first tries wcnhp*; the real Samsung package provides hp*.
    text=text.replace('f->firmware_gets++;','f->firmware_gets++;\n    if(!strncmp(name,"qca/wcn",7))return -ENOENT;')
    # Board-specific NVM is deliberately absent in this fixture: the original
    # btqca selects a generic file only when its discovered board ID is 0.
    text=text.replace('f->board_specific=true;','f->board_specific=false;')
    text=text.replace('f->firmware_gets==3','f->firmware_gets==4')
    fixture=td/'runtime.c';fixture.write_text(text)
    command=[os.environ.get('CC','cc'),'-std=c11','-g','-O1','-Wno-sign-compare','-fsanitize=address,undefined',
        *['-I'+str(p) for p in include],str(C/'src/qbt_core.c'),str(td/'qbt_linux.c'),str(C/'out/linux/btqca.c'),str(fixture),'-o',str(td/'test')]
    subprocess.run(command,check=True);subprocess.run([str(td/'test')],check=True)
