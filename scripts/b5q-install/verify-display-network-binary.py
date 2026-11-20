#!/usr/bin/env python3
"""Inspect actual final Ethernet vtable, late-start call and signed-text machinery."""
import argparse,hashlib,json,struct,sys
from pathlib import Path
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root/'sources/UniXNU/kits/XnuPrelink'));from kc_image import Image
p=argparse.ArgumentParser(description=__doc__);p.add_argument('kernel',type=Path);p.add_argument('--out',required=True,type=Path);a=p.parse_args();raw=a.kernel.read_bytes();outer=Image(raw);im=Image(raw,outer.entries['com.apple.kernel'][1])if outer.entries else outer;names={n:v for v,ns in im.symbols().items()for n in ns};abi=json.loads((root/'UniXNU-b5q/scripts/net-ether-26C5035r.json').read_text());md=Cs(CS_ARCH_ARM64,CS_MODE_ARM)
required=['_b5q_ethernet_start','_b5q_ethernet_state','__ZTV11B5qEthernet','__GLOBAL__sub_I_B5qEthernet.cpp','_cs_text_fixup_page','_cs_text_fixup_hash','_cs_text_fixup_parsed','_cs_text_fixup_applied']
assert all(n in names for n in required),[n for n in required if n not in names]
words=struct.unpack('<'+str(len(abi['slots']))+'Q',im.read(names['__ZTV11B5qEthernet']+16,8*len(abi['slots'])))
assert all((w>>32&0xffff)==int(slot[1],16)for w,slot in zip(words,abi['slots']))
late=[(n,v)for n,v in names.items()if n.endswith('native_legacy_display_late_probev')or n=='_native_legacy_display_late_probe'];assert len(late)==1,late
calls=[i for i in md.disasm(im.read(late[0][1],0x200),late[0][1])if i.mnemonic=='bl'];assert any(int(i.op_str[1:],16)==names['_b5q_ethernet_start']for i in calls)
for needle in [b'com.apple.iokit.IONetworkingFamily\0',b'UniXNULocalClockInterface\0',b'B5qEthernet: local TimeSync interface state %d\n\0',b'ethernet\0',b'text-fixups\0'] :assert needle in raw,needle
result=dict(passed=True,kernel_sha256=hashlib.sha256(raw).hexdigest(),original_Ethernet_collection_sha256=abi['kernelcache_sha256'],actual_final_vtable_entries=len(words),original_vtable_diversities_match=True,late_start_calls_actual_Ethernet_start=True,signature_aware_text_fixup_symbols_present=True,radio_or_hardware_success_claim=False,hardware_tested=False)
a.out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
