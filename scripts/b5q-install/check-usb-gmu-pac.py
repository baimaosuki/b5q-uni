#!/usr/bin/env python3
"""Audit USB/GPU/clock/buttons/HID/Thermal callback PAC contracts on actual objects."""
import argparse,hashlib,json,struct,sys,collections
from pathlib import Path
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'UniXNU-b5q/scripts'))
from b5q_abi import macho,object_symbols
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--usb',type=Path,required=True);p.add_argument('--armcpu',type=Path,required=True);p.add_argument('--gpu',type=Path,required=True);p.add_argument('--gmu',type=Path,required=True);p.add_argument('--extended-dir',type=Path,help='Unchanged baseline board/core objects, newNativeHidInput.o overrides same name');p.add_argument('--out',type=Path,required=True);a=p.parse_args()
md=Cs(CS_ARCH_ARM64,CS_MODE_ARM);md.skipdata=True

def scan(path):
 data=path.read_bytes();symbols=object_symbols(data);instructions=[];relocs={};signed={};calls=[]
 for segment in macho(data)['segments']:
  for sec in segment['sections']:
   ro,rc=struct.unpack_from('<II',data,sec['command_offset']+56)
   for index in range(rc):
    off,bits=struct.unpack_from('<II',data,ro+8*index)
    if bits>>27&1:
     name=symbols[bits&0xffffff][0];relocs[sec['va']+off]=name
     if bits>>28==11:
      word=struct.unpack_from('<Q',data,sec['fileoff']+off)[0]
      signed.setdefault(name,[]).append({'site':hex(sec['va']+off),'key':word>>49&3,'diversity':word>>32&0xffff,'address_diversity':word>>48&1,'kind':'relocation'})
   if sec['name']=='__text':instructions+=list(md.disasm(data[sec['fileoff']:sec['fileoff']+sec['size']],sec['va']))
 for i,ins in enumerate(instructions):
  if ins.mnemonic=='pacia':
   previous=instructions[max(0,i-3):i]
   if len(previous)==3 and previous[-1].mnemonic=='mov'and previous[-1].op_str.startswith('x17, #'):
    name=relocs.get(previous[-2].address)
    if name:signed.setdefault(name,[]).append({'site':hex(ins.address),'key':0,'diversity':int(previous[-1].op_str.split('#')[1],0),'address_diversity':0,'kind':'PACIAinstruction'})
  if ins.mnemonic in ('blraa','braa')and i and instructions[i-1].mnemonic=='mov':
   modifier=ins.op_str.split(', ')[1];prev=instructions[i-1]
   if prev.op_str.startswith(modifier+', #'):
    calls.append({'site':hex(ins.address),'diversity':int(prev.op_str.split('#')[1],0),'key':0})
 return {'signed':signed,'calls':calls,'symbols':symbols,'instructions':instructions,'sha256':hashlib.sha256(data).hexdigest()}
usb,arm,gpu,gmu=map(scan,[a.usb,a.armcpu,a.gpu,a.gmu])
# This callback is passed as armcpu_spi_attach's C-linkage callback parameter.
usb_callback='__ZN9B5qUsbNub9interruptEPv';usb_sites=usb['signed'][usb_callback]
assert usb_sites and all(s['key']==0 and s['diversity']==0x2abe and not s['address_diversity']for s in usb_sites)
start=next(v for n,v,k in arm['symbols']if n=='__ZN6ArmCpu9interruptEv'and k&0xe)
end=min(v for n,v,k in arm['symbols']if k&0xe and v>start)
arm_calls=[c for c in arm['calls']if start<=int(c['site'],16)<end and c['diversity']==0x2abe];assert len(arm_calls)==1,arm_calls
# Every field of both interop structs (ShengGmuIo/Services), including
# BindMmio's C-produced MMIO callbacks that B5qGpu invokes in the reverse direction.
contracts=[('read32',gmu,'_mmio_read',0x54f7),('write32',gmu,'_mmio_write',0xb286),('barrier',gmu,'_mmio_barrier',0x307a),
 ('sha256',gpu,'__ZN12_GLOBAL__N_110coldSha256EPvPKvmPh',0xe2e),('now_us',gpu,'__ZN12_GLOBAL__N_17coldNowEPvPy',0xe4fe),('wait_us',gpu,'__ZN12_GLOBAL__N_18coldWaitEPvj',0x50c7)]
report=[]
for field,producer,name,div in contracts:
 sites=producer['signed'][name];assert sites and all(s['key']==0 and s['diversity']==div and not s['address_diversity']for s in sites)
 consumer=gmu if producer is gpu else gpu
 callers=[c for c in consumer['calls']if c['diversity']==div];assert callers,(field,hex(div))
 report.append({'field':field,'key':'IA','diversity':hex(div),'actual_signed_targets':sites,'actual_matching_consumer_calls':callers})
# The board-level read/write MMIO adapter passed to the common kit is also
# present as an authenticated constant, not an unchecked plain pointer.
for name,div in [('__ZN12_GLOBAL__N_12rdEPvjjPj',0x54f7),('__ZN12_GLOBAL__N_12wrEPvjjj',0xb286)]:
 assert all(s['key']==0 and s['diversity']==div and not s['address_diversity']for s in gpu['signed'][name])
result={'passed':True,'USB_to_ArmCpu':{'producer':usb_sites,'actual_ArmCpu_dispatch_calls':arm_calls,'key':'IA','diversity':'0x2abe'},'all_GMU_IO_and_services_fields':report,'objects_sha256':{name:v['sha256']for name,v in [('USB',usb),('ArmCpu',arm),('GPU',gpu),('GMU',gmu)]},'PAuth_disabled':False,'hardware_PAuth_execution_tested':False}
if a.extended_dir:
 directory=a.extended_dir
 extra={name:scan(directory/name) for name in ['BoardClock.o','ArmDTPlatform.o','ButtonProbe.o','NativeHidInput.o','B5qTouch.o','ThermalLevel.o','IOUserClient.cpo']}
 def within(obj,part,div):
  matches=[(n,v)for n,v,k in obj['symbols']if k&0xe and part in n and not n.startswith('l')and '.cold'not in n]
  assert len(matches)==1,(part,matches)
  n,start=matches[0];end=min((v for nn,v,k in obj['symbols']if k&0xe and v>start),default=1<<64)
  callers=[c for c in obj['calls']if start<=int(c['site'],16)<end and c['diversity']==div]
  assert callers,(part,hex(div));return {'consumer_function':n,'call_sites':callers}
 def interface(producer,symbol,div,consumer,part,label):
  obj=extra[producer];sites=obj['signed'][symbol]
  assert sites and all(x['key']==0 and x['diversity']==div and not x['address_diversity']for x in sites),(label,sites)
  proof=within(extra[consumer],part,div)
  return {'interface':label,'producer_object':producer,'producer_symbol':symbol,'signed_sites':sites,'key':'IA','diversity':hex(div),'consumer_object':consumer,**proof,'passed':True}
 expanded=[]
 expanded.append(interface('BoardClock.o','__ZN12_GLOBAL__N_14readEPy',0x307a,'ArmDTPlatform.o','15getGMTTimeOfDay','BoardClock.read -> gClockRead'))
 expanded.append(interface('BoardClock.o','__ZN12_GLOBAL__N_13setEy',0xa98,'ArmDTPlatform.o','15setGMTTimeOfDay','BoardClock.set -> gClockSet'))
 button=extra['ButtonProbe.o']['signed']['__ZN12_GLOBAL__N_110buttonsIrqEPv']
 assert button and all(x['key']==0 and x['diversity']==0x2abe and not x['address_diversity']for x in button)
 expanded.append({'interface':'ButtonProbe.buttonsIrq -> ArmCpu.interrupt','key':'IA','diversity':'0x2abe','signed_sites':button,'actual_ArmCpu_dispatch_calls':arm_calls,'passed':True})
 expanded.append(interface('NativeHidInput.o','__ZN14NativeHidInput11touchNotifyEPv',0x2abe,'B5qTouch.o','7publishEv','NativeHid.touchNotify -> B5qTouch.sink'))
 expanded.append(interface('NativeHidInput.o','__ZN14NativeHidInput13buttonsNotifyEPvj',0xd507,'ButtonProbe.o','13buttonsThread','NativeHid.buttonsNotify -> ButtonProbe.gSink'))
 for field in ['sCount','sKeys','sValues','sWrite']:
  names=[n for n in extra['ThermalLevel.o']['signed']if ('UserClient'+str(len(field))+field+'E')in n]
  assert len(names)==1,(field,names)
  expanded.append(interface('ThermalLevel.o',names[0],0xbcad,'IOUserClient.cpo','__ZN12IOUserClient14externalMethod','ThermalLevel.'+field+' -> IOExternalMethodDispatch.function'))
 result['expanded_interfaces']=expanded;result['expanded_objects_sha256']={name:obj['sha256']for name,obj in extra.items()}
 result['all_requested_cross_object_interfaces_verified']=True
a.out.write_text(json.dumps(result,indent=2)+'\n');print('PASS actual USB->ArmCpu IA2abe, all6GMU IO/Services fields'+(' and9clock/buttons/HID/Thermal interfaces' if a.extended_dir else '')+'; keys+discriminators match; no core/GPU rebuild')
