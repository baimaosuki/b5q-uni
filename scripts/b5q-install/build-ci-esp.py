#!/usr/bin/env python3
"""Assemble a single native4K ESP IMG from authenticated official CI outputs.

The deployed kernel, ADT, trust cache and RAM Data remain the payload members.
The established menu application and DarwinBoot driver are retained explicitly.
Temporary extraction and optional QEMU loader files are released before exit.
"""
import argparse,hashlib,json,os,re,shutil,struct,subprocess,sys,tempfile,tomllib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'UniXNU/scripts'))
from unixnu import ramdisk

def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def record(path):return {'bytes':path.stat().st_size,'sha256':sha(path)}
def adt_decode(data):
    nodes={}
    def walk(at,parent=None):
        count,children=struct.unpack_from('<II',data,at);at+=8;props={}
        for _ in range(count):
            name,n=struct.unpack_from('<32sI',data,at);at+=36
            key=name.rstrip(b'\0').decode();assert key not in props
            props[key]=data[at:at+n];at+=(n+3)&~3
        name=props['name'].rstrip(b'\0').decode();here=parent.rstrip('/')+'/'+name if parent is not None else '/'
        assert here not in nodes;nodes[here]=props
        for _ in range(children):at=walk(at,here)
        return at
    assert walk(0)==len(data);return nodes

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ci-files',type=Path,required=True)
    parser.add_argument('--base',type=Path,default=ROOT/'artifacts/b5q-esp-adt-v7')
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--qemu',action='store_true')
    a=parser.parse_args();ci=a.ci_files.resolve();base=a.base.resolve();out=a.out.resolve()
    index=json.loads((ci/'transfer-index.json').read_text());manifest=json.loads((ci/'package.manifest.json').read_text())
    report=json.loads((ci/'payload/payload.json').read_text());kernel=json.loads((ci/'kernel/kernel.json').read_text())
    assert manifest['os_profile']=='macos-27.3-26C5035r'
    assert kernel['mapping_complete'] and kernel['missing']=={} and not kernel['allow_missing'] and kernel['stub_symbol'] is None
    assert report['panic_screen'] and manifest['storage']['persistent_block_writes'] is False
    for name in ['kernel/kernel.macho','payload/payload.img','package.manifest.json','payload/payload.json']:
        assert record(ci/name)=={k:index['files'][name][k] for k in ['bytes','sha256']},name
    for name,rel in [('kernel.macho','kernel/kernel.macho'),('payload.img','payload/payload.img')]:
        assert record(ci/rel)==manifest['outputs'][name]
    board=tomllib.loads((ROOT/'UniXNU-b5q/board.toml').read_text());line=' '.join(board['payload']['kernel_args'])
    assert report['kernel_args']==line and 'b5q-smmu-reuse=1' in line.split() and 'vc-text=1' in line.split()
    original=json.loads((base/'package.manifest.json').read_text())
    out.mkdir(parents=True,exist_ok=False)
    log=(out/'verification.log').open('w')
    def run(args,**kwargs):return subprocess.run(list(map(str,args)),check=True,stdout=log,stderr=subprocess.STDOUT,**kwargs)
    with tempfile.TemporaryDirectory(prefix='b5q-ci-esp-') as temp:
        temp=Path(temp);package=temp/'package';stage=package/'esp-files';stage.mkdir(parents=True)
        payload=ci/'payload/payload.img'
        if ramdisk.packed(payload):
            unpacked=temp/'payload.fat';ramdisk.decode(payload,unpacked,ROOT/'sources/Mu-Silicium/Mu_Basecore');payload=unpacked
        run(['mcopy','-s','-i',payload,'::/EFI',stage])
        boot=stage/'EFI/UniXNU';files=boot/'Payloads'
        expected={
          'kernel.macho':report['payload_kernel_sha256'],
          'kernel.macho.adt':report['adt_sha256'],
          'scratch-data.img':report['data_ramdisk_sha256'],
          'kernel.macho.trustcache':report['trust_cache_sha256']}
        for name,digest in expected.items():assert sha(files/name)==digest,name
        seed=json.loads((ci/'runtime/data-seed.json').read_text())
        assert seed['volume_uuid']=='1552CFEE-78FF-48D8-8A6C-694B867D61AC' and seed['template_owners_preserved']
        assert seed['sha256']==sha(files/'scratch-data.img') and seed['logical_bytes']==29*2**30
        nodes=adt_decode((files/'kernel.macho.adt').read_bytes())
        for path,key,fmt,val in [('/chosen','dram-base','<Q',0x80000000),('/chosen','dram-size','<Q',0x80000000),('/chosen','kernel-ctrr-to-be-enabled','<I',0),('/defaults','sleep-disabled','<I',1)]:assert nodes[path][key]==struct.pack(fmt,val),(path,key)
        assert {path for path in nodes if path.startswith('/arm-io/')}=={'/arm-io/intc'}
        assert not any({'interrupts','interrupt-parent','interrupts-extended','interrupt-map','AAPL,interrupts'}.intersection(props) for props in nodes.values())
        # Keep the already-used transport interfaces; the official payload omits
        # these when loader="firmware". Record both retained modules separately.
        retained={}
        for rel in ['EFI/BOOT/BOOTAA64.EFI','EFI/UniXNU/Drivers/DarwinBoot.efi']:
            src=base/'esp-files'/rel;assert record(src)==original['esp_files'][rel]
            target=stage/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,target);retained[rel]=record(src)
        (stage/'startup.nsh').write_text('\\EFI\\BOOT\\BOOTAA64.EFI\r\n')
        config_path=boot/'unixnu.toml';config=config_path.read_text();menu=tomllib.loads(config)
        entry=next(e for e in menu['entry'] if e.get('type')=='xnu')
        assert entry['args']==line and menu['boot']['default']=='xnu'
        assert entry['path']=='Payloads/kernel.macho' and entry['initrd']=='Payloads/scratch-data.img'
        if not menu.get('driver'):
            config=config.replace('[[entry]]','[[driver]]\npath = "Drivers/DarwinBoot.efi"\n\n[[entry]]',1)
        if '[ui]' not in config:config=config.replace('version = 1','version = 1\n[ui]\ntitle = "b5q macOS - ESP v9"',1)
        config_path.write_text(config);menu=tomllib.loads(config)
        assert menu['driver']==[{'path':'Drivers/DarwinBoot.efi'}]
        assert [e['id'] for e in menu['entry']]==[e['id'] for e in tomllib.loads((base/'esp-files/EFI/UniXNU/unixnu.toml').read_text())['entry']]
        # Check the source POST seal on a disposable copy, preserving deployment.
        check=temp/'post-kernel.macho';shutil.copyfile(files/'kernel.macho',check)
        run([sys.executable,ROOT/'UniXNU/scripts/seal-source-crypto-kernel.py',check,'--kernel-args',line],env=dict(os.environ,UNIXNU_XNU_ARCH='arm64e',UNIXNU_IOS_VERSION='27.0',UNIXNU_XNU_TARGET='macosx'))
        assert sha(check)==expected['kernel.macho'];check.unlink()
        policy=(ROOT/'UniXNU-b5q/package/B5qUfs/B5qRootPolicies.h').read_text()
        linked=(files/'kernel.macho').read_bytes()
        anchor=bytes(map(int,re.search(r'b5q_root_key\[\d+\]=\{([^}]+)\}',policy)[1].split(',')));assert anchor in linked
        for header in re.findall(r'\{([^{}]+)\}',policy.split('b5q_root_headers[3][544]=',1)[1]):assert bytes(map(int,header.split(','))) in linked
        assert seed['volume_uuid'].encode() in linked
        esp=out/'esp.img'
        with esp.open('wb') as stream:stream.truncate(800*2**20)
        run(['mkfs.fat','--invariant','-F','32','-S','4096','-s','1','-n','B5QMACOS',esp])
        run(['mcopy','-s','-i',esp,stage/'EFI','::/']);run(['mcopy','-i',esp,stage/'startup.nsh','::/startup.nsh']);run(['fsck.fat','-n',esp])
        members={}
        for src in sorted(stage.rglob('*')):
            if not src.is_file():continue
            rel=src.relative_to(stage).as_posix();target=temp/'readback';target.unlink(missing_ok=True)
            run(['mcopy','-i',esp,'::/'+rel,target]);assert record(src)==record(target),rel;members[rel]=record(src)
        with esp.open('rb') as stream:bpb=stream.read(512)
        assert struct.unpack_from('<H',bpb,11)[0]==4096 and bpb[13]==1 and bpb[82:90]==b'FAT32   ' and bpb[510:512]==b'\x55\xaa'
        assert struct.unpack_from('<I',bpb,32)[0]*4096==esp.stat().st_size
        delivery=dict(os_profile=manifest['os_profile'],scope='v9 kernel/SMMU/text-console update on existing memory-v8 boot and macosroot',
          ci_run=index['run'],source_commit=index['commit'],deploy_kernel_sha256=expected['kernel.macho'],
          raw_kernel=record(ci/'kernel/kernel.macho'),ci_payload=record(ci/'payload/payload.img'),
          kernel_command_line=line,outputs={'esp.img':record(esp)},esp_files=members,retained_loader_modules=retained,
          build_status=dict(delivery_version='b5q-esp-kernel-v9',flash_candidate_ready=True,esp_install_required=True,root_read_only=True,data_volatile=True,esp_fat_sector_bytes=4096,esp_sectors_per_cluster=1,hardware_boot_verified=False),
          checks=dict(mapping_complete=True,missing_symbols={},post_reseal_idempotent=True,root_policies_bound=True,adt_typed_properties=True,fat_roundtrip=True),hardware_tested=False)
        (package/'package.manifest.json').write_text(json.dumps(delivery,indent=2)+'\n')
        if a.qemu:
            for name,extra in [('delivery',[]),('virt-gic',['--virt-gic'])]:
                target=out/'host-checks'/name
                run([sys.executable,ROOT/'scripts/b5q-install/check-lowdram-boot.py','--package',package,'--out',target,'--cpu','cortex-a710','--icount','shift=0,sleep=on',*extra])
                for file in ['memory.bin','bootargs.bin','tree.bin','entry.S','entry.elf']:(target/file).unlink(missing_ok=True)
            delivery['checks']['qemu']={name:json.loads((out/'host-checks'/name/'summary.json').read_text())['terminal_reason'] for name in ['delivery','virt-gic']}
        (out/'package.manifest.json').write_text(json.dumps(delivery,indent=2)+'\n')
    log.close();print(json.dumps({'out':str(out),'outputs':delivery['outputs'],'kernel_sha256':delivery['deploy_kernel_sha256']},indent=2))
if __name__=='__main__':main()
