#!/usr/bin/env python3
"""Inspect the actual deployed collection for console hooks and the journal worker."""
import argparse,ast,hashlib,json,struct,sys
from pathlib import Path
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
from capstone.arm64_const import ARM64_OP_IMM,ARM64_OP_REG,ARM64_OP_MEM
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'sources/UniXNU/kits/XnuPrelink'))
from kc_image import Image
p=argparse.ArgumentParser(description=__doc__);p.add_argument('kernel',type=Path);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
raw=a.kernel.read_bytes();outer=Image(raw);im=Image(raw,outer.entries['com.apple.kernel'][1])if outer.entries else outer;symbols=im.symbols();names={n:v for v,ns in symbols.items()for n in ns};md=Cs(CS_ARCH_ARM64,CS_MODE_ARM)
cap=names['_nabu_capture_append'];starts=sorted(symbols)
def code(name):
 lo=names[name];hi=min([v for v in starts if v>lo]+[lo+4096]);return list(md.disasm(im.read(lo,min(hi-lo,4096)),lo))
def calls(ins,target):return [i.address for i in ins if i.mnemonic in ('b','bl') and i.op_str==f'#{target:#x}']
md.detail=True
# LLVM may inline the producer in this translation unit. Resolve its actual
# static memory operands and require ring/end/lock/lost/capacity plus byte stores.
def inline_capture(ins):
 regs={};refs={}
 for i in ins:
  op=i.operands
  for x in op:
   if x.type==ARM64_OP_MEM and x.mem.base in regs:
    address=regs[x.mem.base]+x.mem.disp
    refs.setdefault(address,[]).append(hex(i.address))
  if i.mnemonic=='adrp' and len(op)==2 and op[1].type==ARM64_OP_IMM:regs[op[0].reg]=op[1].imm&((1<<64)-1)
  elif i.mnemonic=='add' and len(op)==3 and op[1].type==ARM64_OP_REG and op[2].type==ARM64_OP_IMM and op[1].reg in regs:regs[op[0].reg]=regs[op[1].reg]+op[2].imm
  elif op and op[0].type==ARM64_OP_REG and i.mnemonic.startswith(('ldr','ldp','mov')):regs.pop(op[0].reg,None)
 wanted=['_nabu_capture_ring','_nabu_capture_end','_nabu_capture_capacity','_nabu_capture_lock','_nabu_capture_lost']
 assert all(names[n] in refs for n in wanted), {"missing":[(n,hex(names[n])) for n in wanted if names[n] not in refs],"actual":[hex(a)for a in refs]}
 assert any(i.mnemonic=='strb' for i in ins) and any(i.mnemonic.startswith('cas') for i in ins) and any(i.mnemonic=='stlr' for i in ins)
 return {n:refs[names[n]] for n in wanted}
hooks={}
for name in ['_console_write','_console_write_unbuffered','_serial_putc_crlf']:
 hit=calls(code(name),cap)
 hooks[name]={"mode":"direct-call","sites":list(map(hex,hit))} if hit else {"mode":"inlined-producer","memory_refs":inline_capture(code(name))}
# Preserve native panic screen; both patched entries must branch into the same
# existing entry padding, whose renderer calls the actual capture producer.
for name in ['_panic','_panic_trap_to_debugger']:
 first=code(name)[0];assert first.mnemonic=='b';target=int(first.op_str[1:],16)
 entry_cmd=outer.command(5);assert entry_cmd
 entry=struct.unpack_from('<Q',raw,entry_cmd[0]+16+32*8)[0]
 assert abs(target-entry)<4096
 renderer=list(md.disasm(outer.read(target,2700),target));hit=calls(renderer,cap);assert hit,name;hooks[name]=list(map(hex,hit))
for name in ['_nabu_capture_snapshot','_nabu_capture_copy','_nabu_log_writer_state','_nabu_log_writer_rounds','_nabu_log_committed_end']:assert name in names,name
worker=[n for n in names if 'nabuLogThread' in n];assert len(worker)==1
io=[n for n in names if 'nabuLogIo' in n];assert len(io)==1
builder=[n for n in names if 'b5qLogRequest' in n]
text='\n'.join(i.mnemonic+' '+i.op_str for n in [*io,*builder]for i in code(n))
# The exact production CDB/UPIU/DD builder is host-tested. Confirm its new
# opcodes and real lock refusal are also present in the returned binary.
assert '#0x2a' in text and '#0x35' in text,text[-3000:]
assert calls(code(io[0]),names['_IOLockTryLock'])
strings=[b'B5QLOG2: RAM console capture;',b'b5q-log-token=',b'log WRITE10 FUA\0',b'log SYNC10\0',b'lockdown_mode_state_public\0',b'cs-lazy\0',b'boot-payload-release\0',b'exec-log\0']
for s in strings:assert s in raw,s
report={'result':'PASS','kernel_sha256':hashlib.sha256(raw).hexdigest(),'console_to_capture_calls':hooks,'capture_symbol':hex(cap),'writer':worker[0],'bounded_io':io[0],'TryLock_in_actual_binary':True,'write10_and_sync10_present':True,'panic_screen_capture_hook_present':True,'hardware_tested':False}
a.out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
