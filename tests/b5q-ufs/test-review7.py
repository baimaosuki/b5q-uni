#!/usr/bin/env python3
"""Review7 production boot-wait deadlines and causal transport regressions."""
from pathlib import Path
import subprocess,tempfile,json,hashlib
R=Path(__file__).resolve().parents[2]
source=(R/'UniXNU-b5q/package/B5qBluetooth.cpp').read_text()
wait=source[source.index('void waitUntil('):source.index('\nuint32_t urd(',source.index('void waitUntil('))]
with tempfile.TemporaryDirectory(prefix='b5q-review7-')as td:
 t=Path(td)
 prefix=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include "B5qBtFifo.h"
using event_t=void*;
#define THREAD_UNINT 0
#define THREAD_AWAKENED 1
#define THREAD_CONTINUE_NULL nullptr
static struct {struct{void*va;}uart;bool gated;unsigned pending;b5q_bt_fifo geni;}bt;
static uint64_t observed;static unsigned blocks;
static void assert_wait(event_t,int){observed=UINT64_MAX;}
static void nanoseconds_to_absolutetime(uint64_t n,uint64_t *p){*p=n;}
static void assert_wait_deadline(event_t,int,uint64_t n){observed=n;}
static void *current_thread(){return nullptr;}
static void clear_wait(void*,int){}
static void thread_block(void*){blocks++;}
'''
 main=r'''
int main(){
 bt.uart.va=&bt;bt.geni.retry_at=1000;
 waitUntil(nullptr,1000000);assert(observed==1000&&blocks==1);
 waitUntil(nullptr,100);assert(observed==100&&blocks==2);
 bt.gated=true;waitUntil(nullptr,1000000);assert(observed==1000000);
 bt.gated=false;bt.geni.retry_at=0;waitUntil(nullptr,UINT64_MAX);assert(observed==UINT64_MAX);
 bt.pending=1;unsigned before=blocks;waitUntil(nullptr,1);assert(blocks==before&&!bt.pending);
 puts("PASS actual qbt_boot waitUntil merges FIFO progress deadlines; gated/off/pending wake retain semantics");
}
'''
 (t/'test.cpp').write_text(prefix+wait+main)
 flags=['-g','-O1','-fsanitize=address,undefined','-I'+str(R/'UniXNU-b5q/package'),'-I'+str(R/'sources/UniXNU-sheng/drivers/QcaBluetooth/src')]
 subprocess.run(['cc',*flags,'-std=c11','-c',str(R/'UniXNU-b5q/package/B5qBtFifo.c'),'-o',str(t/'fifo.o')],check=True)
 subprocess.run(['c++',*flags,'-std=c++17',str(t/'test.cpp'),str(t/'fifo.o'),'-o',str(t/'test')],check=True)
 subprocess.run([str(t/'test')],check=True)
for name in ['bt-fifo','bt-wcn6855','wifi-platform','pcie-firmware-dma','log-writer']:
 subprocess.run(['python3',str(R/'tests/b5q-ufs'/('test-'+name+'.py'))],check=True)
print('PASS review7 focused production causal regression suite; hardware results pending')
# Apple Clang's qualified-super call may import the original base vtable.
# Check the source kernel symbol and fixture's first-slot convention, then
# exercise the production binding resolver with a real target data import.
import sys,importlib.util,os
sys.path[:0]=[str(R/'UniXNU-b5q/scripts'),str(R/'sources/UniXNU/kits/XnuPrelink')]
from kc_image import Image
from b5q_abi import object_symbols
spec=importlib.util.spec_from_file_location('review7_usb',R/'UniXNU-b5q/scripts/build-b5q-usb.py');usb=importlib.util.module_from_spec(spec);spec.loader.exec_module(usb)
abi=json.loads((R/'UniXNU-b5q/scripts/usb-xhci-26C5035r.json').read_text())
raw=(R/'artifacts/b5q-full-27.3-26C5035r/official/ipsw/26C5035r/kernelcache.decompressed').read_bytes();assert hashlib.sha256(raw).hexdigest()==abi['kernelcache_sha256']
outer=Image(raw);original=Image(raw,outer.entries['com.apple.driver.usb.AppleUSBXHCI'][1])
vt=next(v for v,names in original.symbols().items()if '__ZTV12AppleUSBXHCI'in names)
assert vt+16==int(abi['vtable'],16)
expected=vt+int(abi['collection_slide'],16)
for name in ['usb-dual-bindings-26C5035r.json','usb-host-bindings-26C5035r.json']:
 assert int(json.loads((R/'UniXNU-b5q/scripts'/name).read_text())['bindings']['__ZTV12AppleUSBXHCI'],16)==expected
with tempfile.TemporaryDirectory(prefix='b5q-super-import-')as td:
 t=Path(td);src=t/'import.S';obj=t/'import.o';src.write_text('.text\n.p2align 2\n.globl _check_super_vtable_import\n_check_super_vtable_import:\n adrp x0, __ZTV12AppleUSBXHCI@PAGE\n add x0, x0, __ZTV12AppleUSBXHCI@PAGEOFF\n ret\n')
 subprocess.run([str(R/'tools/llvm21/usr/lib/llvm-21/bin/clang'),'-target','arm64e-apple-ios27.0','-c',str(src),'-o',str(obj)],env=dict(os.environ,LD_LIBRARY_PATH=str(R/'tools/llvm21/usr/lib/x86_64-linux-gnu')),check=True)
 imported=[v for v in object_symbols(obj.read_bytes())if v[0]=='__ZTV12AppleUSBXHCI'];assert imported and imported[0][2]==1
 resolver=usb.object_symbols;usb.object_symbols=lambda data:resolver(data)+imported
 actual=(R/'artifacts/b5q-review7-work/target/QcomDwc3.o').read_bytes()
 bound,slots=usb.family_bindings(actual,abi,'QcomDwc3Xhci','12AppleUSBXHCI');assert slots==427 and bound['__ZTV12AppleUSBXHCI']==expected
print('PASS original26C5035r AppleUSBXHCI ZTV==fixturefirstslot-16; actualtargetdataimport resolvedbyproductionbinder withoutfakevtable orPACbypass')
