#!/usr/bin/env python3
"""Compile the production CPU-burn helpers with pinned XNU private headers/PAC.

The helper object is a compile/ABI probe, not a kernel build or deployment input.
Full thread.c compilation is also attempted; missing local MIG prerequisites are
recorded separately and never reported as a compiled translation unit.
"""
import argparse,hashlib,json,os,shlex,subprocess,sys,tempfile
from pathlib import Path
R=Path(__file__).resolve().parents[2]
ap=argparse.ArgumentParser(description=__doc__)
ap.add_argument('--out',type=Path,default=R/'artifacts/b5q-review19-local/cpu-target')
a=ap.parse_args();W=a.out.resolve();W.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(R/'UniXNU/scripts'))
from unixnu.cli import parser
from unixnu.config import Context
from unixnu import feeds,patches
ctx=Context(parser().parse_args(['tree','--device',str(R/'UniXNU-b5q'),'--os','macos-27.3-26C5035r']))
plan=patches.plan(ctx,feeds.resolve(ctx));source=R/'sources/UniXNU/out/feeds/xnu-3199e8bc'
llvm=R/'tools/llvm21/usr/lib/llvm-21/bin';env=dict(os.environ,LD_LIBRARY_PATH=str(llvm.parents[1]/'x86_64-linux-gnu'))
env['LD_LIBRARY_PATH']=str(R/'tools/llvm21/usr/lib/x86_64-linux-gnu')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
def run(cmd,**kw):return subprocess.run(list(map(str,cmd)),capture_output=True,text=True,env=env,**kw)
with tempfile.TemporaryDirectory(prefix='cpu-burn-target-',dir=W) as td:
 t=Path(td);x=t/'xnu'
 p=run(['git','clone','--quiet','--shared',source,x]);assert p.returncode==0,p.stderr
 revision=run(['git','-C',x,'rev-parse','HEAD']).stdout.strip();assert revision==ctx.board['os']['xnu_revision']
 for patch in plan:
  p=run(['git','-C',x,'apply',patch]);assert p.returncode==0,p.stderr
 native=x/'osfmk/kern/thread.c';text=native.read_text();start=text.index('#if __arm64__ && defined(MACH_BSD)\n/* Ledger AST')
 end=text.index('\nstatic void\nthread_cpu_time_usage_exceeded',start)
 includes='''#include <mach/mach_types.h>
#include <kern/thread.h>
#include <kern/task.h>
#include <kern/misc_protos.h>
#include <arm/thread.h>
#include <kern/backtrace.h>
#include <kdp/kdp_dyld.h>
#include <libkern/copyio.h>
#include <vm/vm_protos.h>
#include <stdatomic.h>
extern int proc_selfpid(void); /* Same existing declaration as thread.c. */
'''
 probe=W/'cpu-burn-context.c';probe.write_text(includes+text[start:end]+'\nvoid b5q_cpu_burn_target_check(thread_t thread, task_t task, int pid, const char *name) { b5q_cpu_burn_context(thread,task,pid,name); }\n')
 overlay=t/'include';(overlay/'os').mkdir(parents=True);(overlay/'san').mkdir()
 # LLVM21 lacks the Apple fourth null-authentication qualifier. This local
 # header adaptation matches the existing target gates; call PAC stays enabled.
 (overlay/'os/base.h').write_text((x/'libkern/os/base.h').read_text().replace(', "authenticates-null-values"',''))
 for folder in ['memory','coverage']:
  for header in (x/'san'/folder).glob('*.h'):(overlay/'san'/header.name).symlink_to(header)
 generated=R/'artifacts/b5q-p2-work/xnu-private-headers'
 config=next(line.split('=',1)[1] for line in (generated/'Makefile').read_text().splitlines() if line.startswith('export CONFIG_DEFINES ='))
 flags=['-target','arm64e-apple-ios27.0','-isysroot',str(R/'tools/macos-sdk/MacOSX26.5.sdk'),'-O2','-std=gnu11','-mkernel','-ffreestanding','-mgeneral-regs-only','-fno-common','-fptrauth-calls','-fptrauth-returns','-fptrauth-intrinsics','-fptrauth-function-pointer-type-discrimination','-D__PTRAUTH_INTRINSICS__=1','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-Wno-incompatible-sysroot','-Wno-deprecated-declarations','-Wno-unknown-warning-option',*shlex.split(config)]
 flags+=['-D'+v+'=1' for v in ['ARM64_BOARD_CONFIG_BCM2837','MACH_KERNEL','MACH_KERNEL_PRIVATE','KERNEL','KERNEL_PRIVATE','XNU_KERNEL_PRIVATE','XNU_TARGET_OS_OSX','_KERNEL_BUILD','KERNEL_BUILD','PRIVATE','__arm64__','__LP64__','__DARWIN_UNIX03']]
 flags+=['-include',str(generated/'meta_features.h')]
 for path in [overlay,generated,x/'osfmk',x/'bsd',x/'osfmk/libsa',x/'pexpert',x,x/'libkern',x/'EXTERNAL_HEADERS',R/'tools/macos-sdk/MacOSX26.5.sdk/System/Library/Frameworks/Kernel.framework/Headers']:flags+=['-I',str(path)]
 command=[str(llvm/'clang'),*flags,'-c',str(probe),'-o',str(W/'cpu-burn-context.o')]
 (W/'command.json').write_text(json.dumps(command,indent=2)+'\n');p=run(command);(W/'compile.log').write_text(p.stdout+p.stderr)
 if p.returncode:raise SystemExit(p.stderr)
 assert not p.stdout and not p.stderr,'target must compile without warnings'
 symbols=run([llvm/'llvm-nm','-u',W/'cpu-burn-context.o']);assert symbols.returncode==0
 (W/'imports.txt').write_text(symbols.stdout)
 for symbol in ['_backtrace','_backtrace_user','_copyin','_get_user_regs','_task_get_all_image_info_addr']:assert symbol in symbols.stdout,symbol
 assembly=run([llvm/'llvm-objdump','--disassemble',W/'cpu-burn-context.o']);assert assembly.returncode==0
 (W/'disassembly.txt').write_text(assembly.stdout)
 assert 'pacibsp' in assembly.stdout and ('retab' in assembly.stdout or 'autibsp' in assembly.stdout),'return PAC missing'
 full=[str(llvm/'clang'),*flags,'-c',str(native),'-o',str(W/'thread.o')]
 (W/'full-thread-command.json').write_text(json.dumps(full,indent=2)+'\n');p=run(full);(W/'full-thread.log').write_text(p.stdout+p.stderr)
 full_result='PASS' if p.returncode==0 else 'BLOCKED_MISSING_LOCAL_MIG_HEADER'
 if p.returncode and "'mach/resource_notify.h' file not found" not in p.stderr:raise SystemExit(p.stderr)
 report=dict(passed=True,scope='Production helper target compile with real MACH_KERNEL_PRIVATE headers; not a full XNU link',hardware_verified=False,xnu_revision=revision,patches=[dict(name=p.name,sha256=sha(p)) for p in plan],patched_thread_sha256=sha(native),probe_sha256=sha(probe),object_sha256=sha(W/'cpu-burn-context.o'),warning_count=0,full_thread_compile=full_result,full_thread_first_error=p.stderr.strip() if p.returncode else None,config_sha256=sha(generated/'Makefile'),PAC_return_verified=True)
 (W/'report.json').write_text(json.dumps(report,indent=2)+'\n')
print('PASS CPU burn helpers: arm64e, private XNU headers, imports and return PAC; full thread.c:',full_result)
