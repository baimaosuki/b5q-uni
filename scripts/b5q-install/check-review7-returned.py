#!/usr/bin/env python3
"""Check review7 features in actual returned firmware and deployment kernel."""
import argparse,hashlib,importlib.util,json,os,subprocess,sys,tempfile
from pathlib import Path
R=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser();p.add_argument('--ci',type=Path,required=True);p.add_argument('--firmware',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
assert json.loads((a.out/'package-ready.json').read_text())['passed']
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
llvm=R/'tools/llvm21/usr/lib/llvm-21/bin';env=dict(os.environ,LD_LIBRARY_PATH=str(R/'tools/llvm21/usr/lib/x86_64-linux-gnu'))
firmware={}
for name in ['PcieDma','UsbDma','MediaDma']:
 paths=list(a.firmware.rglob(name+'.obj'));assert len(paths)==1,(name,len(paths))
 obj=paths[0];assert obj.read_bytes()[:4]==b'BC\xc0\xde'
 ir=subprocess.check_output([str(llvm/'llvm-dis'),str(obj),'-o','-'],text=True,env=env)
 if name=='PcieDma':assert '67108864'in ir,name+' lacks64MiB bound'
 if name in ['PcieDma','UsbDma','MediaDma']:assert 'i32 5'in ir and 'HAL_TABLE'in ir,name+' lacks flush slot5'
 if name=='UsbDma':assert '[32768 x i8]'in ir and 'AllocatePool'not in ir and 'FreePool'not in ir and '8388608'in ir
 firmware[name]={'sha256':sha(obj),'actual_optimized_IR_checked':True}
# Firmware uploads the final loader PE, not an intermediate DarwinBoot.obj.
# Check its actual pool-size equality branch and retention-call argument, and
# prove the loader is the module inside the returned FV.
import pefile,re
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
loader,=a.firmware.rglob('DarwinBoot.efi')
def loader64(data):
 pe=pefile.PE(data=data);decoder=Cs(CS_ARCH_ARM64,CS_MODE_ARM);checks=[]
 for section in pe.sections:
  if not(section.Characteristics&0x20000000):continue
  code=list(decoder.disasm(section.get_data(),section.VirtualAddress))
  for i,ins in enumerate(code[:-2]):
   m=re.fullmatch(r'(w[0-9]+), #0x4000000',ins.op_str)if ins.mnemonic=='mov'else None
   if m and code[i+1].mnemonic=='ccmp'and (', x'+m[1][1:]+',')in code[i+1].op_str and code[i+2].mnemonic=='b.ne':checks.append(ins.address)
   if ins.mnemonic=='mov'and ins.op_str=='w4, #0x4000000'and code[i+1].mnemonic=='bl':checks.append(ins.address)
 return checks
matches=loader64(loader.read_bytes());assert len(matches)>=2,'Loader lacks64MiB equality/retention machine code'
old,=(R/'artifacts/b5q-review5-work/ci45577883578-firmware').rglob('DarwinBoot.efi')
assert not loader64(old.read_bytes()),'32MiB old loader must fail this64MiB check'
sys.path.insert(0,str(R/'UniXNU/scripts'));from unixnu.boot_template import loader_pe
receipt=json.loads((a.firmware/'firmware-transfer.json').read_text())
assert loader.read_bytes()==loader_pe(Path(receipt['FD']['path']).read_bytes(),'1b64af87-8415-4b57-9b16-680d70913b9f')
firmware['DarwinBoot']={'sha256':sha(loader),'64MiB_pool_equality_and_retention_RVAs':[hex(x)for x in matches],'old32MiB_loader_rejected':True,'PE_matches_FD':True}
sys.path.insert(0,str(R/'UniXNU-b5q/scripts'));from b5q_abi import object_symbols,object_vtable
spec=importlib.util.spec_from_file_location('fs',R/'scripts/b5q-install/package-usb-dma-esp.py');fs=importlib.util.module_from_spec(spec);spec.loader.exec_module(fs)
with tempfile.TemporaryDirectory(prefix='b5q-review7-returned-')as td:
 t=Path(td);kernel=t/'kernel';adt=t/'adt'
 for path,out in [('kernel.macho',kernel),('kernel.macho.adt',adt)]:subprocess.run(['mcopy','-i',str(a.ci/'payload/payload.img'),'::/EFI/UniXNU/Payloads/'+path,str(out)],check=True)
 raw=kernel.read_bytes();hid,=a.ci.rglob('NativeHidInput.o');needle=bytes.fromhex('a46513550e37bdd8ffff4743270000')
 assert needle in hid.read_bytes()and needle in raw,'Actual326CPI HID missing'
 for marker in [b'host-dma-diag checkpoint=',b'pdic-ambiguous',b'usb-utmi',b'QSCRATCH=',b'boot-failed result=',b'full_config=']:
  assert marker in raw,marker
 current,=a.ci.rglob('QcomDwc3.o');symbols=object_symbols(current.read_bytes())
 imports={n for n,_,k in symbols if k==1}
 assert '_b5q_log_sync'in imports
 # The artifact contains the final linked storage implementation rather
 # than a standalone B5qUfs.o. Require an actual executable core definition,
 # and inspect the writer-ready guard in that deployed function.
 sys.path.insert(0,str(R/'sources/UniXNU/kits/XnuPrelink'));from kc_image import Image
 outer=Image(raw);core=Image(raw,outer.entries['com.apple.kernel'][1])
 defined={n:address for address,names in core.symbols().items()for n in names}
 assert '_b5q_log_sync'in defined
 sync_address=defined['_b5q_log_sync'];ins=list(Cs(CS_ARCH_ARM64,CS_MODE_ARM).disasm(core.read(sync_address,512),sync_address))
 assert any(i.mnemonic=='cmp'and i.op_str.endswith('#2')for i in ins),'Missing actual writer-ready state2 guard'
 guard=next(i for i in ins if i.mnemonic=='cmp'and i.op_str.endswith('#2'))
 branch=next(i for i in ins if i.address==guard.address+4);assert branch.mnemonic=='b.ne'
 target=int(branch.op_str.lstrip('#'),16)
 tail=list(Cs(CS_ARCH_ARM64,CS_MODE_ARM).disasm(core.read(target,40),target))
 assert tail[0].mnemonic=='mov'and tail[0].op_str=='w0, #3'
 assert any(i.mnemonic=='retab'for i in tail),'Unready writer must return3 with authenticated return'
 base=R/'artifacts/b5q-review6-work/ci45600350653';old,=base.rglob('QcomDwc3.o')
 vt=[object_vtable(o.read_bytes(),object_symbols(o.read_bytes()),'__ZTV12QcomDwc3Xhci',427)for o in [old,current]]
 assert vt[0][421][0]==vt[1][421][0]
 assert all((x is None and y is None)or(x is not None and y is not None and x[1]>>32==y[1]>>32)for x,y in zip(*vt)), 'XHCI PAC changed'
 nodes=fs.adt_nodes(adt.read_bytes());chosen=nodes['/chosen'][2]
 for name,length in [('b5q-pcie-dma-state',88),('b5q-usb-dma-diagnostics',64)]:assert chosen[name]==bytes(length)
 assert int.from_bytes(nodes['/chosen/asmb'][2]['lp-sip0'],'little')==2
result=dict(passed=True,hardware_verified=False,firmware=firmware,HID_326CPI_in_object_and_kernel=True,host_urgent_log_import_export_closed=True,XHCI_427_PAC_fields_and_WRITE64_slot_preserved=True,unchanged_USB_HAL_constants_checked_by_original_returned_gate=True)
(a.out/'review7-returned.json').write_text(json.dumps(result,indent=2)+'\n');print('PASS review7 actual64MiBproducer/loader,HALslot5,326CPIHID,earlyHostlogABI/PAC and ADT')
