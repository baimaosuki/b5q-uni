#!/usr/bin/env python3
"""Inspect all actual P4 objects against the accepted kernel and each other."""
import collections,hashlib,importlib.util,json,struct,subprocess,sys,tempfile
from pathlib import Path
R=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(R/'UniXNU-b5q/scripts'),str(R/'sources/UniXNU/kits/XnuPrelink')]
from b5q_abi import object_symbols,object_vtable
from kc_image import Image
spec=importlib.util.spec_from_file_location('pac',R/'scripts/b5q-install/check-proctop-pac.py')
pac=importlib.util.module_from_spec(spec);spec.loader.exec_module(pac)
out=R/'artifacts/b5q-p4-work/target'
receipt=json.loads((out/'report.json').read_text());assert receipt['passed']
paths=[Path(p)for p in receipt['objects']]
assert len(paths)==35 and {'udivti3.o','udivmodti4.o','ShengAudioReach.o','ShengGpr.o','AudioProbe.o','ShengAudioService.late.o','B5qAudioBoard.o','B5qAudioDma.o'}<={p.name for p in paths},'Current P4A/ADSP/Iris/TDM encoder recipe must be complete'
scans={p:pac.scan(p)for p in paths};owners=collections.defaultdict(list);imports=set()
for p,scan in scans.items():
    assert hashlib.sha256(p.read_bytes()).hexdigest()==receipt['objects'][str(p)]
    for name,_,kind in scan['symbols']:
        if not kind&1:continue
        if kind&14:owners[name].append(p.name)
        else:imports.add(name)
duplicates={n:ps for n,ps in owners.items()if len(ps)>1};assert not duplicates,duplicates
with tempfile.TemporaryDirectory(prefix='b5q-media-core-')as td:
    kernel=Path(td)/'kernel'
    subprocess.run(['mcopy','-i',str(R/'artifacts/b5q-p1-work/ci45167257160/esp.img'),
        '::/EFI/UniXNU/Payloads/kernel.macho',str(kernel)],check=True)
    data=kernel.read_bytes();outer=Image(data);core=Image(data,outer.entries['com.apple.kernel'][1])
    symbols={n:v for v,names in core.symbols().items()for n in names}
    missing=sorted(imports-set(symbols)-set(owners));assert not missing,missing
    tables=[]
    for obj,local,base in [
        ('B5qDaily.late.o','__ZTV10B5qBattery','__ZTV15IOPMPowerSource'),
        ('B5qBacklight.late.o','__ZTV12B5qBacklight','__ZTV9IOService'),
        ('ShengAudioService.late.o','__ZTV10ShengAudio','__ZTV9IOService'),
        ('ShengAudioService.late.o','__ZTV20ShengAudioUserClient','__ZTV12IOUserClient'),
        ('VtParavirt.late.o','__ZTV41AppleVideoToolboxParavirtualizationDriver','__ZTV9IOService'),
        ('VtParavirt.late.o','__ZTV45AppleVideoToolboxParavirtualizationUserClient','__ZTV12IOUserClient')]:
        raw=(out/obj).read_bytes();syms=object_symbols(raw)
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
        missing=[],duplicates={},vtable_PAC=tables,apps_smmu_materializations=0,
        original_core_sha256=hashlib.sha256(data).hexdigest(),
        exact_IOUserClient2022_legacy_guard=True,
        status='P4 objects only; audio transport/HAL, startup, full callback audit and CI/image remain required')
    (out/'media-symbol-vtable-closure.json').write_text(json.dumps(result,indent=2)+'\n')
print('PASS',len(paths),'P4objects: native symbols/duplicates,6vtablesPAC,zeroEL1apps_smmu; fullP4integration stillpending')
