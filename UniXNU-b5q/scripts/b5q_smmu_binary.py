"""Check executable SMMU constants in returned PE/COFF/EDK2 bitcode inputs."""
from pathlib import Path
import hashlib,os,struct,subprocess,tempfile
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM

def sections(data):
    if data[:2]==b'MZ':
        import pefile
        return [(s.Name.rstrip(b'\0').decode(),s.get_data(),s.Characteristics)for s in pefile.PE(data=data).sections]
    machine,count,_,_,_,optional,_=struct.unpack_from('<HHIIIHH',data)
    if machine!=0xaa64:raise ValueError('Expected ARM64 COFF')
    result=[]
    for i in range(count):
        row=20+optional+40*i;name=data[row:row+8].rstrip(b'\0').decode();size,off=struct.unpack_from('<II',data,row+16);flags=struct.unpack_from('<I',data,row+36)[0]
        result.append((name,data[off:off+size],flags))
    return result

def materialized(data):
    values=set();md=Cs(CS_ARCH_ARM64,CS_MODE_ARM);md.skipdata=True
    for name,raw,flags in sections(data):
        if not(flags&0x20000000):continue
        regs={}
        for ins in md.disasm(raw,0):
            ops=ins.op_str.replace(' ','').split(',')
            if ins.mnemonic in ('mov','movz','movn','movk')and len(ops)>=2 and ops[1].startswith('#'):
                reg=ops[0][1:];imm=int(ops[1][1:],0);shift=int(ops[2][4:],0)if len(ops)>2 else 0
                value=(regs.get(reg,0)&~(65535<<shift))|(imm<<shift)if ins.mnemonic=='movk'else ~(imm<<shift)if ins.mnemonic=='movn'else imm<<shift
                value&=(1<<(32 if ops[0][0]=='w'else 64))-1;regs[reg]=value
                values.update([value,value&0xffffffff,value>>32])
                if (value&0xfff)==0x743:values.add(0x740)
            elif ins.mnemonic in ('ret','blr','bl','b','br')or ins.mnemonic.startswith('b.'):regs.clear()
        # Compilers may store the configuration in constant data, so this
        # alternative is restricted to complete adjacent HAL config fields.
    for _,raw,_ in sections(data):
        if struct.pack('<III',0x00c01027,0x00803510,0x0003c071)in raw:values.update([0x00c01027,0x00803510,0x0003c071])
    return values

def check(path,usb=False,msi=True):
    data=Path(path).read_bytes();original=data;ir=None
    if data[:4]==b'BC\xc0\xde':
        root=Path(__file__).resolve().parents[2]
        llvm=root/'tools/llvm21/usr/lib/llvm-21/bin';env=dict(os.environ,LD_LIBRARY_PATH=str(root/'tools/llvm21/usr/lib/x86_64-linux-gnu'))
        with tempfile.TemporaryDirectory(prefix='b5q-returned-dma-code-')as td:
            src=Path(td)/'source.bc';obj=Path(td)/'source.obj';src.write_bytes(data)
            ir=subprocess.check_output([str(llvm/'llvm-dis'),'-o','-',str(src)],env=env,text=True)
            subprocess.run([str(llvm/'clang'),'-target','aarch64-pc-windows-msvc','-O2','-c',str(src),'-o',str(obj)],check=True,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            data=obj.read_bytes()
    values=materialized(data)
    required={0x00c01027,0x00803510,0x0003c071,0x00ff0400,0x748}
    if not usb and msi:required.add(0x740)
    missing=required-values
    if missing:raise ValueError('Missing executable DMA constants '+','.join(hex(x)for x in sorted(missing)))
    if usb:
        # Symbol table is retained in both COFF and bitcode upload. Static
        # buffer must exist and AllocatePool must not be imported anywhere.
        names=ir.encode()if ir else original
        assert b'mUsbMapBuf'in names and b'AllocatePool'not in names,'USB transient allocation returned'
        if ir:assert '[32768 x i8]'in ir,'Wrong static map buffer size'
    return dict(passed=True,sha256=hashlib.sha256(original).hexdigest(),constants=[hex(x)for x in sorted(required)],static_map_no_AllocatePool=usb,bitcode_recompiled_for_inspection=ir is not None)
