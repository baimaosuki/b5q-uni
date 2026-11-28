#!/usr/bin/env python3
"""Inspect newly compiled USB firmware and the unchanged xHCI421 PAC slot."""
from pathlib import Path
import hashlib,json,os,sys
R=Path(__file__).resolve().parents[2];W=Path(os.environ.get('B5Q_GATE_WORK',R/'artifacts/b5q-v33d-review4'))
sys.path.insert(0,str(R/'UniXNU-b5q/scripts'))
from b5q_smmu_binary import check
from b5q_abi import object_symbols,object_vtable
firmware=R/'artifacts/b5q-p5-work/uefi-target';producer=firmware/'UsbDma.obj'
proof=check(producer,usb=True,msi=False)
assert b'AllocatePool'not in producer.read_bytes()and b'FreePool'not in producer.read_bytes()
new=W/'target/QcomDwc3.o';old=R/'artifacts/b5q-v33d-release/returned/board-objects/QcomDwc3.o'
name='__ZTV12QcomDwc3Xhci'
tables=[]
for path in [old,new]:
 data=path.read_bytes();table=object_vtable(data,object_symbols(data),name,427);assert table[421]
 tables.append(table)
# Code pointers change; PAC key/discriminator/address-diversity must not.
assert tables[0][421][1]>>32==tables[1][421][1]>>32
assert tables[0][421][0]==tables[1][421][0]
assert all((a is None and b is None)or(a is not None and b is not None and a[1]>>32==b[1]>>32)for a,b in zip(*tables))
result=dict(passed=True,hardware_verified=False,UsbDma=proof,static_map_no_AllocatePool_no_FreePool=True,XHCI_WRITE64=dict(slot=421,offset='0xd28',symbol=tables[1][421][0],authentication_metadata=hex(tables[1][421][1]>>32),signature_unchanged=True,all427_vtable_PAC_fields_unchanged=True,old_object_sha256=hashlib.sha256(old.read_bytes()).hexdigest(),new_object_sha256=hashlib.sha256(new.read_bytes()).hexdigest()))
(W/'review4-target-proof.json').write_text(json.dumps(result,indent=2)+'\n')
print('PASS new EDK2 UsbDma.obj static32768map/noAllocatePool/noFreePool/0014constants; actualarm64eXHCI_WRITE64slot421@d28 signature+PAC unchanged,all427slots match')
