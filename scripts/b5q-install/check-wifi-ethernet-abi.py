#!/usr/bin/env python3
"""Execute the production family binder on the actual native network object."""
import argparse,hashlib,json,sys,textwrap
from pathlib import Path
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'UniXNU-b5q/scripts'))
from b5q_abi import object_symbols,object_vtable,require
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--object',type=Path,default=R/'artifacts/b5q-p3-work/board-target/B5qEthernet.o')
parser.add_argument('--out',type=Path)
a=parser.parse_args();path=a.object
raw=path.read_bytes();abi=json.loads((R/'UniXNU-b5q/scripts/net-ether-26C5035r.json').read_text())
family=tuple(str(len(n))+n for n in ('IONetworkController','IOEthernetController','IONetworkMedium','IONetworkInterface','IOEthernetInterface','IOOutputQueue'))
found=object_symbols(raw);used={n for n,_,k in found if k==1 and any(c in n for c in family)}
bindings={n:int(v,16)+int(abi['collection_slide'],16)for n,v in abi['bindings'].items()}
context=dict(eth_raw=raw,eth_found=found,eth_used=used,eth_bindings=bindings,
    eth_pure=int(abi['pure_target'],16),family=family,slide=int(abi['collection_slide'],16),
    BASE=json.loads((R/'UniXNU-b5q/scripts/legacy-display-26C5035r.json').read_text()).get('base_slots',168),object_vtable=object_vtable,require=require)
source=(R/'UniXNU-b5q/scripts/build-b5q-gop-27.py').read_text()
start=source.index('    def family_vtable(');end=source.index('\n    eth_slots =',start)
exec(textwrap.dedent(source[start:end]),context)
classes={}
for cls,base,key in [('B5qEthernet','IOEthernetController','slots'),('ShengWifiInterface','IOEthernetInterface','interface_slots')]:
    slots=[(int(t,16),int(d,16))for t,d in abi[key]]
    context['family_vtable'](cls,base,slots);classes[cls]=len(slots)
missing=sorted(used-set(bindings));assert not missing,missing
report=dict(passed=True,object_sha256=hashlib.sha256(raw).hexdigest(),classes=classes,original_bindings={n:hex(bindings[n])for n in sorted(used)},hardware_verified=False)
(a.out or path.parent/'ethernet-abi.json').write_text(json.dumps(report,indent=2)+'\n')
print('PASS native Ethernet/Wi-Fi interface production vtable binder',classes,len(used),'original bindings')
