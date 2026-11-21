#!/usr/bin/env python3
"""Accept returned native-v24 artifacts using actual ESP and object bytes."""
import argparse,hashlib,importlib.util,json,shutil,struct,subprocess,sys,tempfile,tomllib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT/'sources/UniXNU/kits/XnuPrelink'),str(ROOT/'UniXNU-b5q/scripts'),str(ROOT/'sources/UniXNU/drivers/DarwinBoot/Test')]
from kc_image import Image
import packed_ramdisk
from b5q_abi import object_symbols,macho
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--ci',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--objects-ci',type=Path);a=p.parse_args();ci=a.ci.resolve();objects_ci=a.objects_ci.resolve() if a.objects_ci else ci;out=a.out.resolve();out.mkdir(exist_ok=True)
def sha(p):
 with p.open('rb')as f:return hashlib.file_digest(f,'sha256').hexdigest()
def invoke(args):subprocess.run([str(x)for x in args],check=True)
board=tomllib.loads((ROOT/'UniXNU-b5q/board.toml').read_text());index=json.loads((ci/'transfer-index.json').read_text());report={'checks':{},'hardware_executed':False,'run':index['run'],'commit':index['commit']}
esp=ci/'esp.img' if (ci/'esp.img').exists() else out/'esp.img'
with esp.open('rb')as f:b=f.read(4096)
assert esp.stat().st_size==800*2**20 and struct.unpack_from('<H',b,11)[0]==4096 and b[13]==1 and b[16]==2 and b[82:90]==b'FAT32   'and b[510:512]==b'\x55\xaa'
assert struct.unpack_from('<I',b,32)[0]*4096==esp.stat().st_size and struct.unpack_from('<I',b,36)[0]<=256
report['checks']['FAT32_4Kn_800MiB']=True
invoke(['fsck.fat','-n',esp])
spec=importlib.util.spec_from_file_location('b5qesp',ROOT/'scripts/b5q-install/build-ci-esp.py');fmt=importlib.util.module_from_spec(spec);spec.loader.exec_module(fmt)
abi_module=__import__('importlib').machinery.SourceFileLoader('nativeusb',str(ROOT/'UniXNU-b5q/scripts/build-b5q-usb.py')).load_module()
with tempfile.TemporaryDirectory(prefix='b5q-v24-accept-')as td:
 temp=Path(td)
 for name in ['kernel.macho','kernel.macho.adt','scratch-data.img','kernel.macho.gpuaddon','kernel.macho.trustcache']:
  invoke(['mcopy','-i',esp,'::/EFI/UniXNU/Payloads/'+name,temp/name])
 invoke(['mcopy','-i',esp,'::/EFI/UniXNU/unixnu.toml',temp/'unixnu.toml'])
 menu=tomllib.loads((temp/'unixnu.toml').read_text());entry=next(e for e in menu['entry']if e.get('type')=='xnu')
 assert entry['args']==' '.join(board['payload']['kernel_args'])and len(entry['args'].encode())<1024
 assert menu['boot']['default']=='xnu'and menu['driver']==[{'path':'Drivers/DarwinBoot.efi'}]
 nodes=fmt.adt_decode((temp/'kernel.macho.adt').read_bytes());assert nodes['/chosen']['text-fixups']==b''.join(x.encode()+b'\0'for x in board['payload']['text_fixups'])
 assert nodes['/chosen']['dram-base']==struct.pack('<Q',0x80000000)and nodes['/chosen']['dram-size']==struct.pack('<Q',0x80000000)
 assert nodes['/chosen']['kernel-ctrr-to-be-enabled']==struct.pack('<I',0)and nodes['/defaults']['sleep-disabled']==struct.pack('<I',1)
 cpuclasses={nodes['/cpus/cpu'+str(i)]['cluster-type']for i in range(8)};assert cpuclasses=={struct.pack('<I',ord('E')),struct.pack('<I',ord('P'))},cpuclasses
 inv=json.loads((ROOT/'UniXNU-b5q/reports/samsung-gpu-inputs.json').read_text())
 for name,key in [('gmu_gen70200.bin','b5q-gmu-fw'),('a740_sqe.fw','b5q-sqe-fw'),('a740_zap.mbn','b5q-zap-fw')]:assert hashlib.sha256(nodes['/chosen'][key]).hexdigest()==inv['files'][name]['sha256']
 report['checks']['boot_args_ADT_two_clusters_firmware']=True;report['boot_args_bytes']=len(entry['args'].encode())
 payload=json.loads((ci/'payload/payload.json').read_text())
 for name,key in [('kernel.macho','payload_kernel_sha256'),('kernel.macho.adt','adt_sha256'),('scratch-data.img','data_ramdisk_sha256'),('kernel.macho.gpuaddon','gpu_addon_sha256'),('kernel.macho.trustcache','trust_cache_sha256')]:assert sha(temp/name)==payload[key],name
 raw=(temp/'kernel.macho').read_bytes();outer=Image(raw);im=Image(raw,outer.entries['com.apple.kernel'][1]);names={n:v for v,rows in im.symbols().items()for n in rows}
 for name in ['_sheng_cpu_idle_mach','_sheng_edge_cross_type_steals','_sheng_edge_idle_beside_excess','_sheng_edge_idle_beside_queued','_qcom_dwc3_bring_up','_qcom_dwc3_publish','_sheng_usb_probe','_b5q_usb_repeater','_b5q_usb_typec_init','_b5q_usb_otg','_b5q_usb_cable_role','__ZTV12QcomDwc3Xdci','__ZTV12QcomDwc3Xhci']:
  assert name in names,name
 assert '__ZTV10B5qUsbHost'not in names
 # Inspect actual N_SECT/global/nonweak flags on the new core helper.
 symtab=im.command(2)[0];symoff,count,strings,_=struct.unpack_from('<4I',raw,symtab+8);helper=[]
 for i in range(count):
  sx,kind,section,desc,value=struct.unpack_from('<IBBHQ',raw,symoff+16*i)
  if not kind&0xe0 and raw[strings+sx:raw.index(b'\0',strings+sx)]==b'_sheng_cpu_idle_mach':helper.append((kind,desc))
 assert helper and all(kind&0xe==0xe and kind&1 and not desc&0x80 for kind,desc in helper),helper
 from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
 helper_va=names['_sheng_cpu_idle_mach'];helper_end=min(v for v in names.values()if v>helper_va)
 instructions=list(Cs(CS_ARCH_ARM64,CS_MODE_ARM).disasm(im.read(helper_va,helper_end-helper_va),helper_va))
 assert any(i.mnemonic=='bl'and int(i.op_str[1:],16)==names['_recount_processor_usage']for i in instructions)
 report['checks']['strong_recount_and_native_USB_symbols']=True
 report['checks']['real_recount_call_and_Edge_counters']=True
 for kind,cls in [('xdci','QcomDwc3Xdci'),('xhci','QcomDwc3Xhci')]:
  abi=json.loads((ROOT/'UniXNU-b5q/scripts'/('usb-'+kind+'-26C5035r.json')).read_text());words=struct.unpack('<'+str(len(abi['slots']))+'Q',im.read(names['__ZTV'+str(len(cls))+cls]+16,8*len(abi['slots'])))
  assert all(v>>32&0xffff==int(slot[1],16)for v,slot in zip(words,abi['slots']));report['checks'][kind+'_vtable_PAC_slots']=len(words)
 for old in [b'B5qUsb: stage=warm-clocks',b'ppid=7fd',b'b5q-usb-delay'] :assert old not in raw,old
 for text in [b'qcom-dwc3: SID=40',b'TI3e version=',b'Charger69 OTG=',b'enable-report ok11=',b'EINT=%u HSE=%u']:assert text in raw,text
 # The ordered QMP table in the linked kernel is the FDT-derived 168-pair table.
 inp=json.loads((ROOT/'UniXNU-b5q/reports/usb-inputs-v24.json').read_text());table=b''.join(struct.pack('<HBB',o,v,0)for o,v in inp['qmp']['ordered_pairs']);assert table in raw
 report['checks']['QMP168_linked_and_old_warm_removed']=True
 invoke([sys.executable,ROOT/'scripts/b5q-install/verify-esp-log.py','--esp',esp,'--out',out/'log-allocation.json'])
 invoke([sys.executable,ROOT/'tests/b5q-ufs/test-post-seal.py','--kernel',temp/'kernel.macho','--out',out/'post-seal.json'])
 logical,_=packed_ramdisk.regions((temp/'scratch-data.img').read_bytes());assert logical==4*2**30
 invoke([sys.executable,ROOT/'scripts/b5q-install/verify-data-account.py','--seed',temp/'scratch-data.img','--gib','4','--out',out/'data-account.json'])
 report['checks']['actual_4GiB_APFS_account_watchdogd']=True
 # Keep a single small deployment manifest for established signature/root validators.
 delivery={'deploy_kernel_sha256':sha(temp/'kernel.macho'),'data_logical_bytes':logical,'kernel_command_line':entry['args'],'esp_files':{},'outputs':{'esp.img':{'bytes':esp.stat().st_size,'sha256':sha(esp)}},'ci_run':index['run'],'source_commit':index['commit']}
 (out/'package.manifest.json').write_text(json.dumps(delivery,indent=2)+'\n')
 if esp.resolve()!=(out/'esp.img').resolve():esp.replace(out/'esp.img')
 invoke([sys.executable,ROOT/'scripts/b5q-install/verify-mount-runtime.py','--package',out])
 report['checks']['bootshim_signatures_trust_APFS_checksums']=True
 report['kernel']={'bytes':len(raw),'sha256':sha(temp/'kernel.macho')}
 # Production callbacks compiled on the actual CI Xcode, with new core dispatcher.
 objdir=out/'callback-objects';objdir.mkdir(exist_ok=True)
 def find(name):
  found=list(objects_ci.rglob(name));assert found,(name,len(found));assert len({sha(x)for x in found})==1,(name,'differentduplicateobjects');return found[0]
 for name in ['BoardClock.o','ButtonProbe.o','NativeHidInput.o','B5qTouch.o','ThermalLevel.o','IOUserClient.cpo','ArmDTPlatform.o']:
  shutil.copyfile(find(name),objdir/name)
 arm=find('ArmCpu.o');gpuarchive=find('libAdreno740.a')
 llvm=Path('/home/baimao/nabu_macos/out/nabu-27.3-fresh/p025-m2v/toolchain/llvm21/usr/lib/llvm-21/bin')
 # ar extraction itself needs no target execution.
 ar='ar'
 for member in ['B5qGpu.o','ShengGmu.kit.o']:
  data=subprocess.check_output([ar,'p',str(gpuarchive),member]);(objdir/member).write_bytes(data)
 invoke([sys.executable,ROOT/'scripts/b5q-install/check-usb-gmu-pac.py','--usb',find('QcomDwc3.o'),'--armcpu',arm,'--gpu',objdir/'B5qGpu.o','--gmu',objdir/'ShengGmu.kit.o','--extended-dir',objdir,'--out',out/'actual-cross-object-pac.json'])
 for n in ['B5qUsbBoard.o','GeniI2c.o'] :shutil.copyfile(find(n),objdir/n)
 for producer in ['B5qUsbBoard.o','B5qTouch.o']:invoke([sys.executable,ROOT/'scripts/b5q-install/check-geni-pac.py','--objects',objdir,'--producer',producer,'--out',out/(producer+'.PAC.json')])
 usb=abi_module.all_bindings(find('QcomDwc3.o').read_bytes());expected=json.loads((ROOT/'UniXNU-b5q/scripts/usb-dual-bindings-26C5035r.json').read_text());assert {n:hex(v)for n,v in usb[0].items()}==expected['bindings']
 report['checks']['actual_Xcode_ABI_all_callbacks_PAC']=True
 recount=json.loads(find('native-recount-build.json').read_text());assert recount['B5Q_HAVE_CPU_IDLE_MACH']==1
 report['checks']['native_core_object_detection']=recount
 report['core_archive']={'bytes':find('mach.development.bcm2837.a').stat().st_size,'sha256':sha(find('mach.development.bcm2837.a'))}
 assert report['core_archive']['sha256']!='1fce36d7ee6c79cb2b1aca01b3635cdda568c8dadef6a5c3490007610a3a3d3b'
 report['passed']=True;report['ESP']={'bytes':(out/'esp.img').stat().st_size,'sha256':sha(out/'esp.img')}
 (out/'v24-verification.json').write_text(json.dumps(report,indent=2)+'\n')
 shutil.rmtree(objdir)
 print(json.dumps({'passed':True,'run':index['run'],'ESP':report['ESP'],'kernel':report['kernel'],'checks':list(report['checks'])},indent=2))
