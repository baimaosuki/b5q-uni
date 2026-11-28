#!/usr/bin/env python3
"""Inspect actual P4A vtables/callbacks/imports against the accepted core."""
import hashlib,importlib.util,json,struct,subprocess,sys,tempfile
from pathlib import Path
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
R=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(R/'UniXNU-b5q/scripts'),str(R/'sources/UniXNU/kits/XnuPrelink')]
from b5q_abi import object_symbols,object_vtable
from kc_image import Image
spec=importlib.util.spec_from_file_location('pac',R/'scripts/b5q-install/check-proctop-pac.py')
pac=importlib.util.module_from_spec(spec);spec.loader.exec_module(pac)
out=R/'artifacts/b5q-p4-work/target'
paths=[out/n for n in ['B5qDaily.late.o','B5qBacklight.late.o','B5qUsbBoard.o']]
exports={n for p in paths for n,_,kind in object_symbols(p.read_bytes())if kind!=1}
imports={n for p in paths for n,_,kind in object_symbols(p.read_bytes())if kind==1}
with tempfile.TemporaryDirectory(prefix='b5q-p4-abi-')as td:
    p=Path(td)/'kernel'
    subprocess.run(['mcopy','-i',str(R/'artifacts/b5q-p1-work/ci45167257160/esp.img'),
        '::/EFI/UniXNU/Payloads/kernel.macho',str(p)],check=True)
    raw=p.read_bytes();outer=Image(raw);core=Image(raw,outer.entries['com.apple.kernel'][1])
    symbols={n:v for v,names in core.symbols().items()for n in names}
    assert not imports-exports-set(symbols),sorted(imports-exports-set(symbols))
    tables=[]
    for obj,local,base in [('B5qDaily.late.o','__ZTV10B5qBattery','__ZTV15IOPMPowerSource'),
        ('B5qBacklight.late.o','__ZTV12B5qBacklight','__ZTV9IOService')]:
        data=(out/obj).read_bytes();syms=object_symbols(data)
        start=next(v for n,v,k in syms if n==local)
        end=min(v for n,v,k in syms if n.startswith('__ZTV')and v>start and k!=1)
        # clang aligns the following metaclass vtable to16B; remove only
        # trailing zero alignment, never ignore an interior missing slot.
        count=(end-start)//8-2
        table=object_vtable(data,syms,local,count)
        while table and table[-1]is None:table.pop();count-=1
        original=struct.unpack('<'+'Q'*count,core.read(symbols[base]+16,count*8))
        assert all(item and item[1]>>32&65535==old>>32&65535 for item,old in zip(table,original))
        tables.append(dict(object=obj,base=base,slots=count,diversities_match=True))
    decoder=Cs(CS_ARCH_ARM64,CS_MODE_ARM);decoder.skipdata=True
    starts=sorted(set(symbols.values()))
    def core_calls(name):
        start=symbols[name];end=min(v for v in starts if v>start)
        ins=list(decoder.disasm(core.read(start,end-start),start));values={};calls=[]
        for i in ins:
            op=i.op_str.replace(' ','').split(',')
            if i.mnemonic in ('mov','movz')and len(op)>1 and op[1].startswith('#'):
                values['x'+op[0][1:]]=int(op[1][1:],0)
            elif i.mnemonic=='movk'and len(op)>1 and op[1].startswith('#'):
                reg='x'+op[0][1:];shift=int(op[2].removeprefix('lsl#'),0)if len(op)>2 else 0
                values[reg]=(values.get(reg,0)&~(65535<<shift))|int(op[1][1:],0)<<shift
            elif i.mnemonic in ('blraa','braa')and len(op)==2:
                calls.append(values.get(op[1],-1)&65535)
            if i.mnemonic in ('ret','retab','bl','blr','blraa','braa'):values.clear()
        return calls
    callbacks=[]
    for obj,needle,caller,diversity in [
        ('B5qDaily.late.o','batteryWorker','_kernel_thread_start',0xd507),
        ('B5qDaily.late.o','lidWorker','_kernel_thread_start',0xd507),
        ('B5qBacklight.late.o','4tick','__ZN18IOTimerEventSource4initEP8OSObjectPFvS1_PS_E',0x73d8)]:
        scan=pac.scan(out/obj)
        found=[v for n,sites in scan['signed'].items()if needle in n for v in sites]
        assert found and all(v['key']==0 and v['diversity']==diversity and not v['address_diversity']for v in found)
        consumers=core_calls(caller)
        # kernel_thread_start forwards the signed continuation; Arm64's
        # actual call_continuation authenticates it in the assembly switch.
        if diversity==0xd507:
            cswitch=pac.scan(R/'artifacts/b5q-batch2-work/proctop-pac/cswitch.o')if (R/'artifacts/b5q-batch2-work/proctop-pac/cswitch.o').exists()else None
            if not cswitch:
                matches=list((R/'artifacts').glob('*/**/cswitch.o'))
                assert matches;cswitch=pac.scan(matches[0])
            assert any(c['diversity']==diversity for c in cswitch['calls'])
        else:
            # IOTimerEventSource::init authenticates its typed Action then
            # resigns to the stored IOEventSource variadic Action. Follow
            # that real conversion through invokeAction, not timeout's
            # unrelated virtual work-loop calls.
            start=symbols[caller];end=min(v for v in starts if v>start)
            ins=list(decoder.disasm(core.read(start,end-start),start))
            assert any(i.mnemonic=='autia'and j and ins[j-1].mnemonic=='mov'and
                ins[j-1].op_str=='x17, #0x73d8'for j,i in enumerate(ins))
            assert any(i.mnemonic=='pacia'and j and ins[j-1].mnemonic=='mov'and
                ins[j-1].op_str=='x17, #0x7c11'for j,i in enumerate(ins))
            assert 0x7c11 in core_calls('__ZN18IOTimerEventSource12invokeActionEPFvP8OSObjectzEPS_S1_P10IOWorkLoop')
        callbacks.append(dict(object=obj,callback=needle,diversity=hex(diversity),caller=caller))
    for path in paths:
        scan=pac.scan(path);values={}
        for ins in scan['instructions']:
            operands=ins.op_str.replace(' ','').split(',')
            if ins.mnemonic in ('mov','movz','movn','movk')and len(operands)>1 and operands[1].startswith('#'):
                reg='x'+operands[0][1:];value=int(operands[1][1:],0)
                shift=int(operands[2].removeprefix('lsl#'),0)if len(operands)>2 else 0
                values[reg]=((values.get(reg,0)&~(65535<<shift))|value<<shift)if ins.mnemonic=='movk'else ~(value<<shift)if ins.mnemonic=='movn'else value<<shift
                assert not 0x15000000<=values[reg]<0x150d0000,(path,ins.address)
            elif ins.mnemonic in ('ret','retab','bl','blr','blraa','braa')or ins.mnemonic.startswith('b.'):values.clear()
        assert not any('smmu'in name.lower()for name,_,_ in scan['symbols'])
    (out/'abi.json').write_text(json.dumps(dict(passed=True,hardware_verified=False,
        missing_symbols=[],imports=len(imports),vtables=tables,callbacks=callbacks,
        apps_smmu_materializations=0,objects={p.name:hashlib.sha256(p.read_bytes()).hexdigest()for p in paths},
        core_sha256=hashlib.sha256(raw).hexdigest(),full_P4_status='incomplete; audio/video/integration/CI pending'),indent=2)+'\n')
print('PASS P4A complete vtable/callback PAC,closed imports and zero apps_smmu')
