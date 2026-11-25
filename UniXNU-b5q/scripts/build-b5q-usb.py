#!/usr/bin/env python3
"""Build the native QcomDwc3 dual-role module with reviewed 26C5035r ABIs."""
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

def xdci_header(abi):
 slots=[(int(t,16),int(d,16))for t,d in abi['slots']];methods={int(k):v for k,v in abi['methods'].items()}
 text='#pragma once\n#include <IOKit/IOService.h>\n'
 for slot,macro in abi['macros'].items():text+=f'#define {macro} {methods[int(slot)]["name"]}\n'
 text+=f'''class AppleUSBXDCI : public IOService {{
 OSDeclareAbstractStructors(AppleUSBXDCI)
 unsigned char originalPrivate[{abi['instance_size']}-sizeof(IOService)];
public:
 void free() override;bool init(OSDictionary *properties=nullptr) override;IOReturn setProperties(OSObject *) override;
 bool start(IOService *) override;void stop(IOService *) override;bool terminate(IOOptionBits options=0) override;
 IOWorkLoop *getWorkLoop() const override;IOReturn callPlatformFunction(const OSSymbol *,bool,void *,void *,void *,void *) override;
 IOReturn setPowerState(unsigned long,IOService *) override;unsigned long maxCapabilityForDomainState(IOPMPowerFlags) override;
 unsigned long initialPowerStateForDomainState(IOPMPowerFlags) override;
 IOReturn powerStateWillChangeTo(IOPMPowerFlags,unsigned long,IOService *) override;
 IOReturn powerStateDidChangeTo(IOPMPowerFlags,unsigned long,IOService *) override;
'''
 pure=int(abi['pure_target'],16)
 for i in range(abi.get('base_slots',168),len(slots)):
  m=methods[i];suffix='=0'if slots[i][0]==pure or i in abi.get('pure_slots',[])else''
  text+=f' virtual {m["returns"]} {m["name"]}({m["parameters"]}){suffix};\n'
 return text+f'}};\nstatic_assert(sizeof(AppleUSBXDCI)=={abi["instance_size"]},"Original controller instance size");\n'

def family_bindings(raw,abi,cls,family):
 found=object_symbols(raw);slots=[(int(t,16),int(d,16))for t,d in abi['slots']]
 entries=object_vtable(raw,found,'__ZTV'+str(len(cls))+cls,len(slots)+1)
 require(all(entries[:len(slots)])and not entries[len(slots)],cls+'vtable length')
 slide=int(abi['collection_slide'],16);result={n:int(v,16)+slide for n,v in abi['bindings'].items()}
 # Apple Clang can authenticate a qualified super call through the native
 # base vtable. The fixture records its first slot, sixteen bytes after ZTV.
 # Bind data directly, exactly as gMetaClass; never synthesize a fake vtable.
 result['__ZTV'+family]=int(abi['vtable'],16)-16+slide
 for i,(name,word)in enumerate(entries[:len(slots)]):
  require(word>>63 and word>>48&1 and word>>49&3==0 and word>>32&0xffff==slots[i][1],f'{cls} diversity slot{i}')
  if family in name:
   require(slots[i][0]!=int(abi.get('pure_target','0'),16),f'{cls} unimplemented pure slot{i}')
   require(result.setdefault(name,slots[i][0]+slide)==slots[i][0]+slide,f'{cls} binding slot{i}')
  elif not name.startswith(('__ZN'+str(len(cls))+cls,'__ZNK'+str(len(cls))+cls)):require(i<abi.get('base_slots',168),f'{cls} inherited slot{i}')
 by_div={d:i for i,(_,d)in enumerate(slots)}
 used={n for n,_,k in found if k==1 and family in n}
 for n in used-set(result):
  slot=by_div.get(discriminator(n[1:]));require(slot is not None,f'unbound import {n}');result[n]=slots[slot][0]+slide
 used|={n for n,_ in entries[:len(slots)]if family in n}
 return {n:result[n]for n in used},len(slots)

def bindings(raw,abi):return family_bindings(raw,abi,'QcomDwc3Xhci','12AppleUSBXHCI')
def all_bindings(raw):
 out={};counts={}
 for kind,cls,family in [('xhci','QcomDwc3Xhci','12AppleUSBXHCI'),('xdci','QcomDwc3Xdci','12AppleUSBXDCI')]:
  abi=json.loads(Path(__file__).with_name('usb-'+kind+'-26C5035r.json').read_text());bound,n=family_bindings(raw,abi,cls,family);out.update(bound);counts[kind]=n
 return out,counts

def main():
 from b5q_compile import ROOT,compile,archive,late,report
 from kernel_target import TRIPLE
 out=ROOT/'build/qcom-dwc3';out.mkdir(parents=True,exist_ok=True)
 abi=json.loads(Path(__file__).with_name('usb-xhci-26C5035r.json').read_text())
 (out/'OriginalUsbXhciABI.h').write_text(header(abi));(out/'OriginalUsbXdciABI.h').write_text(xdci_header(json.loads(Path(__file__).with_name('usb-xdci-26C5035r.json').read_text())));source=ROOT/'kits/b5q/QcomDwc3.cpp'
 obj=compile(source,out/'QcomDwc3.o',['-I',str(out),'-I',str(ROOT/'kits/b5q')])
 # ABI integrity checks run locally before submission and on returned bytes.
 # These precomputed original addresses are compile inputs, not a CI gate.
 inputs=json.loads(Path(__file__).with_name('usb-dual-bindings-26C5035r.json').read_text())
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
 report(archive(out/'libQcomDwc3.a',objects),objects,[source],dict(original_XHCI_slots=slots,original_imports=len(bound),apps_smmu_MMIO=False,DMA_environment="controller DMA deferred until firmware-proven SID40 WB-IS handoff",DMA_handoff_required=True,hardware_tested=False))
 print(json.dumps([str(v)for v in objects]))
if __name__=='__main__':main()
