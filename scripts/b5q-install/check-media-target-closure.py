#!/usr/bin/env python3
"""Inspect all actual P4 objects against the accepted kernel and each other."""
import argparse,ast,collections,hashlib,importlib.util,json,struct,subprocess,sys,tempfile
from pathlib import Path
R=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(R/'UniXNU-b5q/scripts'),str(R/'sources/UniXNU/kits/XnuPrelink')]
from b5q_abi import object_symbols,object_vtable,macho
from kc_image import Image
spec=importlib.util.spec_from_file_location('pac',R/'scripts/b5q-install/check-proctop-pac.py')
pac=importlib.util.module_from_spec(spec);spec.loader.exec_module(pac)
parser=argparse.ArgumentParser();parser.add_argument('--ci',type=Path);parser.add_argument('--esp',type=Path);parser.add_argument('--out',type=Path);a=parser.parse_args()
out=R/'artifacts/b5q-p4-work/target'
if a.ci:
    assert a.esp and a.out
    manifest,=a.ci.rglob('media-build.json');out=manifest.parent
    build=json.loads(manifest.read_text());objects={}
    for name,digest in build['objects'].items():
        path=out/Path(name).name;assert path.is_file()and hashlib.sha256(path.read_bytes()).hexdigest()==digest
        objects[str(path)]=digest
    usb,=a.ci.rglob('board-input/B5qUsbBoard.o');objects[str(usb)]=hashlib.sha256(usb.read_bytes()).hexdigest()
    receipt=dict(passed=True,objects=objects)
else:receipt=json.loads((out/'report.json').read_text())
assert receipt['passed'];paths=[Path(p)for p in receipt['objects']]
assert len(paths)==35 and {'udivti3.o','udivmodti4.o','ShengAudioReach.o','ShengGpr.o','AudioProbe.o','ShengAudioService.late.o','B5qAudioBoard.o','B5qAudioDma.o'}<={p.name for p in paths},'Current P4A/ADSP/Iris/TDM encoder recipe must be complete'
def unused_auth_declarations(path,scan):
    # Apple clang emits unused weak l_<name>.ptrauth nlist declarations next
    # to the *referenced*, authenticated $auth_ptr. They carry no relocation.
    # Classify only this proven metadata shape; never excuse a weak call.
    raw=path.read_bytes();headers=macho(raw);referenced=set()
    for seg in headers['segments']:
        for sec in seg['sections']:
            off,count=struct.unpack_from('<II',raw,sec['command_offset']+56)
            for i in range(count):
                _,bits=struct.unpack_from('<II',raw,off+8*i)
                if bits>>27&1:referenced.add(scan['symbols'][bits&0xffffff][0])
    st=next(at for cmd,at,_ in headers['commands']if cmd==2)
    sy,count,_,_=struct.unpack_from('<4I',raw,st+8);rows=[]
    defined={n for n,_,kind in scan['symbols']if kind&14}
    for i,(name,_,kind)in enumerate(scan['symbols']):
        if kind!=1 or not(name.startswith('l_')and name.endswith('.ptrauth')):continue
        _,_,_,description,_=struct.unpack_from('<IBBHQ',raw,sy+16*i)
        target=name[1:-len('.ptrauth')]
        assert description&0x40 and name not in referenced,(path,name,'not unused weak compiler metadata')
        assert any(n.startswith('l'+target+'$auth_ptr$')for n in defined),(path,name,'no real auth pointer')
        assert target in referenced and scan['signed'].get(target),(path,name,'real function lacks authenticated relocation')
        rows.append(dict(object=str(path),declaration=name,target=target,external_relocations=0,
            actual_target_auth_relocations=scan['signed'][target]))
    return rows
scans={p:pac.scan(p)for p in paths};owners=collections.defaultdict(list);imports=set()
auth_metadata=[row for p,scan in scans.items()for row in unused_auth_declarations(p,scan)]
metadata_names={row['declaration']for row in auth_metadata}
for p,scan in scans.items():
    assert hashlib.sha256(p.read_bytes()).hexdigest()==receipt['objects'][str(p)]
    for name,_,kind in scan['symbols']:
        if not kind&1:continue
        if kind&14:owners[name].append(p.name)
        else:imports.add(name)
duplicates={n:ps for n,ps in owners.items()if len(ps)>1};assert not duplicates,duplicates
with tempfile.TemporaryDirectory(prefix='b5q-media-core-')as td:
    kernel=Path(td)/'kernel'
    subprocess.run(['mcopy','-i',str(a.esp or R/'artifacts/b5q-p1-work/ci45167257160/esp.img'),
        '::/EFI/UniXNU/Payloads/kernel.macho',str(kernel)],check=True)
    data=kernel.read_bytes();outer=Image(data);core=Image(data,outer.entries['com.apple.kernel'][1])
    symbols={n:v for v,names in core.symbols().items()for n in names}
    assert all(row['target']in symbols or row['target']in owners for row in auth_metadata)
    missing=sorted(imports-set(symbols)-set(owners)-metadata_names);assert not missing,missing
    tables=[]
    for obj,local,base in [
        ('B5qDaily.late.o','__ZTV10B5qBattery','__ZTV15IOPMPowerSource'),
        ('B5qBacklight.late.o','__ZTV12B5qBacklight','__ZTV9IOService'),
        ('ShengAudioService.late.o','__ZTV10ShengAudio','__ZTV9IOService'),
        ('ShengAudioService.late.o','__ZTV20ShengAudioUserClient','__ZTV12IOUserClient'),
        ('VtParavirt.late.o','__ZTV41AppleVideoToolboxParavirtualizationDriver','__ZTV9IOService'),
        ('VtParavirt.late.o','__ZTV45AppleVideoToolboxParavirtualizationUserClient','__ZTV12IOUserClient')]:
        raw=next(p for p in paths if p.name==obj).read_bytes();syms=object_symbols(raw)
        start=next(v for n,v,k in syms if n==local)
        end=min(v for n,v,k in syms if n.startswith('__ZTV')and v>start and k!=1)
        count=(end-start)//8-2;table=object_vtable(raw,syms,local,count)
        while table and table[-1]is None:table.pop();count-=1
        original=struct.unpack('<'+'Q'*count,core.read(symbols[base]+16,count*8))
        mismatch=[i for i,(entry,previous)in enumerate(zip(table,original))
            if not entry or entry[1]>>32&65535!=previous>>32&65535]
        assert not mismatch,(obj,base,mismatch)
        tables.append(dict(object=obj,local=local,base=base,slots=count,PAC_match=True))
    for p,scan in scans.items():
        values={}
        for ins in scan['instructions']:
            op=ins.op_str.replace(' ','').split(',')
            if ins.mnemonic in ('mov','movz','movn','movk')and len(op)>1 and op[1].startswith('#'):
                reg='x'+op[0][1:];v=int(op[1][1:],0);shift=int(op[2].removeprefix('lsl#'),0)if len(op)>2 else 0
                values[reg]=((values.get(reg,0)&~(65535<<shift))|v<<shift)if ins.mnemonic=='movk'else ~(v<<shift)if ins.mnemonic=='movn'else v<<shift
                assert not 0x15000000<=values[reg]<0x150d0000,(p.name,ins.address,ins.op_str)
            elif ins.mnemonic in ('bl','blr','blraa','braa','ret','retab')or ins.mnemonic.startswith('b.'):values.clear()
        assert not any(any(word in n for word in ('smmu_plan_bypass','smmu_configure_bypass','qcom_iris_mmu','sm8550_apps_smmu_pick'))for n,_,_ in scan['symbols'])
    result=dict(passed=True,hardware_verified=False,objects=receipt['objects'],imports=len(imports),
        missing=[],duplicates={},unused_auth_declarations=auth_metadata,vtable_PAC=tables,apps_smmu_materializations=0,
        original_core_sha256=hashlib.sha256(data).hexdigest(),
        exact_IOUserClient2022_legacy_guard=True,
        status='P4 objects only; audio transport/HAL, startup, full callback audit and CI/image remain required')
    (a.out or out/'media-symbol-vtable-closure.json').write_text(json.dumps(result,indent=2)+'\n')
print('PASS',len(paths),'P4objects: native symbols/duplicates,6vtablesPAC,zeroEL1apps_smmu; fullP4integration stillpending')
