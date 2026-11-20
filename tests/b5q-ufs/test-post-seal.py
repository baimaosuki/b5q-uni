from pathlib import Path
import sys,struct,json,os,subprocess,tempfile,shutil,hmac,hashlib,argparse
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
from unicorn.arm64_const import *
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
r=Path('/home/baimao/zflip5');w=r/'artifacts/b5q-runtime-v21-work';sys.path.insert(0,str(r/'sources/UniXNU/kits/XnuPrelink'));from kc_image import Image
parser=argparse.ArgumentParser(description='Verify POST modeling with actual compiled XNU key initializer and ARM64 patcher');parser.add_argument('--kernel',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);argspec=parser.parse_args();source=argspec.kernel;original=source.read_bytes();outer=Image(original);im=Image(original,outer.entries['com.apple.kernel'][1]);names={n:va for va,rows in im.symbols().items() for n in rows}
md=Cs(CS_ARCH_ARM64,CS_MODE_ARM)
base=0xfffffff040000000;stop=base;stack=base+0xf000;arg=base+0x1000
u=Uc(UC_ARCH_ARM64,UC_MODE_ARM);u.ctl_set_cpu_model(UC_CPU_ARM64_MAX)
lo=min(s['va'] for s in im.segments if s['size'])&~4095;hi=(max(s['va']+s['size'] for s in im.segments if s['size'])+4095)&~4095;u.mem_map(lo,hi-lo)
for s in im.segments:
 if s['filesize']:u.mem_write(s['va'],original[s['fileoff']:s['fileoff']+s['filesize']])
u.mem_map(base,0x10000);u.reg_write(UC_ARM64_REG_CPACR_EL1,3<<20);flips=[]
def hook(e,pc,size,_):
 if pc==names['___static_if_key_delta']:
  flips.append((e.reg_read(UC_ARM64_REG_X0),e.reg_read(UC_ARM64_REG_W1)));e.reg_write(UC_ARM64_REG_PC,e.reg_read(UC_ARM64_REG_X30));return
 if pc==names.get('_panic'):raise AssertionError('runtime static key code panicked')
 ins=next(md.disasm(bytes(e.mem_read(pc,4)),pc))
 if ins.mnemonic.startswith(('pac','aut','xpac')) or ins.mnemonic=='ic':e.reg_write(UC_ARM64_REG_PC,pc+4)
 elif ins.mnemonic in ('retab','retaa'):e.reg_write(UC_ARM64_REG_PC,e.reg_read(UC_ARM64_REG_X30))
u.hook_add(UC_HOOK_CODE,hook)
def call(name,x0,x1=0):
 u.reg_write(UC_ARM64_REG_X0,x0);u.reg_write(UC_ARM64_REG_X1,x1);u.reg_write(UC_ARM64_REG_SP,stack);u.reg_write(UC_ARM64_REG_X30,stop);u.emu_start(names[name],stop,count=1000000);assert u.reg_read(UC_ARM64_REG_PC)==stop,name
args=' '.join(__import__('tomllib').loads((r/'UniXNU-b5q/board.toml').read_text())['payload']['kernel_args']);u.mem_write(arg,args.encode()+b'\0');call('_kern_feature_override_apply',arg)
expected={names['_sched_debug_preemption_disable_jump_key'],names['_sched_debug_interrupt_disable_jump_key']};assert {a for a,_ in flips}==expected and all(d==0xffffffff for _,d in flips),flips
with tempfile.TemporaryDirectory(prefix='b5q-post-runtime-') as td:
 p=Path(td)/'kernel';p.write_bytes(original)
 env=dict(os.environ,PYTHONPATH=str(r/'sources/UniXNU/scripts'),UNIXNU_XNU_ARCH='arm64e',UNIXNU_IOS_VERSION='27.0',UNIXNU_XNU_TARGET='macosx')
 for attempt in range(2):
  subprocess.run([sys.executable,str(r/'UniXNU/scripts/seal-source-crypto-kernel.py'),str(p),'--kernel-args',args],check=True,env=env)
  if attempt:assert p.read_bytes()==sealed
  sealed=p.read_bytes()
 report=json.loads(p.with_suffix('.crypto-hmac.json').read_text());code_off=int(report['code_file_offset'],16);hmac_off=int(report['hmac_file_offset'],16)
 assert hmac.digest(b'\0',sealed[code_off:code_off+report['code_bytes']],'sha256')==sealed[hmac_off:hmac_off+32]
 # Execute the production ARM64 instruction patcher for every selected entry,
 # independently checking the sealed bytes are EXACTLY what boot will write.
 for s in im.segments:
  if s['filesize']:u.mem_write(s['va'],sealed[s['fileoff']:s['fileoff']+s['filesize']])
 sec=next(s for s in im.sections if s['name']=='__static_if');count=0
 allkeys=expected|{names['_static_if_test_key_true_to_false_jump_key'],names['_static_if_test_key_false_to_true_jump_key']}
 for offset in range(0,sec['size'],16):
  va=sec['va']+offset;delta,target,link=struct.unpack('<iiQ',im.read(va,16));key=outer.base+(link&0x3fffffff&~3)
  if key not in allkeys:continue
  point=va+delta;before=bytes(u.mem_read(point,4));call('_ml_static_if_entry_patch',va,not(link&1));assert bytes(u.mem_read(point,4))==before,(hex(point),before.hex());count+=1
 assert count==69,count
 report.update(passed=True,actual_compiled_override_function=True,actual_ARM64_instruction_patcher_sites=count,all_runtime_writes_leave_sealed_text_unchanged=True,sealing_idempotent=True,POST_HMAC_recomputed_independently=True,hardware_tested=False,emulation_scope='actual short leaf functions; no QEMU or OS hardware emulation')
 argspec.out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
