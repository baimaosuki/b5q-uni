#!/usr/bin/env python3
"""Inspect final peripheral ABI and execute opt-in/warm-USB mapping paths."""
import argparse,hashlib,json,struct,sys
from pathlib import Path
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
from unicorn.arm64_const import *
root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root/'sources/UniXNU/kits/XnuPrelink'))
from kc_image import Image
p=argparse.ArgumentParser(description=__doc__);p.add_argument('kernel',type=Path);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
raw=a.kernel.read_bytes();outer=Image(raw);im=Image(raw,outer.entries['com.apple.kernel'][1])if outer.entries else outer
names={n:v for v,rows in im.symbols().items()for n in rows};md=Cs(CS_ARCH_ARM64,CS_MODE_ARM)
def one(part):
 found=[v for n,v in names.items()if n=='_'+part or part in n and not n.startswith('_'+part+'.')];assert len(found)==1,(part,found);return found[0]
required=['_b5q_usb_start','_b5q_gpu_start','_b5q_usb_state','_native_gpu_power_stage','__ZTV10B5qUsbHost'];assert all(n in names for n in required)
abi=json.loads((root/'UniXNU-b5q/scripts/usb-xhci-26C5035r.json').read_text());words=struct.unpack('<'+str(len(abi['slots']))+'Q',im.read(names['__ZTV10B5qUsbHost']+16,8*len(abi['slots'])))
assert all((v>>32&0xffff)==int(slot[1],16)for v,slot in zip(words,abi['slots']))
context=one('b5q_windowserver_signal_context');end=min(v for v in names.values()if v>context);instructions=list(md.disasm(im.read(context,end-context),context))
call_targets=[int(i.op_str[1:],16)for i in instructions if i.mnemonic=='bl']
assert names['_backtrace_user']in call_targets and names['_backtrace']in call_targets
assert sum(i.mnemonic=='mov'and i.op_str=='w1, #0x10'for i in instructions)>=2
prepare=names['_proc_prepareexit'];end=min(v for v in names.values()if v>prepare)
assert any(i.mnemonic=='bl'and int(i.op_str[1:],16)==context for i in md.disasm(im.read(prepare,end-prepare),prepare))
for s in [b'B5Q-WS-SIGNAL: saved pc=',b'cache_slide=0x',b'b5q-gmu-fw\0',b'B5qGpu: stage=Samsung-firmware-invalid'] :assert s in raw,s
assert b'b5q-gmu-handoff\0' not in raw
assert b'b5q-usb-handoff\0' not in raw
for value in [b'B5qUsb: stage=warm-clocks',b'B5qUsb: cmd=%08x',b'b5q-fb: REJ acc=',b'b5q-fb: REJ2 rect0=',b'b5q-fb: swap accepted #']:
 assert value in raw,value
for symbol in ['_ShengGmuColdStart','_ShengGmuBuildStartup','_ShengGmuCommandDbInputs','_NativeAdrenoGmuContextBringup','_NativeAdrenoGpuContextBringup']:
 assert symbol in names,symbol
# Inspect compiled b5q CM3 state offset and shared cold-start call rather than
# treating a library name or optional weak default as a driver.
assert 'gpu-power=9' in (root/'UniXNU-b5q/board.toml').read_text()
u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);u.ctl_set_cpu_model(UC_CPU_ARM64_MAX)
lo=min(s['va']for s in im.segments if s['size'])&~4095;hi=(max(s['va']+s['size']for s in im.segments if s['size'])+4095)&~4095;u.mem_map(lo,hi-lo)
for s in im.segments:
 if s['filesize']:u.mem_write(s['va'],raw[s['fileoff']:s['fileoff']+s['filesize']])
base=0xfffffff030000000;u.mem_map(base,0x10000);stop=base;stack=base+0xf000;u.reg_write(UC_ARM64_REG_CPACR_EL1,3<<20)
workers=[];messages=[];enabled=0;worker_mode=False;map_calls=0;usb_delay_calls=[]
frompath={v for n,v in names.items()if 'IORegistryEntry' in n and '8fromPath' in n}
map_targets={v for n,v in names.items()if 'IODeviceMemory' in n and '9withRange' in n}
def cstr(at):
 out=bytearray()
 for j in range(256):
  b=u.mem_read(at+j,1)[0]
  if not b:return out.decode(errors='replace')
  out.append(b)
 raise AssertionError('unterminated fixture string')
def ret(value=0):u.reg_write(UC_ARM64_REG_X0,value);u.reg_write(UC_ARM64_REG_PC,u.reg_read(UC_ARM64_REG_X30))
def hook(e,pc,size,unused):
 global map_calls
 if pc==names['_PE_parse_boot_argn']:
  if cstr(e.reg_read(UC_ARM64_REG_X0))=='b5q-usb-delay':ret(0);return
  assert e.reg_read(UC_ARM64_REG_X2)==4;e.mem_write(e.reg_read(UC_ARM64_REG_X1),struct.pack('<I',enabled));ret(1);return
 if pc==names.get('_IOSleep') and worker_mode:
  ms=e.reg_read(UC_ARM64_REG_X0);assert ms==35000,ms;usb_delay_calls.append(ms);ret(0);return
 if pc==names['_kernel_thread_start']:
  workers.append(e.reg_read(UC_ARM64_REG_X0));e.mem_write(e.reg_read(UC_ARM64_REG_X2),struct.pack('<Q',base+0x1000));ret(0);return
 if pc==names['_thread_deallocate']:ret();return
 if pc in frompath:ret(0);return
 if pc in map_targets:
  physical=e.reg_read(UC_ARM64_REG_X0);length=e.reg_read(UC_ARM64_REG_X1)
  assert physical==0xa600000 and length==0x10000,(hex(physical),hex(length))
  map_calls+=1;ret(0);return
 if pc==names['_IOLog']:
  fmt=cstr(e.reg_read(UC_ARM64_REG_X0));messages.append({'format':fmt,'stage':cstr(struct.unpack('<Q',bytes(e.mem_read(e.reg_read(UC_ARM64_REG_SP),8)))[0]) if 'stage=%s' in fmt else fmt});ret();return
 if pc==names['_thread_terminate']:e.emu_stop();return
 ins=next(md.disasm(bytes(e.mem_read(pc,4)),pc))
 if ins.mnemonic.startswith(('pac','aut','xpac')):e.reg_write(UC_ARM64_REG_PC,pc+4)
 elif ins.mnemonic in ('retab','retaa'):e.reg_write(UC_ARM64_REG_PC,e.reg_read(UC_ARM64_REG_X30))
 elif ins.mnemonic.startswith(('blraa','blrab')):
  target=getattr(__import__('unicorn.arm64_const',fromlist=['*']),'UC_ARM64_REG_'+ins.op_str.split(',')[0].upper());pc2=e.reg_read(target);e.reg_write(UC_ARM64_REG_X30,pc+4);e.reg_write(UC_ARM64_REG_PC,pc2)
u.hook_add(UC_HOOK_CODE,hook);results=[]
# Run the actual compiled timer leaves. Samsung's wider GMU mapping starts
# 0x2000 earlier than the reference; these offsets must advance by 0x2000.
for term,expected in [('gmuLowOffset',0x16220),('gmuHighOffset',0x16224)]:
 address=one(term);u.reg_write(UC_ARM64_REG_SP,stack);u.reg_write(UC_ARM64_REG_X30,stop);u.emu_start(address,stop,count=20)
 assert u.reg_read(UC_ARM64_REG_X0)==expected,(term,hex(u.reg_read(UC_ARM64_REG_X0)))

for prefix in ['usb','gpu']:
 entry=names['_b5q_'+prefix+'_start'];enabled=0;before=len(workers)
 for on in [0,1]:
  enabled=on;u.reg_write(UC_ARM64_REG_SP,stack);u.reg_write(UC_ARM64_REG_X30,stop);u.emu_start(entry,stop,count=10000)
  assert len(workers)==before+on
 if prefix=='usb':
  # PE_state.bootArgs offset160; boot_args.physBase/memSize offset16/24
  # from the pinned pexpert headers. No fabricated firmware handoff property.
  u.mem_write(names['_PE_state']+160,struct.pack('<Q',base+0x2000))
  u.mem_write(base+0x2010,struct.pack('<QQ',0x8c0004000,0x100000000))
 worker_mode=True
 worker=workers[-1];u.reg_write(UC_ARM64_REG_X0,0);u.reg_write(UC_ARM64_REG_X1,0);u.reg_write(UC_ARM64_REG_SP,stack);u.reg_write(UC_ARM64_REG_X30,stop)
 u.emu_start(worker,stop,count=30000);expected='map-core'if prefix=='usb'else'B5qGpu: stage=Samsung-firmware-invalid\n';assert messages[-1]['stage']==expected,(prefix,messages)
 if prefix=='usb':
  assert map_calls==1
  if b'b5q-usb-delay\0' in raw:assert usb_delay_calls==[35000]
 results.append({'worker':prefix,'opt_in_gate_executed':True,'mocked_stop':expected,'controller_maps':map_calls})
a.out.write_text(json.dumps(dict(passed=True,kernel_sha256=hashlib.sha256(raw).hexdigest(),XHCI_vtable_slots=len(words),saved_signal_collector_called_before_corpse=True,actual_user_and_kernel_backtrace_calls=True,frame_limits=16,actual_compiled_missing_input_paths=results,boot_parser_threads_registry_and_logging_mocked=True,PAuth_not_tested=True,device_or_GPU_execution_tested=False,b5q_compiled_timer_offsets_executed=[0x16220,0x16224]),indent=2)+'\n')
print('PASS final427-slot xHCI ABI, fatal-context calls and compiled USB opt-in reaching actual core mapping')
