#!/usr/bin/env python3
"""Read produced timings with real macOS 26C5035r IOAV getter instructions."""
from pathlib import Path
import ctypes,hashlib,json,struct,subprocess,sys,tempfile
import unicorn
from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X30
R=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(R/'sources/UniXNU/kits/XnuPrelink'))
from kc_image import Image
raw=(R/'sources/UniXNU/out/ipsw/26C5035r/kernelcache.decompressed').read_bytes()
assert hashlib.sha256(raw).hexdigest()=='d1003b5143ffd88439b4d45b6017f587171cfe6855660bed05370a2ea5db9fe9'
kc=Image(raw);im=Image(raw,kc.entries['com.apple.iokit.IOAVFamily'][1]);symbols={n:va for va,names in im.symbols().items()for n in names}
prefix='__ZNK22IOAVVideoTimingElement'
getters={
 'total':(prefix+'8getTotalE13IOAVVideoAxis',40),
 'active':(prefix+'9getActiveE13IOAVVideoAxis',48),
 'back':(prefix+'12getBackPorchE13IOAVVideoAxis',48),
 'front':(prefix+'13getFrontPorchE13IOAVVideoAxis',48),
 'sync':(prefix+'12getSyncWidthE13IOAVVideoAxis',48),
 'rate':(prefix+'11getSyncRateE13IOAVVideoAxis',48),
 'polarity':(prefix+'15getSyncPolarityE13IOAVVideoAxis',48),
}
h=r'''
#include "B5qDpIoav.h"
#include <cstring>
extern "C" bool timing(unsigned index,unsigned lowClock,uint32_t output[20],uint32_t expected[17]){
 using namespace B5qDp;if(index>=sizeof(ctaTimings)/sizeof(ctaTimings[0]))return false;
 Modes modes;if(!modes.advertisedVic(ctaTimings[index].vic))return false;Mode m=modes.values[0];
 if(lowClock)m.pixelKHz=uint32_t(uint64_t(m.pixelKHz)*1000/1001);
 IoavTiming result;if(!result.make(m))return false;memcpy(output,result.words,80);
 const uint32_t h[]={m.totalWidth(),m.width,uint32_t(m.hBlank-m.hFront-m.hSync),m.hFront,m.hSync,0,uint32_t(m.hPositive)};
 const uint32_t v[]={m.totalHeight(),m.height,uint32_t(m.vBlank-m.vFront-m.vSync),m.vFront,m.vSync,0,uint32_t(m.vPositive)};
 memcpy(expected,h,sizeof h);memcpy(expected+7,v,sizeof v);expected[14]=m.pixelKHz*1000;
 expected[15]=m.refreshMilliHz();expected[16]=uint32_t(uint64_t(m.pixelKHz)*1000*65536/(uint64_t(m.totalWidth())*m.totalHeight()));return true;
}
extern "C" bool reject(){B5qDp::IoavTiming t;B5qDp::Mode m;return !t.make(m)&&!memcmp(&t,B5qDp::IoavTiming{}.words,80);}
'''
out=R/'artifacts/b5q-p5-work/evidence/ioav-timing.json';out.parent.mkdir(parents=True,exist_ok=True)
evidence={key:dict(symbol=name,va=hex(symbols[name]),bytes=im.read(symbols[name],size).hex())for key,(name,size)in getters.items()}
pixelSymbol='_IOAVVideoTimingGetPixelClock'
evidence['pixel']=dict(symbol=pixelSymbol,va=hex(symbols[pixelSymbol]),bytes=im.read(symbols[pixelSymbol],88).hex())
def getter(data,name,axis):
 if name=='pixel':symbol,size=pixelSymbol,88
 else:symbol,size=getters[name]
 code=im.read(symbols[symbol],size)
 uc=unicorn.Uc(unicorn.UC_ARCH_ARM64,unicorn.UC_MODE_ARM);uc.mem_map(0x100000,0x2000);uc.mem_write(0x100000,code)
 uc.mem_map(0x200000,0x1000);uc.mem_write(0x200020,data)
 uc.reg_write(UC_ARM64_REG_X0,0x200020 if name=='pixel'else 0x200000);uc.reg_write(UC_ARM64_REG_X1,axis);uc.reg_write(UC_ARM64_REG_X30,0x101000)
 uc.emu_start(0x100000,0x101000,count=100);return uc.reg_read(UC_ARM64_REG_X0)&0xffffffff
with tempfile.TemporaryDirectory(prefix='b5q-dp-ioav-')as td:
 t=Path(td);(t/'timing.cpp').write_text(h)
 subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror','-Wno-misleading-indentation','-shared','-fPIC','-I'+str(R/'UniXNU-b5q/package'),str(t/'timing.cpp'),'-o',str(t/'timing.so')],check=True)
 lib=ctypes.CDLL(str(t/'timing.so'));lib.timing.argtypes=[ctypes.c_uint,ctypes.c_uint,ctypes.POINTER(ctypes.c_uint32),ctypes.POINTER(ctypes.c_uint32)];lib.timing.restype=ctypes.c_bool
 assert lib.reject();cases=0
 for index in range(94):
  for reduced in [0,1]:
   data=(ctypes.c_uint32*20)();expected=(ctypes.c_uint32*17)();assert lib.timing(index,reduced,data,expected)
   payload=bytes(data);assert len(payload)==80 and data[0]==data[8]==data[16]==data[18]==data[19]==0
   for axis in [0,1]:
    for i,name in enumerate(getters):
     result=getter(payload,name,axis)
     if name=='rate':assert result==0 if axis==0 else abs(result-expected[16])<=1
     else:assert result==expected[axis*7+i],(index,reduced,axis,name,result,expected[axis*7+i])
     cases+=1
   assert getter(payload,'pixel',0)==expected[14] and abs(data[14]*1000//65536-expected[15])<=1;cases+=1
 out.write_text(json.dumps(dict(hardware_verified=False,complete_P5=False,kernelcache_sha256=hashlib.sha256(raw).hexdigest(),original_getters=evidence,cases=cases,result='PASS real 26C5035r IOAV instructions consume produced EDID timings; full external display integration remains incomplete'),indent=2)+'\n')
 print('PASS IOAV timing',cases,'real macOS26C5035r getter executions/94 CTA modes/fractional refresh/no porch transform; invalid mode refused')
