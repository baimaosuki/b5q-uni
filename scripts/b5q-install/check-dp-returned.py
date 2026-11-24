#!/usr/bin/env python3
"""Check real Apple-compiled P5 objects and the paired firmware, not host stand-ins."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,struct,subprocess,sys,tempfile
R=Path(__file__).resolve().parents[2];sys.path[:0]=[str(R/'UniXNU-b5q/scripts'),str(R/'UniXNU/scripts'),str(R/'sources/UniXNU/kits/XnuPrelink')]
from b5q_abi import object_symbols,object_vtable,macho
from kc_image import Image
from unixnu.boot_template import loader_pe
spec=importlib.util.spec_from_file_location('pac',R/'scripts/b5q-install/check-proctop-pac.py');pac=importlib.util.module_from_spec(spec);spec.loader.exec_module(pac)
p=argparse.ArgumentParser(description=__doc__)
for name in ['ci','esp','fd','out']:p.add_argument('--'+name,type=Path,required=True)
a=p.parse_args();a.out.mkdir(exist_ok=True,parents=True)
def sha(p):
 with p.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
manifest,=a.ci.rglob('dp-build.json');build=json.loads(manifest.read_text());objects={}
for name,digest in build['objects'].items():
 path=manifest.parent/Path(name).name;assert path.is_file()and sha(path)==digest;objects[path]=digest
assert {p.name for p in objects}=={'B5qDpLink.o','B5qDpIrq.o','B5qDpDisplay.late.o'}
source_root=R/'artifacts/b5q-p5-work/source-check/UniXNU-b5q/package'
for name,digest in build['sources'].items():assert sha(source_root/Path(name).name)==digest,name
scans={p.name:pac.scan(p)for p in objects}
for path,digest in objects.items():
 scan=scans[path.name];values={}
 for ins in scan['instructions']:
  op=ins.op_str.replace(' ','').split(',')
  if ins.mnemonic in ('mov','movz','movk','movn')and len(op)>1 and op[1].startswith('#'):
   reg='x'+op[0][1:];imm=int(op[1][1:],0);shift=int(op[2].removeprefix('lsl#'),0)if len(op)>2 else 0
   v=(values.get(reg,0)&~(65535<<shift))|(imm<<shift)if ins.mnemonic=='movk'else ~(imm<<shift)if ins.mnemonic=='movn'else imm<<shift
   values[reg]=v&((1<<(32 if op[0].startswith('w')else 64))-1)
   assert not 0x15000000<=values[reg]<0x150d0000,(path.name,ins.address,ins.op_str)
  elif ins.mnemonic in ('ret','retab','bl','blr','blraa','braa','b')or ins.mnemonic.startswith('b.'):values.clear()
 assert not any(any(v in name for v in ['smmu_plan_bypass','smmu_configure_bypass','MmioWrite','MmioRead'])for name,_,_ in scan['symbols'])
 env=dict(__import__('os').environ,LD_LIBRARY_PATH=str(R/'tools/llvm21/usr/lib/x86_64-linux-gnu'))
 with(a.out/(path.name+'.disasm')).open('w')as log:
  subprocess.run([str(R/'tools/llvm21/usr/lib/llvm-21/bin/llvm-objdump'),'--macho','--disassemble',str(path)],stdout=log,env=env,check=True)
display=next(p for p in objects if p.name=='B5qDpDisplay.late.o');raw=display.read_bytes();fixture=json.loads((R/'UniXNU-b5q/scripts/legacy-display-26C5035r.json').read_text())
table=object_vtable(raw,object_symbols(raw),'__ZTV12B5qDpDisplay',len(fixture['slots']))
assert len(table)==483
for index,(entry,expected)in enumerate(zip(table,fixture['slots'])):
 assert entry and entry[1]>>63 and entry[1]>>48&1 and not(entry[1]>>49&3)and entry[1]>>32&65535==int(expected[1],16),index
# Check runtime-matching inherited entries in the final kernel as well as
# the relocation signatures. Symbols may resolve through branch adapters.
with tempfile.TemporaryDirectory(prefix='b5q-dp-returned-core-')as td:
 kernel=Path(td)/'kernel';subprocess.run(['mcopy','-i',str(a.esp),'::/EFI/UniXNU/Payloads/kernel.macho',str(kernel)],check=True)
 data=kernel.read_bytes();outer=Image(data);core=Image(data,outer.entries['com.apple.kernel'][1]);syms={n:v for v,names in core.symbols().items()for n in names}
 assert all(n in syms for n in ['_b5q_dp_display_create','_b5q_dp_link_update','_b5q_dp_irq_start','_b5q_dp_lid_online','__GLOBAL__sub_I_B5qDpDisplay.cpp'])
 fixups=outer.fixups();start=syms['__ZTV12B5qDpDisplay']
 for index,expected in enumerate(fixture['slots']):
  pointer=fixups[start+16+index*8];assert pointer[1:]==(1,0,int(expected[1],16),1)
 for marker in [b'scanout=online',b'B5qDP: dma-ready=',b'B5qDP: EDID pool-filter',b'B5qDP: vsync frame=',b'clamshell-sleep-disabled=']:
  assert marker in data,marker
 assert b'scanout=unattached'not in data
 kernel_sha=hashlib.sha256(data).hexdigest()
fd=a.fd.read_bytes();handoff=loader_pe(fd,'f8a45ce9-92de-48cc-8e19-e97c28b724a0');loader=loader_pe(fd,'1b64af87-8415-4b57-9b16-680d70913b9f')
for marker in [b'B5Q-DPDMA:',b'policy=stock-earlymap-tail']:assert marker in handoff
for marker in [b'b5q-dp-dma-ready',b'b5q-dp-dma-state',b'b5q-dp=']:assert marker in loader
result=dict(passed=True,hardware_verified=False,source_manifest=str(manifest),objects={str(p):d for p,d in objects.items()},
 external_IOMFB_slots=483,all_original_discriminators=True,linked_PAC_slots=483,EL1_apps_smmu_materializations=0,
 native_kernel_sha256=kernel_sha,FD_sha256=sha(a.fd),handoff_sha256=hashlib.sha256(handoff).hexdigest(),loader_sha256=hashlib.sha256(loader).hexdigest(),
 callback_gate='Run check-media-callback-pac.py --dp with the same returned CI directory',
 storage_untouched=True,retained_mapping_policy='Owner-authorized stock splash earlymap tail; firmware validates actual GOP and retained memory')
(a.out/'report.json').write_text(json.dumps(result,indent=2)+'\n');print('PASS actual returned P5 native objects/original483slotABI+linkedPAC/zeroEL1apps_smmu/pairedGOPtailproducer')
