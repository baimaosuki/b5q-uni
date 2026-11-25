#!/usr/bin/env python3
"""Verify the three review8 changes in actual returned kernel/driver objects."""
from pathlib import Path
import argparse,hashlib,json,os,re,struct,subprocess,sys,tempfile
R=Path(__file__).resolve().parents[2]
p=argparse.ArgumentParser();p.add_argument('--ci',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
sys.path[:0]=[str(R/'UniXNU-b5q/scripts'),str(R/'sources/UniXNU/kits/XnuPrelink')]
from b5q_abi import object_symbols,macho
from kc_image import Image
assert json.loads((a.out/'package-ready.json').read_text())['passed']
# Get the real target layout from the same production compiler command and
# generated headers. This is compiled ABI evidence, not assumed field offsets.
meta=json.loads((R/'artifacts/b5q-p3-work/target/raw/ath11k_mac.inputs.json').read_text());cmd=meta['command'];source=Path(cmd[cmd.index('-c')+1])
with tempfile.TemporaryDirectory(prefix='b5q-review8-returned-')as td:
 t=Path(td);fixture=t/'offsets.c';fixture.write_text('#include "'+str(source)+'"\nconst unsigned b5q_review8_ops_offsets[]={__builtin_offsetof(struct ieee80211_ops,bss_info_changed),__builtin_offsetof(struct ieee80211_ops,link_info_changed),__builtin_offsetof(struct ieee80211_ops,vif_cfg_changed)};\n')
 command=cmd[:cmd.index('-MD')]+['-S','-emit-llvm',str(fixture),'-o','-']
 ir=subprocess.check_output(command,env=dict(os.environ,LD_LIBRARY_PATH=str(R/'tools/llvm21/usr/lib/x86_64-linux-gnu')),text=True)
 line=next(v for v in ir.splitlines()if v.startswith('@b5q_review8_ops_offsets ='));offsets=list(map(int,re.findall(r'i32 (\d+)',line)));assert len(offsets)==3
 def callbacks(obj):
  raw=obj.read_bytes();symbols=object_symbols(raw);ops=next(v for n,v,k in symbols if n.endswith('ath11k_ops'));sec=next(s for g in macho(raw)['segments']for s in g['sections']if s['va']<=ops<s['va']+s['size'])
  at,count=struct.unpack_from('<II',raw,sec['command_offset']+56);relocs={}
  for i in range(count):
   off,bits=struct.unpack_from('<II',raw,at+i*8)
   if bits>>27&1:relocs[sec['va']+off]=symbols[bits&0xffffff][0]
  result=[]
  for off in offsets:
   address=ops+off;word=struct.unpack_from('<Q',raw,sec['fileoff']+address-sec['va'])[0]
   result.append((word,relocs.get(address)))
  return result
 candidates=[v for v in a.ci.rglob('ath11k_mac.o')if v.parent.name!='raw'];assert len(candidates)==1
 current=callbacks(candidates[0]);assert current[0]==(0,None),'Legacy BSS callback still installed'
 assert current[1][1]and current[1][1].endswith('ath11k_mac_op_bss_info_changed')
 assert current[2][1]and current[2][1].endswith('b5q_ath11k_vif_cfg_changed')
 old=[v for v in (R/'artifacts/b5q-review7-work/ci45623026650').rglob('ath11k_mac.o')if v.parent.name!='raw'];assert len(old)==1 and callbacks(old[0])[0][1],'Old invalid ops must be detected'
 kernel=t/'kernel';subprocess.run(['mcopy','-i',str(a.ci/'payload/payload.img'),'::/EFI/UniXNU/Payloads/kernel.macho',str(kernel)],check=True)
 raw=kernel.read_bytes();outer=Image(raw);core=Image(raw,outer.entries['com.apple.kernel'][1]);symbols={n:va for va,names in core.symbols().items()for n in names}
 assert '_assert_wait_timeout'in symbols
 for marker in [b'stage=silence-lift timeout-ms=40',b'stage=ignored-report',b'max77705 DRP stage=',b'CCCTRL1=',b'CC_STATUS0=',b'PD_STATUS0=']:
  assert marker in raw,marker
 touch,=a.ci.rglob('B5qTouch.o');assert '_assert_wait_timeout'in {n for n,_,k in object_symbols(touch.read_bytes())if k==1}
 # Review7 gains/DPI/click core and the working BT/QMP code stay identical.
 for name in ['NativeHidInput.o','B5qBluetooth.o','B5qBtFifo.o','QcomDwc3.o']:
  actual,=a.ci.rglob(name);previous,=(R/'artifacts/b5q-review7-work/ci45623026650').rglob(name)
  assert actual.read_bytes()==previous.read_bytes(),name+' unexpectedly changed'
proof=dict(passed=True,hardware_verified=False,actual_target_ops_offsets=offsets,actual_callback_relocations=current,old_invalid_callback_detected=True,timeout_and_DRP_diagnostics_in_deployment=True,review7_HID_BT_USB_objects_byte_identical=True)
(a.out/'review8-returned.json').write_text(json.dumps(proof,indent=2)+'\n');print('PASS actualreview8opslegacyNULL+splitpair,40mswait/DRPmarkers,oldinvalidnegative andunchangedHID/BT/USBobjects')
