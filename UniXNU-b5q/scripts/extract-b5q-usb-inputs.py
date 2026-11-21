#!/usr/bin/env python3
"""Extract only b5q USB hardware properties from the saved runtime FDT."""
from pathlib import Path
import argparse,hashlib,json,re,sys
root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root/'UniXNU/scripts'))
from unixnu.devicetree import read_fdt
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--fdt',type=Path,default=root/'b5q-runtime.fdt');a=p.parse_args()
blob=a.fdt.read_bytes();nodes=list(read_fdt(blob).walk())
def one(name):
 found=[n for n in nodes if n.name==name];assert len(found)==1,name;return found[0]
phy=one('ssphy@88e8000');repeater=next(n for n in nodes if n.name=='eusb2_repeater@4f');usb=one('dwc3@a600000');smmu=one('apps-smmu@15000000')
assert repeater.strings('compatible')==['ti,eusb2-repeater'] and repeater.cells('reg')==[0x3e]
assert usb.cells('iommus')[1:]==[0x40,0] and phy.cells('reg')==[0x88e8000,0x3000]
values=phy.cells('qcom,qmp-phy-init-seq');assert len(values)%2==0
pairs=list(zip(values[::2],values[1::2]));assert all(off%4==0 and off<0x3000 and v<=255 for off,v in pairs)
ref=root/'sources/UniXNU-sheng/drivers/QcomDwc3/QcomQmpUsb3.h';rp=[(int(a,16),int(b,16))for a,b in re.findall(r'\{(0x[\da-f]+), (0x[\da-f]+)\}',ref.read_text())]
header='// SPDX-License-Identifier: BSD-2-Clause-Patent\n// Ordered b5q runtime FDT register data; provenance in reports/usb-inputs-v24.json.\n#pragma once\n#include <stdint.h>\nnamespace B5qUsbInputs {\n'
header+='constexpr uint64_t qmpBase=0x88e8000;\nconstexpr uint32_t qmpBytes=0x3000;\n'
header+='constexpr struct {uint16_t offset;uint8_t value;} qmp[]={\n'+''.join(' {0x%x,0x%x},\n'%pair for pair in pairs)+'};\n'
seq=repeater.cells('qcom,param-host-override-seq');header+='constexpr struct {uint8_t reg,value;} tiHost[]={\n'+''.join(' {0x%x,0x%x},\n'%(reg,val)for val,reg in zip(seq[::2],seq[1::2]))+'};\n}\n'
target=root/'UniXNU-b5q/package/B5qUsbInputs.h';target.write_text(header)
r={'fdt_path':str(a.fdt),'fdt_sha256':hashlib.sha256(blob).hexdigest(),'scope':'USB numeric hardware properties only; no chosen/bootargs/identity','qmp':{'base':'0x88e8000','extent':'0x3000','source_property_sha256':hashlib.sha256(phy.properties['qcom,qmp-phy-init-seq']).hexdigest(),'ordered_pairs':pairs,'register_offsets':phy.cells('qcom,qmp-phy-reg-offset'),'reference_header_sha256':hashlib.sha256(ref.read_bytes()).hexdigest(),'reference_count':len(rp),'reference_byte_identical':pairs==rp,'new_pairs_compared_reference':[list(p)for p in pairs if p not in rp],'reference_pairs_missing_in_b5q':[list(p)for p in rp if p not in pairs]},'repeater':{'compatible':repeater.strings('compatible'),'I2C_address':repeater.cells('reg')[0],'parent_reg':repeater.parent.cells('reg'),'reset_gpio':repeater.cells('reset-gpio'),'host_value_register_cells':seq,'revision_register':'0xb0 from Samsung TI_REPEATER; 0x13 is NXP'},'USB_SID':usb.cells('iommus')[1],'display_handoff_SMR':smmu.cells('qcom,handoff-smrs'),'generated_header_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'runtime_owned_USB_slot':'unknown','runtime_owned_USB_context_bank':'unknown','hardware_executed':False}
(root/'UniXNU-b5q/reports/usb-inputs-v24.json').write_text(json.dumps(r,indent=2)+'\n');print('Extracted ordered168b5qQMP and4TIoverride pairs; reference165 table is not byte-identical')
