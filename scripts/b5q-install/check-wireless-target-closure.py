#!/usr/bin/env python3
"""Joint original-core symbol, authenticated callback and MMIO inspection."""
import collections,hashlib,importlib.util,json,struct,subprocess,sys,tempfile
from pathlib import Path
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'UniXNU-b5q/scripts'));sys.path.insert(0,str(R/'sources/UniXNU/kits/XnuPrelink'))
from b5q_abi import object_symbols,macho
from kc_image import Image
spec=importlib.util.spec_from_file_location('pac',R/'scripts/b5q-install/check-proctop-pac.py');pac=importlib.util.module_from_spec(spec);spec.loader.exec_module(pac)
out=R/'artifacts/b5q-p3-work';target=json.loads((out/'target/compile-result.json').read_text());assert target['passed']and not target['core_only']
paths=list(map(Path,target['objects']));paths+=list((out/'board-target').glob('*.o'))
bt=R/'artifacts/b5q-p2-work/target';paths+=[bt/n for n in json.loads((bt/'report.json').read_text())['objects']if n!='B5qWcnPower.o']
def calls(instructions):
    values={};result=[]
    for ins in instructions:
        operands=ins.op_str.replace(' ','').split(',')
        if ins.mnemonic in ('mov','movz','movk')and len(operands)>1:
            reg=operands[0];reg='x'+reg[1:]if reg.startswith(('x','w'))else reg
            if operands[1].startswith('#'):
                value=int(operands[1][1:],0);shift=int(operands[2].removeprefix('lsl#'),0)if len(operands)>2 else 0
                values[reg]=((values.get(reg,0)&~(65535<<shift))|value<<shift)if ins.mnemonic=='movk'else value<<shift
            elif operands[1]in values:values[reg]=values[operands[1]]
            else:values.pop(reg,None)
        if ins.mnemonic in ('blraa','braa')and len(operands)==2:
            value=values.get(operands[1]);
            if value is not None:result.append(dict(site=hex(ins.address),diversity=value&65535))
        if ins.mnemonic in ('ret','retab','bl','blr','blraa','braa','b'):values.clear()
    return result
scans={p:pac.scan(p)for p in paths};coreCalls=[]
with tempfile.TemporaryDirectory(prefix='b5q-joint-core-')as td:
    kernel=Path(td)/'kernel'
    subprocess.run(['mcopy','-i',str(R/'artifacts/b5q-p1-work/ci45167257160/esp.img'),'::/EFI/UniXNU/Payloads/kernel.macho',str(kernel)],check=True)
    raw=kernel.read_bytes();outer=Image(raw);core=Image(raw,outer.entries['com.apple.kernel'][1])
    symbols={n:v for v,names in core.symbols().items()for n in names};names=set(symbols)
    decoder=Cs(CS_ARCH_ARM64,CS_MODE_ARM);decoder.skipdata=True
    starts=sorted(set(symbols.values()))
    for name,va in symbols.items():
        if not name.startswith(('_ctl_','_proc_iterate','_thread_continue','_thread_invoke','_thread_call','_kernel_thread')):continue
        try:
            end=min((v for v in starts if v>va),default=va+4096)
            if end-va>65536:continue
            found=calls(list(decoder.disasm(core.read(va,end-va),va)))
            coreCalls.extend(dict(function=name,**call)for call in found)
        except ValueError:continue
    owners=collections.defaultdict(list);undefined=set()
    for p,scan in scans.items():
        for name,_,kind in scan['symbols']:
            if not kind&1:continue
            if kind&14:owners[name].append(str(p))
            else:undefined.add(name)
    abi=json.loads((out/'board-target/ethernet-abi.json').read_text())
    missing=sorted(undefined-names-set(owners)-set(abi['original_bindings'])-{'_boot_cpu_kick','_boot_kthread_report'})
    duplicates={n:v for n,v in owners.items()if len(v)>1}
    assert not missing and not duplicates,(missing,duplicates)
    consumers=collections.defaultdict(list)
    for p,scan in scans.items():
        for call in calls(scan['instructions']):consumers[call['diversity']].append(dict(object=str(p),**call))
    arm=pac.scan(R/'artifacts/b5q-p1-work/returned-PAC/ArmCpu.o')
    for call in calls(arm['instructions']):consumers[call['diversity']].append(dict(object='accepted P1 ArmCpu.o',**call))
    for call in coreCalls:consumers[call['diversity']].append(dict(object='accepted P1 core',**call))
    contracts=[]
    for p in [out/'board-target/B5qWifiBoard.o',bt/'B5qBluetooth.o']:
        for callback,sites in scans[p]['signed'].items():
            if not callback.startswith(('__ZN12_GLOBAL__N_','__Z11processSeen','__Z12processWatch','__enable_preemption','__disable_preemption')):continue
            for site in sites:
                assert site['key']==0 and not site['address_diversity'],(callback,site)
                targets=consumers.get(site['diversity'],[])
                assert targets,(callback,hex(site['diversity']),'no authenticated consumer')
                contracts.append(dict(producer=str(p),callback=callback,signature=site,consumers=targets))
    mmio={}
    for p,scan in scans.items():
        # Every instruction that materializes the forbidden physical aperture
        # is rejected; unlike a string search, shifted MOVK fragments count.
        values={}
        for ins in scan['instructions']:
            operands=ins.op_str.replace(' ','').split(',')
            if ins.mnemonic in ('mov','movz','movn','movk')and len(operands)>=2 and operands[1].startswith('#'):
                reg='x'+operands[0][1:];value=int(operands[1][1:],0);shift=int(operands[2].removeprefix('lsl#'),0)if len(operands)>2 else 0
                values[reg]=((values.get(reg,0)&~(65535<<shift))|value<<shift)if ins.mnemonic=='movk'else ~(value<<shift)if ins.mnemonic=='movn'else value<<shift
                assert not 0x15000000<=values[reg]<0x150d0000,(str(p),ins.address,ins.op_str)
            elif ins.mnemonic in ('ret','retab','bl','blr','blraa','braa')or ins.mnemonic.startswith('b.'):values.clear()
        assert not any('smmu_plan_bypass'in name or 'smmu_configure_bypass'in name for name,_,_ in scan['symbols'])
        mmio[str(p)]=dict(sha256=scan['sha256'],instructions=len(scan['instructions']),apps_smmu_materializations=0)
    result=dict(passed=True,hardware_verified=False,objects=len(paths),duplicate_definitions=duplicates,unresolved=missing,
        optional_weak_imports=['_boot_cpu_kick','_boot_kthread_report'],core='actual P1 CI45167257160',callback_contracts=contracts,
        zero_apps_smmu=mmio,network_vtables=abi['classes'],new_CI_binary_revalidation_required=True)
    (out/'joint-target-closure.json').write_text(json.dumps(result,indent=2)+'\n')
    print('PASS joint',len(paths),'objects; symbols/no duplicates;',len(contracts),'authenticated producer/consumer contracts; zero EL1 apps_smmu')
