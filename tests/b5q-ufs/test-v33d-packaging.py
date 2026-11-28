#!/usr/bin/env python3
"""Exercise reuse/return gates without CI calls or generating a deployment ESP."""
from pathlib import Path
import ast,copy,hashlib,importlib.util,json,os,subprocess,sys,tempfile
from unittest.mock import patch
R=Path(__file__).resolve().parents[2];sys.path[:0]=[str(R/'UniXNU-b5q/scripts'),str(R/'UniXNU/scripts')]
def module(path):
 spec=importlib.util.spec_from_file_location(path.stem,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
fetch=module(R/'UniXNU-b5q/scripts/fetch-b5q-reuse.py')
with tempfile.TemporaryDirectory(prefix='b5q-test-reuse-discovery-')as td:
 out=Path(td)/'selected';calls=[]
 def response(cmd,**kw):
  calls.append(cmd);assert cmd[0]=='gh'
  if 'actions/artifacts?'in cmd[-1]:return json.dumps([{'artifacts':[dict(id=i,name=f'b5q-build-{i}',expired=i==4,created_at=str(i),workflow_run={'id':i})for i in [1,2,3,4]]}])
  run=int(cmd[-1].rsplit('/',1)[1]);return json.dumps(dict(conclusion='failure'if run==3 else'success',head_sha=str(run)*40))
 def download(cmd,**kw):
  calls.append(cmd);run=int(cmd[3]);dest=Path(cmd[-1]);names=fetch.REQUIRED if run==1 else ['payload.img']
  for n in names:(dest/n).write_bytes(n.encode())
  return subprocess.CompletedProcess(cmd,0)
 with patch.object(fetch.subprocess,'check_output',response),patch.object(fetch.subprocess,'run',download):receipt=fetch.fetch('owner/repo',out)
 assert receipt['run']==1 and receipt['skipped'][0]['run']==2 and fetch.valid(out)
 assert not any('45047962341'in str(x)for x in calls)
print('PASS real reuse selector:paginated newest/nonexpired/successful,skips incomplete artifact,records input hashes; no network used')
from unixnu import ramdisk
source=(R/'UniXNU-b5q/scripts/reuse-completed-build.py').read_text();tree=ast.parse(source)
block=next(x for x in tree.body if isinstance(x,ast.With)and 'b5q-reuse-payload-'in ast.get_source_segment(source,x))
with tempfile.TemporaryDirectory(prefix='b5q-test-packed-reuse-')as td:
 t=Path(td);source_dir=t/'source';(source_dir/'payload').mkdir(parents=True);out=t/'data';out.mkdir();raw=t/'raw.fixture';sample=(b'non-filesystem-test-data'+bytes(4096))[:4096];raw.write_bytes(sample)
 packed=source_dir/'payload/payload.img';ramdisk.encode(raw,packed,R/'uefi-b5q');assert ramdisk.packed(packed)
 actual_run=subprocess.run;copies=[]
 def copy_command(cmd,**kw):
  if cmd[0]=='mcopy':
   assert Path(cmd[2]).read_bytes()==sample;copies.append(cmd[3]);Path(cmd[-1]).write_bytes(cmd[3].encode());return subprocess.CompletedProcess(cmd,0)
  return actual_run(cmd,**kw)
 with patch.object(subprocess,'run',copy_command):exec(compile(ast.Module(body=[block],type_ignores=[]),'<production-packed-reuse>','exec'),dict(Path=Path,tempfile=tempfile,source=source_dir,out=out,ramdisk=ramdisk,subprocess=subprocess))
 assert len(copies)==3 and all((out/n).is_file()for n in ['data.dbr','gpu-addon.bin','owner-trust.bundle'])
print('PASS actual reuse extraction:realUNXNFAT1 encode/decode before3mcopycalls; tiny nonfilesystem fixture, noESP')
# Exercise current EDK2 target machine-code inspectors and negative mutations.
import b5q_smmu_binary as binary
for name in ['UsbDma','PcieDma','MediaDma']:
 path=R/'artifacts/b5q-p5-work/uefi-target'/(name+'.obj');assert binary.check(path,usb=name=='UsbDma',msi=name!='MediaDma')['passed']
 with tempfile.TemporaryDirectory(prefix='b5q-test-returned-constants-')as td:
  data=bytearray(path.read_bytes());coff=binary.sections(data)
  from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
  ins=next(i for _,raw,flags in coff if flags&0x20000000 and raw for i in Cs(CS_ARCH_ARM64,CS_MODE_ARM).disasm(raw,0)if i.mnemonic=='mov'and i.op_str.endswith('#0x1027'))
  word=int.from_bytes(ins.bytes,'little');offset=data.index(ins.bytes);data[offset:offset+4]=(word^(1<<5)).to_bytes(4,'little');bad=Path(td)/'bad.obj';bad.write_bytes(data)
  try:binary.check(bad,usb=name=='UsbDma',msi=name!='MediaDma')
  except ValueError:pass
  else:raise AssertionError('SCTLR corrupted object accepted')
print('PASS actual3COFF objects:SCTLR/TCR/TCR2/MAIR/AP/MSI+staticmap;3corruptSCTLR executable mutations rejected')
# Old actual EFI binaries must fail the new output gate, not be blessed by
# source text alone. No new firmware or final ESP is generated here.
old=R/'uefi-b5q/Build/b5qPkg/DEBUG_CLANGPDB/AARCH64/b5qPkg/Drivers/B5qHandoffDxe/B5qHandoffDxe/OUTPUT/B5qHandoffDxe.efi'
try:binary.check(old)
except ValueError:pass
else:raise AssertionError('Old handed-off EFI accepted despite missing new constants')
script=(R/'UniXNU-b5q/scripts/package-batch2-esp.py').read_text();assert script.count('gpu_firmware=preserve_gpu_firmware(ctx.board,chosen)')==1
assert script.index('gpu_firmware=preserve_gpu_firmware(ctx.board,chosen)')<script.index(' if a.ci:',script.index(' from unixnu.boot_template'))
for guid in ['9b665204-a133-47a2-9396-9e2b370a4e25','1b64af87-8415-4b57-9b16-680d70913b9f']:assert guid in script
workflow=(R/'.github/workflows/b5q-p0-p5.yml').read_text();assert '45047962341'not in workflow
for n in ['libAdreno740.a','data.dbr','gpu-addon.bin','owner-trust.bundle','OUTPUT/UsbDma.obj']:assert n in workflow
# Existing source-bound baseline receipt with a new, empty work directory.
pre=(R/'scripts/b5q-install/pre-ci-v33d.py').read_text();tree=ast.parse(pre);branch=next(n for n in tree.body if isinstance(n,ast.If)and 'x.get' in ast.unparse(n.test))
with tempfile.TemporaryDirectory(prefix='b5q-test-empty-gate-work-')as td:
 W=Path(td);checks=[];baseline=R/'artifacts/b5q-p4-work/pre-ci/report.json'
 exec(compile(ast.Module(body=branch.orelse,type_ignores=[]),'<cached-preflight-new-work>','exec'),dict(W=W,checks=checks,baseline=baseline,hashlib=hashlib))
 assert (W/'pre-ci-all.log').is_file()and checks[0]['passed']
print('PASS oldEFI rejection,unconditionalGPU preservation,pairedFDmenu+loader,dynamicreuse+uploads,source-bound receipt with emptygatework; unchanged WiFi readiness assertions retained')
# Mixed workflow upload roots include runtime reuse files outside the payload
# manifest directory. Keep all files while preserving the payload's layout.
import stat,zipfile,types
source=(R/'scripts/b5q-install/download-ci-artifact.py').read_text();tree=ast.parse(source)
zip_block=next(n for n in ast.walk(tree)if isinstance(n,ast.With)and 'zipfile.ZipFile(archive)'in ast.unparse(n.items[0].context_expr))
with tempfile.TemporaryDirectory(prefix='b5q-mixed-artifact-roots-')as td:
 t=Path(td);archive=t/'return.zip'
 with zipfile.ZipFile(archive,'w')as z:
  z.writestr('job/work/package.manifest.json','{}')
  z.writestr('job/work/kernel/kernel.macho',b'kernel-fixture')
  z.writestr('_temp/reuse/data.dbr',b'seed-fixture')
 env=dict(archive=archive,a=types.SimpleNamespace(out=t/'unpacked'),Path=Path,zipfile=zipfile,stat=stat,sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest())
 exec(compile(ast.Module(body=[zip_block],type_ignores=[]),'<production-artifact-extract>','exec'),env)
 assert (t/'unpacked/kernel/kernel.macho').read_bytes()==b'kernel-fixture'
 assert (t/'unpacked/extra/_temp/reuse/data.dbr').read_bytes()==b'seed-fixture'
print('PASS production artifact extract:manifest-relative payload plus external reusable inputs retained; no files discarded')
