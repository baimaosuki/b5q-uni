#!/usr/bin/env python3
"""Assemble the b5q low-bank and ADT interrupt fix around the deployment kernel.

Local only: no kernel patches, CI, firmware builds or connected device access.
The guide-restoration assembler remains unchanged for historical reproduction.
"""
import argparse,copy,hashlib,json,os,shutil,struct,subprocess,sys,tempfile,tomllib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'UniXNU/scripts'))
from unixnu.devicetree import generate
from unixnu.profiles import merge

RELEASE = 'b5q-esp-adt-v7'
IRQ_PROPERTIES = {
    'interrupts', 'interrupt-parent', 'interrupts-extended', 'interrupt-map',
    'AAPL,interrupts',
}

def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def record(path):return {'bytes':path.stat().st_size,'sha256':sha(path)}
def decode(data):
    paths={}
    def walk(at,parent=None):
        np,nc=struct.unpack_from('<II',data,at);at+=8;props={}
        for _ in range(np):
            key,size=struct.unpack_from('<32sI',data,at);at+=36;key=key.rstrip(b'\0').decode()
            assert key not in props;props[key]=data[at:at+size];at+=(size+3)&~3
        name=props['name'].rstrip(b'\0').decode();here=parent.rstrip('/')+'/'+name if parent is not None else '/'
        assert here not in paths;paths[here]=props
        for _ in range(nc):at=walk(at,here)
        return at
    assert walk(0)==len(data)
    return paths

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    a=parser.parse_args();source=a.source.resolve();out=a.out.resolve()
    old=json.loads((source/'package.manifest.json').read_text())
    assert old['os_profile']=='macos-27.3-26C5035r'
    for rel,item in old['esp_files'].items():assert record(source/'esp-files'/rel)==item,rel
    board=tomllib.loads((ROOT/'UniXNU-b5q/board.toml').read_text())
    assert board['payload']['panic_screen'] is True
    required=['use_contiguous_hint=0','kt_fixed_zones=120','-no_slto_panic']
    assert all(arg in board['payload']['kernel_args'] for arg in required)
    assert sha(ROOT/'UniXNU-b5q/scripts/patch-xnu-entry-probe.py')=='e67dd5ba255a78a7d6f1ad20a9c82cefbedfa804b071837851fddaf878991da5'
    out.mkdir(parents=True,exist_ok=False);stage=out/'esp-files';shutil.copytree(source/'esp-files',stage)
    boot=stage/'EFI/UniXNU';payload=boot/'Payloads';kernel=payload/'kernel.macho'
    expected='7ea22869a35061a45d00221d503442a3d58b6f845c6d1d7fbecd7f49ff18cacf'
    assert sha(kernel)==expected
    original_adt=decode((payload/'kernel.macho.adt').read_bytes())
    config={}
    for path in ['UniXNU/profiles/arch/arm64e/profile.toml','sources/UniXNU-sm8550-common/soc.toml','UniXNU/profiles/os/macos-27.3-26C5035r/profile.toml','UniXNU-b5q/board.toml']:
        config=merge(config,tomllib.loads((ROOT/path).read_text()))
    dtb=out/'hardware.dtb'
    with (out/'adt-generation.log').open('w') as log:
        subprocess.run(['dtc','-I','dts','-O','dtb','-i',str(ROOT/'sources/UniXNU-sm8550-common/dts'),'-o',str(dtb),str(ROOT/'UniXNU-b5q/dts/b5q.dts')],stdout=log,stderr=subprocess.STDOUT,check=True)
    seed=int.from_bytes(original_adt['/chosen']['unique-chip-id'],'little')
    data=generate(dtb,config,unique_chip_id=f'{seed:x}',data=True,trust=True)
    adt=decode(data)
    assert adt['/chosen']['dram-base']==struct.pack('<Q',0x80000000)
    assert adt['/chosen']['dram-size']==struct.pack('<Q',0x80000000)
    assert adt['/chosen']['kernel-ctrr-to-be-enabled']==struct.pack('<I',0)
    assert adt['/defaults']['sleep-disabled']==struct.pack('<I',1)
    assert adt['/chosen']['unique-chip-id']==original_adt['/chosen']['unique-chip-id']
    assert adt['/chosen/memory-map']==original_adt['/chosen/memory-map']
    assert adt['/chosen']['darwinboot-memory-size']==original_adt['/chosen']['darwinboot-memory-size']
    assert {path for path in adt if path.startswith('/arm-io/')}=={'/arm-io/intc'}
    assert adt['/arm-io/intc']['compatible']==b'arm,gic-v3\0'
    interrupt_consumers=sorted(path for path,props in adt.items() if IRQ_PROPERTIES.intersection(props))
    assert not interrupt_consumers, f'Unexpected ADT interrupt consumers: {interrupt_consumers}'
    (payload/'kernel.macho.adt').write_bytes(data)
    line=' '.join(config['payload']['kernel_args']);assert len(line.encode())<1000
    cfg=boot/'unixnu.toml';text=cfg.read_text();previous=tomllib.loads(text)
    text=text.replace('b5q macOS - ESP v2','b5q macOS - ESP v7 ADT').replace('b5q macOS 27.3 - ESP v2','b5q macOS 27.3 - ESP v7 ADT')
    entry=next(e for e in previous['entry'] if e.get('type')=='xnu')
    assert text.count('args = '+json.dumps(entry['args']))==1
    text=text.replace('args = '+json.dumps(entry['args']),'args = '+json.dumps(line));cfg.write_text(text)
    menu=tomllib.loads(text);xnu=next(e for e in menu['entry'] if e.get('type')=='xnu')
    assert menu['boot']['default']=='xnu' and xnu['args']==line
    assert [e['id'] for e in menu['entry']]==[e['id'] for e in previous['entry']]
    assert menu['driver']==previous['driver']
    assert all((boot/e['path']).is_file() for e in menu['driver'])
    changed=[]
    for rel,item in old['esp_files'].items():
        if record(stage/rel)!=item:changed.append(rel)
    assert set(changed)=={'EFI/UniXNU/unixnu.toml','EFI/UniXNU/Payloads/kernel.macho.adt'}
    # POST verification is performed on a disposable copy; even that check must
    # preserve every byte of the already-completed deployment kernel.
    with tempfile.TemporaryDirectory(prefix='b5q-v6-post-') as tmp:
        check=Path(tmp)/'kernel.macho';shutil.copyfile(kernel,check)
        with (out/'kernel-post-check.log').open('w') as log:
            subprocess.run([sys.executable,str(ROOT/'UniXNU/scripts/seal-source-crypto-kernel.py'),str(check),'--kernel-args',line],env=dict(os.environ,UNIXNU_XNU_ARCH='arm64e',UNIXNU_IOS_VERSION='27.0',UNIXNU_XNU_TARGET='macosx'),stdout=log,stderr=subprocess.STDOUT,check=True)
        assert sha(check)==expected
    esp=out/'esp.img'
    with esp.open('wb') as stream:stream.truncate(800*1024*1024)
    with (out/'fat-verification.log').open('w') as log:
        def run(cmd):subprocess.run(list(map(str,cmd)),stdout=log,stderr=subprocess.STDOUT,check=True)
        run(['mkfs.fat','--invariant','-F','32','-S','4096','-s','1','-n','B5QMACOS',esp])
        run(['mcopy','-s','-i',esp,stage/'EFI','::/']);run(['mcopy','-i',esp,stage/'startup.nsh','::/startup.nsh'])
        run(['fsck.fat','-n',esp])
        with tempfile.TemporaryDirectory(prefix='b5q-v6-fat-') as temp:
            target=Path(temp)/'member'
            for p in sorted(stage.rglob('*')):
                if not p.is_file():continue
                target.unlink(missing_ok=True);run(['mcopy','-i',esp,'::/'+p.relative_to(stage).as_posix(),target]);assert record(p)==record(target)
    with esp.open('rb') as stream:bpb=stream.read(512)
    assert struct.unpack_from('<H',bpb,11)[0]==4096 and bpb[13]==1
    assert struct.unpack_from('<I',bpb,32)[0]*4096==838860800
    assert bpb[82:90]==b'FAT32   ' and bpb[510:512]==b'\x55\xaa'
    shutil.copyfile(ROOT/'scripts/b5q-install/install-firstboot.py',out/'install-firstboot.py')
    manifest=copy.deepcopy(old)
    manifest.update(scope='ESP-v7 ADT interrupt fix and b5q low physical DRAM classification',kernel_command_line=line,deploy_kernel_sha256=expected,hardware_tested=False,
       outputs={'esp.img':record(esp)},
       esp_files={p.relative_to(stage).as_posix():record(p) for p in sorted(stage.rglob('*')) if p.is_file()})
    manifest.pop('restoration',None)
    manifest['kernel_command_line_bytes']=len(line.encode())
    manifest['memory_handoff']={'dts_dram':{'base':'0x80000000','size':'0x80000000','role':'low physical bank classification, not the EFI allocation list'},'physical_window':'DarwinBoot EFI allocator at load time; existing request unchanged'}
    manifest['build_status'].update(delivery_version=RELEASE,esp_install_required=True,flash_candidate_ready=True,root_read_only=True,data_volatile=True,esp_fat_sector_bytes=4096,esp_device_logical_sector_bytes=4096,esp_sectors_per_cluster=1)
    manifest['lowdram_update']={'changed_esp_members':changed,'kernel_unchanged':True,'post_reseal_idempotent':True,'dram_base':'0x80000000','dram_size':'0x80000000','ctrr_u32':0,'sleep_disabled_u32':1,'fat_roundtrip':'PASS','new_probes':False,'new_kernel_build':False,'new_ci_run':False,'new_boot_image':False,'physical_bank_source':'b5q Mu reference DTB /ddr-regions property region0; first four cells 0 80000000 0 80000000'}
    manifest['adt_interrupts']={
        'removed_exports':['/arm-io/gpu','/arm-io/gmu','/arm-io/gpu-smmu'],
        'arm_io_exports':['/arm-io/intc'],
        'interrupt_consumers':interrupt_consumers,
    }
    (out/'package.manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (out/'README.zh-CN.md').write_text('''# b5q ESP v7 ADT 启动修复

目标：macos-27.3-26C5035r。esp.img 为 800 MiB FAT32，每扇区 4096 字节、每簇 1 扇区。
GPU、GMU、GPU SMMU 继续在硬件 DTS 中启用。交付 ADT 移除了这三个导出，早期启动期间不会生成对应的 Adreno IOKit 节点。

手机在现有 TWRP 中，电脑端执行：

```sh
cd /home/baimao/zflip5/artifacts/b5q-esp-adt-v7
sha256sum -c SHA256SUMS
python3 install-firstboot.py --esp
adb reboot
```

安装目标为 GPT 中 800 MiB 的 esp 分区，需要设备已安装对应的 boot 和 macosroot。安装器执行整幅镜像回读校验。
主菜单显示 ESP v7 ADT，默认 xnu。验证记录与内核日志见 host-checks/。
''')
    print(json.dumps({'out':str(out),'esp':manifest['outputs']['esp.img'],'changed_esp_members':changed,'deployment_kernel_sha256':expected},indent=2))
if __name__=='__main__':main()
