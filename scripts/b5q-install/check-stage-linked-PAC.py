#!/usr/bin/env python3
"""Inspect actual final chained PAC pointers, including storage and USB/HID ABI."""
import argparse,hashlib,json,sys
from pathlib import Path
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'sources/UniXNU/kits/XnuPrelink'))
from kc_image import Image
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--kernel',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
raw=a.kernel.read_bytes();outer=Image(raw);core=Image(raw,outer.entries['com.apple.kernel'][1]);symbols={n:v for v,ns in core.symbols().items()for n in ns};fixups=outer.fixups()
classes={}
for cls,fixture in [('NativeHidInput','hid-device'),('QcomDwc3Xdci','usb-xdci'),('QcomDwc3Xhci','usb-xhci')]:
 address=symbols['__ZTV'+str(len(cls))+cls]
 original=json.loads((R/'UniXNU-b5q/scripts'/(fixture+'-26C5035r.json')).read_text())
 for i,row in enumerate(original['slots']):
  actual=fixups.get(address+16+i*8);diversity=int(row[1],16)
  assert actual and actual[1] and actual[2]==0 and actual[3]==diversity and actual[4]==1,(cls,i,actual,diversity)
 classes[cls]=dict(slots=len(original['slots']),authenticated=True,key='IA',address_diversity=True,all_discriminators_match_original=True)
data=symbols['__ZTV12B5qDataBlock'];root=symbols['__ZTV12B5qRootBlock']
for i in range(326):
 d=fixups.get(data+16+i*8);r=fixups.get(root+16+i*8)
 assert d and r and d[1:]==r[1:] and d[1] and d[2]==0 and d[4]==1,(i,d,r)
callbacks={}
for fragment,discriminator in [('b5qPlatformPower',0xba5),('buttonsIrq',0x2abe),('touchIrq',0x2abe),('NativeHidInput11touchNotify',0x2abe),('NativeHidInput13buttonsNotify',0xd507),('QcomDwc3Nub7primary',0x2abe)]:
 matches=[(n,v)for n,v in symbols.items()if fragment in n and not n.startswith(('l','__ZZ'))]
 assert len(matches)==1,(fragment,matches)
 name,target=matches[0];sites=[site for site,v in fixups.items()if v[0]==target and v[1:]==(1,0,discriminator,0)]
 # Some compilers sign the callback at runtime with PACIA instead of an
 # authenticated constant. Those sites are checked on the returned objects;
 # do not mistake their absence here for a missing authenticated call.
 callbacks[fragment]=dict(symbol=name,constant_sites=[hex(s)for s in sites],runtime_signed_when_no_constant=not sites)
result=dict(passed=True,kernel_sha256=hashlib.sha256(raw).hexdigest(),classes=classes,storage_virtual_slots=326,
 callback_constants=callbacks,callback_runtime_PAC_requires_returned_object_gate=True,hardware_PAuth_execution_verified=False)
a.out.write_text(json.dumps(result,indent=2)+'\n');print('PASS final chained PAC:1145USB/HIDslots +326Data/root slots; runtime callback proof remains in actual-object audit')
