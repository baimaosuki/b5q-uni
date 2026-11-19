#!/usr/bin/env python3
"""Observe the actual ESP kernel/ADT in QEMU using hardware breakpoints only."""
import argparse,ast,hashlib,json,re,socket,struct,subprocess,tempfile,time,tomllib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def kernel_symbols(kernel):
    # Reuse only the existing read-only fileset symbol parser, never its patcher.
    tree=ast.parse((ROOT/'UniXNU-b5q/scripts/patch-xnu-entry-probe.py').read_text())
    fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='kernel_symbols')
    scope={'struct':struct};exec(compile(ast.Module(body=[fn],type_ignores=[]),'symbols','exec'),scope)
    return {name:va for va,name in scope['kernel_symbols'](kernel).items()}

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--package',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--port',type=int,default=12349)
    parser.add_argument('--cpu', default='max', help='QEMU CPU model')
    parser.add_argument('--icount', help='QEMU instruction-counting settings for comparison runs')
    parser.add_argument('--extra-arg', action='append', default=[], help='Append a boot argument for a host-only control run')
    parser.add_argument('--virt-gic', action='store_true', help='Point the in-memory test ADT at the QEMU virt GIC')
    a=parser.parse_args()
    package=a.package.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    boot=package/'esp-files/EFI/UniXNU';menu=tomllib.loads((boot/'unixnu.toml').read_text());entry=next(e for e in menu['entry'] if e.get('type')=='xnu')
    kernel=boot/entry['path'];payload=kernel.parent;original=(kernel.with_suffix('.macho.adt')).read_bytes();data=kernel.read_bytes()
    manifest=json.loads((package/'package.manifest.json').read_text())
    assert sha(kernel)==manifest['deploy_kernel_sha256']
    assert manifest['kernel_command_line']==entry['args']
    symbols=kernel_symbols(kernel);off=32;segs=[];pc=None
    for _ in range(struct.unpack_from('<I',data,16)[0]):
        cmd,size=struct.unpack_from('<II',data,off)
        if cmd==0x19:
            _,va,length,fo,fs=struct.unpack_from('<16s4Q',data,off+8);segs.append((va,length,fo,fs))
        if cmd==5:pc=struct.unpack_from('<Q',data,off+272)[0]
        off+=size
    base=min(s[0] for s in segs);pa=0x80000000+(base&0x1fffff);end=max(s[0]+s[1] for s in segs)
    with (out/'memory.bin').open('wb') as f:
        f.truncate(end-base)
        for va,length,fo,fs in segs:f.seek(va-base);f.write(data[fo:fo+fs])
    args=bytearray(0x480);args_pa=0x90000000;tree_pa=args_pa+0x4000;trust_pa=tree_pa+0x10000;ram_pa=trust_pa+0x100000
    inputs=[(kernel.with_suffix('.macho.trustcache'),trust_pa),(boot/entry['initrd'],ram_pa)]
    adt=bytearray(original);properties={};changed=[]
    def walk(at,parent=None):
        np,nc=struct.unpack_from('<II',adt,at);at+=8;props={}
        for _ in range(np):
            key,n=struct.unpack_from('<32sI',adt,at);key=key.rstrip(b'\0').decode();at+=36;props[key]=(at,n);at+=(n+3)&~3
        at_name,n=props['name'];name=bytes(adt[at_name:at_name+n]).rstrip(b'\0').decode();here=parent.rstrip('/')+'/'+name if parent is not None else '/';properties[here]=props
        if here=='/chosen/memory-map':
            for key,addr,p in [('TrustCache',trust_pa,inputs[0][0]),('PackedRAMDisk',ram_pa,inputs[1][0])]:
                pos,n=props[key];assert n==16;struct.pack_into('<QQ',adt,pos,addr,p.stat().st_size);changed.append((pos,pos+16))
        for _ in range(nc):at=walk(at,here)
        return at
    assert walk(0)==len(adt)
    def prop(path,key):pos,n=properties[path][key];return bytes(adt[pos:pos+n])
    assert prop('/chosen','dram-base')==struct.pack('<Q',0x80000000)
    assert prop('/chosen','dram-size')==struct.pack('<Q',0x80000000)
    assert prop('/chosen','kernel-ctrr-to-be-enabled')==struct.pack('<I',0)
    assert prop('/defaults','sleep-disabled')==struct.pack('<I',1)
    if a.virt_gic:
        # The QEMU virt control maps GICD at 0x08000000 and GICR at 0x080a0000.
        for path,key,fmt,value in [
            ('/arm-io','ranges','<QQQ',(0,0x08000000,0x1000000)),
            ('/arm-io/intc','reg','<4Q',(0,0x10000,0xa0000,0x20000)),
            ('/arm-io/intc','redistributor-stride','<Q',(0x20000,)),
        ]:
            pos,n=properties[path][key]
            assert n==struct.calcsize(fmt)
            struct.pack_into(fmt,adt,pos,*value)
            changed.append((pos,pos+n))
    assert all(x==y or any(lo<=i<hi for lo,hi in changed) for i,(x,y) in enumerate(zip(original,adt)))
    struct.pack_into('<HHI4Q',args,0,2,2,0,base,pa,0x80000000,(ram_pa+inputs[1][0].stat().st_size+0x3fff)&~0x3fff)
    # Model GOP only: actual XNU image/ADT/args are taken from the delivery.
    struct.pack_into('<6Q',args,0x28,0xb8000000,1,4320,1080,2640,32)
    command_line=' '.join([entry['args'],*a.extra_arg])
    struct.pack_into('<QI',args,0x60,base+tree_pa-pa,len(adt));line=command_line.encode();assert len(line)<1000;args[0x6c:0x6c+len(line)]=line;struct.pack_into('<Q',args,0x478,0x80000000)
    (out/'bootargs.bin').write_bytes(args);(out/'tree.bin').write_bytes(adt)
    (out/'entry.S').write_text(f'.text\n.global _start\n_start:\n ldr x0, ={args_pa:#x}\n ldr x1, ={pa+pc-base:#x}\n br x1\n')
    subprocess.run(['/usr/lib/llvm-17/bin/clang','--target=aarch64-none-elf','-nostdlib','-fuse-ld=lld','-Wl,-Ttext=0x41000000',str(out/'entry.S'),'-o',str(out/'entry.elf')],check=True)
    qmp_dir=tempfile.TemporaryDirectory(prefix='b5q-qmp-')
    qmp_path=Path(qmp_dir.name)/'control'
    cmd=['qemu-system-aarch64','-M','virt,virtualization=off,secure=off,gic-version=3','-cpu',a.cpu,'-m','4096','-smp','1','-display','none','-serial',f'file:{out / "serial.log"}','-monitor','none','-S','-gdb',f'tcp:127.0.0.1:{a.port}','-qmp',f'unix:{qmp_path},server=on,wait=off','-d','int,guest_errors','-D',str(out/'exceptions.log')]
    if a.icount:
        cmd+=['-icount',a.icount]
    for file,addr in [(out/'memory.bin',pa),(out/'bootargs.bin',args_pa),(out/'tree.bin',tree_pa),*inputs]:cmd+=['-device',f'loader,file={file},addr={addr:#x},force-raw=on']
    cmd+=['-device',f'loader,file={out/"entry.elf"},cpu-num=0']
    log=(out/'qemu.stderr').open('w');proc=subprocess.Popen(cmd,stdout=log,stderr=log)
    report={'scope':f'ESP deployment kernel, ADT and menu arguments on QEMU {a.cpu} with synthesized GOP and loader allocation','kernel_sha256':sha(kernel),'delivered_adt_sha256':hashlib.sha256(original).hexdigest(),'menu_sha256':sha(boot/'unixnu.toml'),'dram_properties_unchanged':True,'loader_filled_properties':['/chosen/memory-map/TrustCache','/chosen/memory-map/PackedRAMDisk'],'kernel_code_modified':False,'hardware_breakpoints_only':True,'command':cmd,'checkpoints':[],'console_returned':False,'synthetic_gop':{'base':'0xb8000000','width':1080,'height':2640,'stride':4320},'kernel_command_line':command_line,'host_only_boot_arguments':a.extra_arg}
    report['host_only_virt_gic']=a.virt_gic
    try:
        for _ in range(80):
            try:s=socket.create_connection(('127.0.0.1',a.port),timeout=.2);break
            except OSError:
                if proc.poll() is not None:raise RuntimeError((out/'qemu.stderr').read_text())
                time.sleep(.1)
        s.settimeout(25)
        qmp=socket.socket(socket.AF_UNIX)
        qmp.settimeout(5)
        qmp.connect(str(qmp_path))
        qmp_stream=qmp.makefile('rwb')
        qmp_stream.readline()
        def monitor(command, **arguments):
            request=json.dumps({'execute':command,'arguments':arguments}).encode()+b'\n'
            qmp_stream.write(request)
            qmp_stream.flush()
            while True:
                response=json.loads(qmp_stream.readline())
                if 'event' not in response:
                    return response['return']
        monitor('qmp_capabilities')
        (out/'qemu-memory-map.log').write_text(monitor('human-monitor-command', **{'command-line':'info mtree'}))
        def recv():
            while (byte:=s.recv(1))!=b'$':
                if not byte:
                    raise EOFError('QEMU closed its GDB connection')
            b=b''
            while (c:=s.recv(1))!=b'#':b+=c
            s.recv(2);s.sendall(b'+');return b.decode()
        def send(command):
            b=command.encode();s.sendall(b'$'+b+b'#'+f'{sum(b)%256:02x}'.encode());return recv()
        def regs():
            raw=send('g');return [int.from_bytes(bytes.fromhex(raw[i:i+16]),'little') for i in range(0,33*16,16)]
        def memory(addr,n):return send(f'm{addr:x},{n:x}')
        def read_bytes(addr,n):
            result=memory(addr,n)
            return None if result.startswith('E') else bytes.fromhex(result)
        def string(addr,n=400):
            h=memory(addr,n)
            return '' if h.startswith('E') else bytes.fromhex(h).split(b'\0')[0].decode('utf8','replace')
        send('qSupported')
        watch=['_panic','_panic_trap_to_debugger','_PE_create_console','_arm_vm_prot_finalize','_kernel_bootstrap','_kernel_bootstrap_thread','_InitIOKit','_ConfigureIOKit','_StartIOKitMatching','_IOKitBSDInit','_bsd_init','_IOFindBSDRoot','_load_init_program','__ZN6ArmCpu6mapGicEv']
        breaks={symbols[name]:name for name in watch if name in symbols}
        for addr in breaks:assert send(f'Z1,{addr:x},4')=='OK'
        return_points={'_PE_create_console':'PE_create_console returned','__ZN6ArmCpu6mapGicEv':'ArmCpu::mapGic returned'}
        for attempt in range(len(breaks) + len(return_points)):
            try:stop=send('c')
            except socket.timeout:
                monitor('stop')
                stop=recv()
                report['timeout']=True
            values=regs();here=values[32];name=breaks.get(here,'untracked');record={'name':name,'pc':hex(here),'lr':hex(values[30]),'stop':stop};report['checkpoints'].append(record)
            print('QEMU',name,hex(here),flush=True)
            if name in ['_panic','_panic_trap_to_debugger']:
                record['format']=string(values[0]);record['x1_hex']=memory(values[1],256)
                # Capture the arguments the existing panic renderer would see.
                indirect=[]
                if not record['x1_hex'].startswith('E'):
                    blob=bytes.fromhex(record['x1_hex'])
                    for i in range(0,min(len(blob),128),8):
                        value=struct.unpack_from('<Q',blob,i)[0]
                        if value>>48==0xffff:
                            text=string(value,256)
                            if text:indirect.append({'slot':i//8,'address':hex(value),'text':text})
                record['arguments']=indirect;report['terminal_reason']='panic';break
            if report.get('timeout'):report['terminal_reason']='host_timeout';break
            send(f'z1,{here:x},4');breaks.pop(here,None)
            if name in return_points:
                ret=values[30]
                breaks[ret]=return_points[name];assert send(f'Z1,{ret:x},4')=='OK'
            elif name=='PE_create_console returned':report['console_returned']=True
            elif name=='ArmCpu::mapGic returned':record['result']=values[0]
        report['last_pc']=hex(values[32]);report['vinfo_hex']=memory(symbols['_vinfo'],64);report['gDramBase_hex']=memory(symbols['_gDramBase'],8);report['gDramSize_hex']=memory(symbols['_gDramSize'],8)
        report['registers']={f'x{i}':hex(v) for i,v in enumerate(values[:31])};report['sp']=hex(values[31])
        frames=[]
        frame=values[29]
        for _ in range(24):
            data=read_bytes(frame,16) if frame>>48==0xffff else None
            if not data:
                break
            next_frame,ret=struct.unpack('<QQ',data)
            pc=ret | 0xffffff8000000000  # Kernel stack return addresses can carry PAC.
            candidates=[(address,name) for name,address in symbols.items() if address<=pc]
            if candidates:
                address,name=max(candidates)
                frames.append({'pc':hex(pc),'symbol':name,'offset':hex(pc-address)})
            if next_frame<=frame:
                break
            frame=next_frame
        report['backtrace']=frames
        msgbuf=read_bytes(symbols['_msgbuf'],24)
        if msgbuf:
            magic,size,write,_,buffer=struct.unpack('<4IQ',msgbuf)
            if magic==0x063061 and 0<=write<size<=1024*1024:
                chunks=[read_bytes(buffer+i,min(1024,size-i)) for i in range(0,size,1024)]
                if all(chunk is not None for chunk in chunks):
                    ring=b''.join(chunks)
                    (out/'kernel.log').write_bytes((ring[write:]+ring[:write]).strip(b'\0'))
        assert report['console_returned'], 'PE_create_console did not return'
        assert int(report['vinfo_hex'],16)!=0
        assert sha(kernel)==report['kernel_sha256']
    finally:
        proc.terminate()
        try:proc.wait(timeout=3)
        except subprocess.TimeoutExpired:proc.kill();proc.wait()
        log.close();(out/'summary.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
        qmp_dir.cleanup()
    exceptions=re.findall(r'with ESR ([^\n]+)\n(?:\.\.\.with FAR (0x[0-9a-f]+)\n)?\.\.\.with ELR (0x[0-9a-f]+)',(out/'exceptions.log').read_text())
    if exceptions:
        esr,far,elr=exceptions[-1];addr=int(elr,16);va,name=max((v,n) for n,v in symbols.items() if v<=addr)
        report['last_exception']={'esr':esr,'far':far,'elr':elr,'symbol':name,'symbol_address':hex(va),'offset':hex(addr-va)}
    (out/'summary.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({k:report.get(k) for k in ['console_returned','last_pc','terminal_reason','checkpoints']},indent=2,ensure_ascii=False))
if __name__=='__main__':main()
