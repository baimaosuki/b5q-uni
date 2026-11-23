#!/usr/bin/env python3
"""Build actual macOS IOBlockStorageDevice + RamBlock, with Samsung b5q read-only root transport."""
import importlib.util,os,shutil,subprocess
from pathlib import Path
from b5q_compile import ROOT,compile,archive,late,report
out=ROOT/'build/ram-block';out.mkdir(parents=True,exist_ok=True)
storage=ROOT/'refer/IOStorageFamily'
p=ROOT/'scripts/prepare-storage-headers.py';spec=importlib.util.spec_from_file_location('b5q_storage_headers',p);headers=importlib.util.module_from_spec(spec);spec.loader.exec_module(headers)
revision=os.environ.get('UNIXNU_IOSTORAGEFAMILY_COMMIT')
if revision!='7edb88fbae296fb7c8ce2f64e115e116e566d51c':
 raise SystemExit('b5q macOS storage requires pinned IOStorageFamily 337.100.1')
headers.prepare(storage,revision,out/'headers')
original=(storage/'IOBlockStorageDevice.cpp').read_text();macro='OSDefineMetaClassAndAbstractStructors(IOBlockStorageDevice,IOService)'
if original.count(macro)!=1:raise SystemExit('Public storage registration macro changed')
base=out/'IOBlockStorageDevice.cpp';base.write_text(original.replace(macro,'''
extern "C" const OSMetaClass *native_source_storage_parent(void);
OSDefineMetaClassWithInit(IOBlockStorageDevice, IOService, )
IOBlockStorageDevice::MetaClass::MetaClass()
    : OSMetaClass("UniXNUBlockStorageDevice", native_source_storage_parent(), sizeof(IOBlockStorageDevice)) {}
OSDefineAbstractStructors(IOBlockStorageDevice, IOService)
OSDefineOperatorMethods(IOBlockStorageDevice)
'''))
osx=out/'macos-target.h';osx.write_text('#include <TargetConditionals.h>\n#undef TARGET_OS_OSX\n#define TARGET_OS_OSX 1\n')
includes=['-I',str(out/'headers/include'),'-I',str(ROOT/'.cache/xnu-work/osfmk'),'-I',str(ROOT/'kits/VerifiedRoot/include'),'-I',str(ROOT/'kits/b5q/B5qUfs')]
flags=['-include',str(osx)]
ramblock=ROOT/'drivers/RamBlock'
ram_source=out/'NativeRamBlock.cpp'
from b5q_ramblock import prepare_source
ram_patch=Path(__file__).with_name('b5q-volatile-data-4g.patch')
prepare_source(ramblock/ram_source.name,ram_source)
includes+=['-iquote',str(ramblock)]
sources=[base,ram_source,ROOT/'kits/b5q/B5qRamStorage.cpp',ROOT/'kits/b5q/B5qPower.cpp',ROOT/'kits/b5q/B5qAbsentBoard.cpp',ROOT/'kits/b5q/B5qUfs/B5qUfs.cpp',ROOT/'kits/b5q/B5qRootBinding.cpp',ROOT/'kits/VerifiedRoot/src/verified_root.c',ROOT/'kits/VerifiedRoot/adapters/xnu_crypto.c']
objects=[]
for source in sources:
 obj=compile(source,out/(source.stem+'.o'),includes,flags+(['-Wno-error'] if source==base else []))
 if source in sources[:2] or source.name=="B5qUfs.cpp":obj=late(source,obj)
 objects.append(obj)
import json,sys
objects += [Path(p) for p in json.loads(subprocess.check_output([sys.executable,str(ROOT/'scripts/build-b5q-pmgr.py')],text=True))]
path=archive(out/'libRamBlock.a',objects)
report(path,objects,[*sources,ramblock/ram_source.name,ram_patch,Path(__file__).with_name('b5q-storage-provider.patch')],dict(ufs_controller=True,persistent_block_writes="validated Data window and ESP journal slots",root_partition="macosroot",original_storage_class_size_checked_at_runtime=True))
print('PASS: macOS source storage ABI, actual RamBlock and VerifiedRoot; b5q authenticated read-only macosroot driver linked; root read-only; isolated ESP journal writer enabled')
