"""Compare generated register sequences to the actual runtime FDT, preserving byte order."""
from pathlib import Path
import sys,re,struct,json,hashlib
root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root/'UniXNU/scripts'))
from unixnu.devicetree import read_fdt
fdt=root/'b5q-runtime.fdt';nodes=list(read_fdt(fdt.read_bytes()).walk());phy=next(n for n in nodes if n.name=='ssphy@88e8000');rep=next(n for n in nodes if n.name=='eusb2_repeater@4f')
s=(root/'UniXNU-b5q/package/B5qUsbInputs.h').read_text()
q=s.split('qmp[]={\n',1)[1].split('};',1)[0];pairs=[(int(a,16),int(b,16))for a,b in re.findall(r'\{(0x[\da-f]+),(0x[\da-f]+)\}',q)]
assert len(pairs)==168 and b''.join(struct.pack('>II',*p)for p in pairs)==phy.properties['qcom,qmp-phy-init-seq']
t=s.split('tiHost[]={\n',1)[1].split('};',1)[0];pairs=[(int(a,16),int(b,16))for a,b in re.findall(r'\{(0x[\da-f]+),(0x[\da-f]+)\}',t)]
assert rep.cells('reg')==[0x3e] and rep.strings('compatible')==['ti,eusb2-repeater']
assert b''.join(struct.pack('>II',v,r)for r,v in pairs)==rep.properties['qcom,param-host-override-seq']
source=root/'artifacts/b5q-runtime-v24-work/samsung-source/repeater-i2c-eusb2.c'
text=source.read_text();assert '#define REV_ID\t\t\t\t0xB0' in text
print('PASS exact runtimeFDT168QMPpairs/order +4TIoverrides and correctTIrevisionB0; nohardwarewrite')
