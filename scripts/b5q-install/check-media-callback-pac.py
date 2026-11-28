#!/usr/bin/env python3
"""Match every defined P4 callback with its source-selected authenticated caller."""
import argparse,bisect,collections,hashlib,importlib.util,json,re,subprocess,sys
from pathlib import Path
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
R=Path(__file__).resolve().parents[2];sys.path[:0]=[str(R/'UniXNU-b5q/scripts'),str(R/'sources/UniXNU/kits/XnuPrelink')]
from kc_image import Image
s=importlib.util.spec_from_file_location('pac',R/'scripts/b5q-install/check-proctop-pac.py');pac=importlib.util.module_from_spec(s);s.loader.exec_module(pac)
parser=argparse.ArgumentParser();parser.add_argument('--ci',type=Path);parser.add_argument('--out',type=Path);parser.add_argument('--dp',action='store_true');parser.add_argument('--hid',type=Path,help='Verify newly scheduled HID timers/actions against the actual core');a=parser.parse_args()
out=R/'artifacts/b5q-p4-work/target'
if a.ci:
    manifest,=a.ci.rglob('media-build.json');out=manifest.parent;build=json.loads(manifest.read_text());objects={}
    for name,digest in build['objects'].items():
        path=out/Path(name).name;assert path.is_file()and hashlib.sha256(path.read_bytes()).hexdigest()==digest
        objects[str(path)]=digest
    usb,=a.ci.rglob('board-input/B5qUsbBoard.o');objects[str(usb)]=hashlib.sha256(usb.read_bytes()).hexdigest()
    receipt=dict(passed=True,objects=objects)
else:receipt=json.loads((out/'report.json').read_text())
assert receipt['passed'];paths=[Path(p)for p in receipt['objects']]
if a.dp:
    if a.ci:
        dp_manifest,=a.ci.rglob('dp-build.json');dp=json.loads(dp_manifest.read_text())
        extra={str(dp_manifest.parent/Path(n).name):digest for n,digest in dp['objects'].items()}
    else:
        dp=json.loads((R/'artifacts/b5q-p5-work/target/report.json').read_text())
        extra={n:d for n,d in dp['actual_objects'].items()if Path(n).name in ('B5qDpLink.o','B5qDpIrq.o','B5qDpDisplay.late.o')}
    assert len(extra)==3
    receipt['objects'].update(extra);paths+=[Path(n)for n in extra]
baseline=a.ci or R/'artifacts/b5q-p3-work/ci45261064321'
arm,=baseline.rglob('ArmCpu.o');geni,=baseline.rglob('GeniI2c.o');native,=baseline.rglob('mach.development.bcm2837.unstripped.noctf')
allpaths=paths+[arm,geni];scans={p.name:pac.scan(p)for p in allpaths};assert len(scans)==len(allpaths)
for p in paths:assert hashlib.sha256(p.read_bytes()).hexdigest()==receipt['objects'][str(p)]
def owner(scan,site):
    lows=[i.address for i in scan['instructions']];assert lows
    candidates=sorted((value,name)for name,value,kind in scan['symbols']if kind&14 and min(lows)<=value<=site and name.startswith('_') and not name.endswith('auth_ptr'))
    return candidates[-1][1]if candidates else '?'
def calls(instructions,object_name,lookup):
    values={};found=[]
    for ins in instructions:
        op=ins.op_str.replace(' ','').split(',')
        if ins.mnemonic in ('mov','movz','movn','movk')and len(op)>1:
            reg='x'+op[0][1:]
            if op[1].startswith('#'):
                value=int(op[1][1:],0);shift=int(op[2].removeprefix('lsl#'),0)if len(op)>2 else 0
                values[reg]=((values.get(reg,0)&~(65535<<shift))|value<<shift)if ins.mnemonic=='movk'else ~(value<<shift)if ins.mnemonic=='movn'else value<<shift
            elif op[1]in values:values[reg]=values[op[1]]
            else:values.pop(reg,None)
        if ins.mnemonic in ('blraa','braa')and len(op)==2 and op[1]in values:
            found.append(dict(object=object_name,site=hex(ins.address),diversity=values[op[1]]&65535,function=lookup(ins.address)))
        # Never propagate constants across calls/control transfers.
        if ins.mnemonic in ('ret','retab','bl','blr','blraa','braa','b'):values.clear()
    return found
consumers=collections.defaultdict(list)
for name,scan in scans.items():
    for call in calls(scan['instructions'],name,lambda at,s=scan:owner(s,at)):consumers[call['diversity']].append(call)
raw=native.read_bytes();core=Image(raw);symbols={n:v for v,names in core.symbols().items()for n in names};starts=sorted(set(symbols.values()))
dec=Cs(CS_ARCH_ARM64,CS_MODE_ARM);dec.skipdata=True
core_groups={}
for name,va in symbols.items():
    if not(name in ('_sysctl_register_oid_locked','_sysctl_unregister_oid','_sysctl_root') or any(needle in name for needle in ('call_continuation','Call_continuation','IOTimerEventSource','IOWorkLoop'))):continue
    nxt=bisect.bisect_right(starts,va)
    if nxt==len(starts):continue
    end=starts[nxt]
    if end-va>65536:continue
    try:ins=list(dec.disasm(core.read(va,end-va),va))
    except ValueError:continue
    core_groups[name]=ins
    for c in calls(ins,'native-core',lambda at,n=name:n):consumers[c['diversity']].append(c)
# The IOTimerEventSource API deliberately resigns its typed callback into the
# stored variadic IOEventSource action. Verify both sides of that conversion.
timer_name='__ZN18IOTimerEventSource4initEP8OSObjectPFvS1_PS_E';ins=core_groups[timer_name]
for mnemonic,disc in [('autia',0x73d8),('pacia',0x7c11)]:
    assert any(i.mnemonic==mnemonic and j and ins[j-1].mnemonic=='mov'and ins[j-1].op_str=='x17, #'+hex(disc)for j,i in enumerate(ins)),(mnemonic,disc)
assert any('invokeAction'in c['function']for c in consumers[0x7c11]if c['object']=='native-core')
# sysctl_register_oid_locked authenticates the typed handler, then signs
# its oid_handler storage with a blended address discriminator. sysctl_root
# authenticates using that stored modifier; no plain0e2e BLRAA is expected.
registered=core_groups['_sysctl_register_oid_locked']
assert any(i.mnemonic=='autia'and j and registered[j-1].mnemonic=='mov'and registered[j-1].op_str=='x17, #0xe2e'for j,i in enumerate(registered))
assert any(i.mnemonic=='pacia'and i.op_str=='x16, x8'and j+1<len(registered)and registered[j+1].mnemonic=='str'and registered[j+1].op_str=='x16, [x1, #0x30]'for j,i in enumerate(registered))
assert any(i.mnemonic=='blraa'and i.op_str=='x22, x19'for i in core_groups['_sysctl_root'])

def selected(obj,name):
    # Every branch follows the callback field in the pinned production source.
    # Never satisfy a callback with an unrelated caller that shares its type.
    if obj=='B5qDpLink.o':
        if 'Owner5frame'in name:return [('B5qDpIrq.o','Irq6worker')]
        return [('B5qDpDisplay.late.o','opaque411_228909'if'Owner7present'in name else'disconnect')]
    if obj=='B5qDpIrq.o':return [('ArmCpu.o','interrupt')]if'primary'in name else[('native-core','continuation')]
    if obj=='B5qDpDisplay.late.o':
        if 'fenceFired'in name:return [('timer-resign','')]
        if '__invoke'in name:return [('native-core','IOWorkLoop')]
    if obj=='B5qDaily.late.o' or re.search(r'(Thread|Worker|Main|irqThread|workThread|eventThread)EPvi$',name):
        return [('native-core','continuation')]
    if obj=='B5qBacklight.late.o'and '4tickE'in name:return [('timer-resign','')]
    if obj=='B5qAudioBoard.o':return [('GeniI2c.o','_geni_i2c_')]
    if obj=='AudioProbe.o':return [('AdspProbe.o','clientReceive'if 'dspReceive'in name else'clientState')]
    if obj=='B5qUsbBoard.o':return [('GeniI2c.o','_geni_i2c_')]
    if obj=='AdspProbe.o':
        for needle,target,prefix in [('fileRead','QcomMdt.o','_qcom_mdt_'),('clientReceive','QcomGlink.o','_qcom_glink_'),('clientState','QcomGlink.o','_qcom_glink_'),('ipccIrq','ArmCpu.o','interrupt'),('rscIrq','ArmCpu.o','interrupt'),('kickAop','QcomQmp.o','_qcom_qmp_'),('kickGlink','QcomGlink.o','_qcom_glink_')]:
            if needle in name:return [(target,prefix)]
    if obj=='ShengQrtr.o':
        return [('AdspProbe.o','clientReceive'if name=='_linkReceive'else'clientState')]if name in ('_linkReceive','_linkState')else[('QcomQrtr.o','_emit'if name=='_send'else'_qcom_qrtr_receive')]
    if obj=='VideoProbe.o':
        if 'fileRead'in name:return [('QcomMdt.o','_qcom_mdt_')]
        if 'ccRead'in name or 'ccWrite'in name:return [('Sm8550VideoCc.o','_sm8550_video_cc_')]
        if 'primary'in name:return [('ArmCpu.o','interrupt')]
        return [('IrisCore.o',''),('IrisVpu.o','')]
    if obj=='IrisMedia.o':return [('IrisSession.o','')]
    if obj=='VtHost.o'and'mediaSink'in name:return [('IrisMedia.o','eventThread')]
    if obj=='VtParavirt.late.o':
        if 'vt_paravirt_sysctl'in name:return [('sysctl-resign','')]
        if 'sendToGuest'in name:return [('VtHost.o','')]
    if obj=='iris_vpu_buffer.o'and name.startswith('_iris_vpu'):return [('iris_vpu_buffer.o','_iris_vpu')]
    raise AssertionError(('Callback lacks source route',obj,name))
contracts=[]
for path in paths:
    scan=scans[path.name];defined={n for n,_,kind in scan['symbols']if kind&14}
    for name,sites in scan['signed'].items():
        if name not in defined:continue
        sites=[v for v in sites if not v['address_diversity']]
        if not sites:continue
        routes=selected(path.name,name)
        for site in sites:
            assert site['key']==0 and not site['address_diversity'],(name,site)
            if routes==[('timer-resign','')]:
                assert site['diversity']==0x73d8
                matches=[dict(object='native-core',function=timer_name,typed_auth='0x73d8',stored_resign='0x7c11')]
            elif routes==[('sysctl-resign','')]:
                assert site['diversity']==0xe2e
                matches=[dict(object='native-core',function='_sysctl_register_oid_locked -> _sysctl_root',typed_auth='0xe2e',stored_resign='oid_handler address/name blend; field+0x30')]
            else:
                matches=[c for c in consumers[site['diversity']]if any(c['object']==obj and needle in c['function']for obj,needle in routes)]
            assert matches,(path.name,name,hex(site['diversity']),routes,[c for c in consumers[site['diversity']]if any(c['object']==obj for obj,_ in routes)])
            contracts.append(dict(producer=path.name,callback=name,signature=site,source_selected_routes=routes,authenticated_consumers=matches))
assert len(contracts)>=100,'Missing selected module callbacks'
if a.hid:
    hid=pac.scan(a.hid)
    for part in ['9clickTick','4tick','10stopAction','11touchAction','13buttonsAction']:
        names=[n for n in hid['signed']if '__ZN14NativeHidInput'+part+'E'in n];assert len(names)==1,(part,names)
        name=names[0];sites=hid['signed'][name]
        for site in sites:
            div=0x73d8 if part in ['9clickTick','4tick']else 0xbd41
            assert site['key']==0 and site['diversity']==div and not site['address_diversity']
            matches=([dict(object='native-core',function=timer_name,typed_auth='0x73d8',stored_resign='0x7c11')]
                if div==0x73d8 else [c for c in consumers[div]if c['object']=='native-core'and 'IOWorkLoop'in c['function']])
            assert matches,(part,hex(div))
            contracts.append(dict(producer='NativeHidInput.o',callback=name,signature=site,authenticated_consumers=matches))
    receipt['objects'][str(a.hid)]=hid['sha256']
result=dict(passed=True,hardware_verified=False,contracts=contracts,objects=receipt['objects'],
    baseline_objects={p.name:hashlib.sha256(p.read_bytes()).hexdigest()for p in [arm,geni,native]},
    scope='All defined non-vtable P4 callbacks in current35object recipe; 6 base vtables checked separately; full audio/runtime/CI remains pending')
(a.out or out/'media-callback-pac.json').write_text(json.dumps(result,indent=2)+'\n')
print('PASS',len(contracts),'actual P4callback signatures matched source-selected authenticated callers, including native thread/sysctl and timer resigning')
