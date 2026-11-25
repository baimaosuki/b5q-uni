#!/usr/bin/env python3
"""Original26C5035r USB call flow and real Qualcomm HAL configure execution."""
from pathlib import Path
import hashlib,json,sys,struct,pefile,os
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
R=Path(__file__).resolve().parents[2];W=Path(os.environ.get('B5Q_GATE_WORK',R/'artifacts/b5q-v33d-review2'));W.mkdir(exist_ok=True);sys.path.insert(0,str(R/'sources/UniXNU/kits/XnuPrelink'));from kc_image import Image
k=R/'artifacts/b5q-full-27.3-26C5035r/official/ipsw/26C5035r/kernelcache.decompressed';raw=k.read_bytes();outer=Image(raw);images={n:Image(raw,v[1])for n,v in outer.entries.items()if n in ['com.apple.kernel','com.apple.driver.AppleUSBXDCI','com.apple.iokit.IOUSBDeviceFamily','com.apple.driver.AppleUSBDeviceMux']};allsyms={a:ns for v in outer.entries.values()for a,ns in Image(raw,v[1]).symbols().items()};fixups=outer.fixups();d=Cs(CS_ARCH_ARM64,CS_MODE_ARM);lines=[];result={}
assert hashlib.sha256(raw).hexdigest()=='d1003b5143ffd88439b4d45b6017f587171cfe6855660bed05370a2ea5db9fe9'
for id,im in images.items():
 for start,names in im.symbols().items():
  candidates=[n for n in names if n.startswith('__ZN')and any(s in n for s in ['AppleUSBXDCI5start','IOUSBDeviceController5start','IOUSBDeviceController15setProperties','IOUSBDeviceController13setProperties','IOUSBDeviceController30buildFallbackDeviceDescription','IOUSBDeviceController29activateFallbackConfiguration','IOUSBDeviceController15initPower','IOService18changePowerStateTo','IOService22changePowerStateToPriv','IOUSBDeviceController15createUSBDevice','IOUSBDeviceController15setDescription','IOUSBDeviceController18setDescription','AppleUSBDeviceMux5start','IOUSBDeviceController14joinPowerPlane','IOUSBDeviceController15prepareDefaults','IOUSBDeviceController13startUSBStack','IOUSBDeviceConfigurator5start','IOUSBDeviceConfigurator13setProperties'])]
  if not candidates:continue
  name=candidates[0];end=min((v for v in allsyms if v>start),default=start+4096);end=min(end,start+0x5000);result[name]=hex(start);lines+=['\n'+id+' '+name+' '+hex(start)];regs={}
  for i in d.disasm(im.read(start,end-start),start):
   annotation='';op=i.op_str.replace(' ','').split(',')
   if i.mnemonic=='bl' and op[0].startswith('#'):
    target=int(op[0][1:],0);annotation=' ; '+','.join(allsyms.get(target,[]))
    if not allsyms.get(target):
     try:
      stub=list(d.disasm(im.read(target,16),target));page=int(stub[0].op_str.split('#')[1],0)
      if stub[1].mnemonic=='add':
       site=page+int(stub[1].op_str.rsplit('#',1)[1],0);resolved=fixups.get(site,(0,))[0];annotation+=' thunk->'+','.join(allsyms.get(resolved,[]))
     except Exception:pass
   if i.mnemonic=='adrp':regs[op[0]]=int(op[1][1:],0)
   elif i.mnemonic=='add'and len(op)==3 and op[1]in regs and op[2].startswith('#'):
    regs[op[0]]=regs[op[1]]+int(op[2][1:],0)
    try:
     b=im.read(regs[op[0]],128).split(b'\0',1)[0]
     if b and all(32<=c<127 for c in b):annotation+=' ; '+repr(b.decode())
    except Exception:pass
   lines.append(f'{i.address:#x}: {i.bytes.hex()} {i.mnemonic} {i.op_str}'+annotation)
for start,end in [(0xfffffe000c356494,0xfffffe000c356704)]:
 lines.append('\nOriginal IOService common PM request path '+hex(start))
 for i in d.disasm(images['com.apple.kernel'].read(start,end-start),start):lines.append(f'{i.address:#x}: {i.bytes.hex()} {i.mnemonic} {i.op_str}')
(W/'26C5035r-USB-original.disasm.txt').write_text('\n'.join(lines)+'\n')


# Preserve prelink personalities straight from the same original binary.
import plistlib
from native_prelink import unserialize_xml
segment=next(s for s in outer.segments if s['name']=='__PRELINK_INFO')
import xml.etree.ElementTree as ET
root=ET.fromstring(outer.read(segment['va'],segment['filesize']).split(b'\0',1)[0])
info=unserialize_xml(ET.tostring(root[0]if root.tag=='plist'else root));bundles=info['_PrelinkInfoDictionary']
personalities=[b for b in bundles if b.get('CFBundleIdentifier')in ['com.apple.iokit.IOUSBDeviceFamily','com.apple.driver.AppleUSBDeviceMux']]
(W/'26C5035r-USB-personalities.plist').write_bytes(plistlib.dumps(personalities))
pers=next(b for b in personalities if b['CFBundleIdentifier']=='com.apple.iokit.IOUSBDeviceFamily')['IOKitPersonalities']
assert pers['Configuration-standardBringup']['IOPropertyMatch']['ConfigurationType']=='standardBringup'
assert pers['Configuration-standardBringup']['IOClass']=='IOUSBDeviceConfigurator'
assert pers['Configuration-standardBringup']['IOProviderClass']=='IOUSBDeviceController'
assert not any('standardMuxOnly'in str(v)for v in pers.values())
# Resolve the original IOService vtable entries used by joinPowerPlane.
kernel=images['com.apple.kernel'];symbols={n:a for a,ns in kernel.symbols().items()for n in ns}
vtable=symbols['__ZTV9IOService']+16
power_slots={}
for off,expected in [(0x7c0,'PMinit'),(0x7d0,'joinPMtree'),(0x7d8,'registerPowerDriver')]:
 target=fixups[vtable+off][0];names=allsyms[target]
 assert any(expected in n for n in names),(hex(off),names)
 power_slots[hex(off)]={'target':hex(target),'symbols':names}
family=images['com.apple.iokit.IOUSBDeviceFamily']
family_symbols={n:a for a,ns in family.symbols().items()for n in ns}
usb_vtable=family_symbols['__ZTV21IOUSBDeviceController']+16
usb_slots={}
for off,expected in [(0xa40,'startUSBStack'),(0xa48,'joinPowerPlane')]:
 target=fixups[usb_vtable+off][0];names=allsyms[target]
 assert any(expected in n for n in names),(hex(off),names)
 usb_slots[hex(off)]={'target':hex(target),'symbols':names}
super_table=fixups[0xfffffe00089ac550][0]
assert super_table==family_symbols['__ZTV21IOUSBDeviceController']
super_target=fixups[super_table+0x600][0]
assert super_target==family_symbols['__ZN21IOUSBDeviceController5startEP9IOService']
# prepareDefaults holds the OSData metaclass inx21; verify its GOT source,
# then resolve the virtual getBytesNoCopy slot used after safeMetaCast.
prepare_ins=list(d.disasm(family.read(0xfffffe000b1acec8,0x1000),0xfffffe000b1acec8))
osdata_meta=next(a for a,ns in allsyms.items()if '__ZN6OSData10gMetaClassE'in ns)
meta_pointer=fixups[0xfffffe00089aa230][0]
assert '__ZN6OSData9metaClassE'in allsyms[meta_pointer]
assert fixups[meta_pointer][0]==osdata_meta
assert next(d.disasm(family.read(0xfffffe000b1acff0,4),0xfffffe000b1acff0)).op_str=='x21, [x8]'
osdata_vtable=next(a for a,ns in allsyms.items()if '__ZTV6OSData'in ns)+16
assert any('getBytesNoCopy'in n for n in allsyms[fixups[osdata_vtable+0x198][0]])
for site,target in [(0xfffffe000b1aea5c,0xfffffe000b1acec8),(0xfffffe000b1c4844,0xfffffe000b1bcdf4)]:
 ins=next(d.disasm(family.read(site,4),site));assert ins.mnemonic=='bl'and int(ins.op_str[1:],0)==target
pm=images['com.apple.kernel']
assert next(d.disasm(pm.read(0xfffffe000c3564b8,4),0xfffffe000c3564b8)).op_str=='w9, #0, #0xfffffe000c3565fc'
assert next(d.disasm(pm.read(0xfffffe000c3565fc,4),0xfffffe000c3565fc)).op_str=='w0, #8'
# Execute the unmodified HAL machine code. No stub returns stand in for
# domain_configure. New/unattached domain is the production call order.
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X30,UC_ARM64_REG_SP
hal=R/'uefi-b5q/Binaries/b5q/QcomPkg/Drivers/HALIOMMUDxe/HALIOMMUDxe.efi'
hash_hal=hashlib.sha256(hal.read_bytes()).hexdigest();assert hash_hal=='a6020ff87c4526baf9f8cb39870e618691a83cf5ecb8ae4cd1e9e1d42ed9c2ef'
pe=pefile.PE(str(hal));mapped=pe.get_memory_mapped_image();base=0x100000
hal_lines=['HALIOMMUDxe SHA256 '+hash_hal]
for start,end in [(0x2cd0,0x3020),(0x4840,0x4990)]:
 for i in d.disasm(mapped[start:end],start):hal_lines.append(f'{i.address:#010x}: {i.bytes.hex()} {i.mnemonic} {i.op_str}')
(W/'HAL-domain-configure-original.disasm.txt').write_text('\n'.join(hal_lines)+'\n')
config=struct.pack('<IIQQIIIIII',0,0,0xa0c000000,0,0x00ff0400,0,0x00c01027,0x00803510,0x0003c071,0)
assert len(config)==48
cases=[]
for name,domain,cfg,vmsa,expected in [('new-WBIS-config',0x200000,0x201000,0,0),('null-domain',0,0x201000,0,3),('null-config',0x200000,0,0,3),('unsupported-vmsa',0x200000,0x201000,1,21)]:
 u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);u.mem_map(base,0x100000);u.mem_write(base,mapped)
 u.mem_map(0x200000,0x10000);u.mem_map(0x400000,0x10000);u.mem_map(0x500000,4096)
 candidate=bytearray(config);struct.pack_into('<I',candidate,0,vmsa);u.mem_write(0x201000,bytes(candidate))
 u.reg_write(UC_ARM64_REG_SP,0x40f000);u.reg_write(UC_ARM64_REG_X0,domain);u.reg_write(UC_ARM64_REG_X1,cfg);u.reg_write(UC_ARM64_REG_X30,0x500000)
 visits=[];u.hook_add(UC_HOOK_CODE,lambda uc,pc,size,user:visits.append(pc-base))
 u.emu_start(base+0x2db0,0x500000,count=10000)
 returned=u.reg_read(UC_ARM64_REG_X0);assert returned==expected,(name,returned)
 if expected==0:
  assert u.mem_read(domain,44)==config[:44]
  assert 0x2ec0 in visits and not any(0x3660<=v<0x4840 for v in visits)
 cases.append(dict(name=name,result=returned,expected=expected,instructions=len(visits),copied_configuration=expected==0))
receipt=dict(passed=True,hardware_verified=False,kernelcache_sha256=hashlib.sha256(raw).hexdigest(),HAL_sha256=hash_hal,
 USB_functions=result,original_power_slots=power_slots,configuration_property_type="OSData (NUL-terminated bytes), safeMetaCast b1ade8c then getBytesNoCopy b1adeb4",original_USB_slots=usb_slots,AppleUSBXDCI_super_start=dict(GOT="0xfffffe00089ac550",raw_vtable=hex(super_table),offset="0x600",target=hex(super_target)),PM_uninitialized_test="c3564b8 tbz initialized bit0 -> c3565fc returns8",personality=pers['Configuration-standardBringup'],HAL_real_machine_code_cases=cases,
 conclusion='RVA2cd0 generates defaults; RVA2db0 checks pointers/VMSA only and accepts/copies modified48B configuration; physical DMA and enumeration require subsequent hardware validation')
(W/'original-binaries.json').write_text(json.dumps(receipt,indent=2)+'\n')
print('PASS actual26C5035r USB personality/PM vtable/call disassembly; no standardMuxOnly personality')
print('PASS unmodified HAL RVA2db0 Unicorn:WBIS configuration accepted/copied; null domain/config=>3; VMSA1=>21; defaults are not validation constraints')
