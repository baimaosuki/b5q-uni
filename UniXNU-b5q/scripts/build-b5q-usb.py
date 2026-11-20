#!/usr/bin/env python3
"""Exact 26C5035r host ABI only; hardware code is B5qUsbHost.cpp."""
import json,struct,subprocess,sys
from pathlib import Path
from b5q_abi import require,discriminator,object_symbols,object_vtable

def header(xhci_abi):
 xhci_slots=[(int(t,16),int(d,16))for t,d in xhci_abi['slots']]
 xhci_methods={int(k):v for k,v in xhci_abi['methods'].items()}
 xhci_names={int(k):v for k,v in xhci_abi['macros'].items()}
 xhci_header = '''// Generated from the reviewed AppleUSBXHCI fixture; opaque private storage only.
 #pragma once
 #include <IOKit/IOService.h>
 '''
 for slot, macro in xhci_names.items():
     xhci_header += f'#define {macro} {xhci_methods[slot]["name"]}\n'
 xhci_header += f'''class AppleUSBXHCI : public IOService {{
  OSDeclareAbstractStructors(AppleUSBXHCI)
  unsigned char originalPrivate[{xhci_abi['instance_size']}-sizeof(IOService)];
 public:
  void free() override;
  bool init(OSDictionary *properties=nullptr) override;
  IOReturn setProperties(OSObject *) override;
  bool didTerminate(IOService *,IOOptionBits,bool *) override;
  void systemWillShutdown(IOOptionBits) override;
  void registerService(IOOptionBits options=0) override;
  bool start(IOService *) override;
  void stop(IOService *) override;
  bool open(IOService *,IOOptionBits options=0,void *arg=nullptr) override;
  void close(IOService *,IOOptionBits options=0) override;
  bool handleOpen(IOService *,IOOptionBits,void *) override;
  void handleClose(IOService *,IOOptionBits) override;
  bool handleIsOpen(const IOService *) const override;
  bool terminate(IOOptionBits options=0) override;
  bool matchPropertyTable(OSDictionary *,SInt32 *) override;
  bool attach(IOService *) override;
  IOWorkLoop *getWorkLoop() const override;
  IOReturn message(UInt32,IOService *,void *arg=nullptr) override;
  void PMstop() override;
  IOReturn setPowerState(unsigned long,IOService *) override;
  unsigned long maxCapabilityForDomainState(IOPMPowerFlags) override;
  unsigned long initialPowerStateForDomainState(IOPMPowerFlags) override;
  IOReturn powerStateWillChangeTo(IOPMPowerFlags,unsigned long,IOService *) override;
  IOReturn powerStateDidChangeTo(IOPMPowerFlags,unsigned long,IOService *) override;
 '''
 for i in range(xhci_abi.get('base_slots', 168), len(xhci_slots)):
     m = xhci_methods[i]
     xhci_header += f' virtual {m["returns"]} {m["name"]}({m["parameters"]});\n'
 xhci_header += f'}};\nstatic_assert(sizeof(AppleUSBXHCI)=={xhci_abi["instance_size"]},"Original controller instance size");\n'
 return xhci_header

def bindings(raw,abi):
 found=object_symbols(raw);slots=[(int(t,16),int(d,16))for t,d in abi['slots']]
 entries=object_vtable(raw,found,'__ZTV10B5qUsbHost',len(slots)+1)
 require(all(entries[:len(slots)])and not entries[len(slots)],'B5qUsbHost vtable length')
 slide=int(abi['collection_slide'],16);result={n:int(v,16)+slide for n,v in abi['bindings'].items()}
 base=abi['base_slots'];kernel=range(*(int(v,16)for v in abi['kernel_text']))
 for i,(name,word)in enumerate(entries[:len(slots)]):
  require(word>>63 and word>>48&1 and word>>49&3==0 and word>>32&0xffff==slots[i][1],f'xHCI diversity slot{i}')
  if '12AppleUSBXHCI'in name:
   require(result.setdefault(name,slots[i][0]+slide)==slots[i][0]+slide,f'xHCI binding slot{i}')
  elif not name.startswith(('__ZN10B5qUsbHost','__ZNK10B5qUsbHost')):require(i<base,f'xHCI inherited slot{i}')
  if i<base and slots[i][0]not in kernel and i not in (0,1,7):require('12AppleUSBXHCI'in name or '10B5qUsbHost'in name,f'xHCI original override{i}')
 by_div={d:i for i,(_,d)in enumerate(slots)}
 used={n for n,_,k in found if k==1 and '12AppleUSBXHCI'in n}
 for n in used-set(result):
  slot=by_div.get(discriminator(n[1:]));require(slot is not None,f'unbound xHCI import {n}');result[n]=slots[slot][0]+slide
 used|={n for n,_ in entries[:len(slots)]if '12AppleUSBXHCI'in n}
 return {n:result[n]for n in used},len(slots)

def main():
 from b5q_compile import ROOT,compile,archive,late,report
 from kernel_target import TRIPLE
 out=ROOT/'build/b5q-usb';out.mkdir(parents=True,exist_ok=True)
 abi=json.loads(Path(__file__).with_name('usb-xhci-26C5035r.json').read_text())
 (out/'OriginalUsbXhciABI.h').write_text(header(abi));source=ROOT/'kits/b5q/B5qUsbHost.cpp'
 obj=compile(source,out/'B5qUsbHost.o',['-I',str(out),'-I',str(ROOT/'kits/b5q')])
 # ABI integrity checks run locally before submission and on returned bytes.
 # These precomputed original addresses are compile inputs, not a CI gate.
 inputs=json.loads(Path(__file__).with_name('usb-host-bindings-26C5035r.json').read_text())
 bound={n:int(v,16)for n,v in inputs['bindings'].items()};slots=inputs['slots']
 asm='.text\n.p2align 2\n';addresses=''
 for name,va in sorted(bound.items()):
  if name.endswith('10gMetaClassE')or name.startswith('__ZTV'):addresses+=f'.globl {name}\n.set {name}, {va:#x}\n'
  else:
   addresses+=f'.globl {name}.original\n.set {name}.original, {va:#x}\n';asm+=f'.globl {name}\n{name}:\n bti c\n b {name}.original\n'
 objects=[late(source,obj)]
 for stem,text in [('usb-bindings',asm),('usb-addresses',addresses)]:
  path=out/(stem+'.S');path.write_text(text);target=path.with_suffix('.o')
  subprocess.run(['xcrun','clang','-target',TRIPLE,'-c',str(path),'-o',str(target)],check=True);objects.append(target)
 report(archive(out/'libB5qUsbHost.a',objects),objects,[source],dict(original_XHCI_slots=slots,original_imports=len(bound),apps_smmu_MMIO=False,DMA_handoff_required=True,hardware_tested=False))
 print(json.dumps([str(v)for v in objects]))
if __name__=='__main__':main()
