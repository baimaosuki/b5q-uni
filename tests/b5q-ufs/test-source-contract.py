#!/usr/bin/env python3
"""Independent source-boundary checks alongside actual parser mutation tests."""
from pathlib import Path
import json,hashlib,tomllib
root=Path(__file__).resolve().parents[2];device=root/'UniXNU-b5q';source=(device/'package/B5qUfs/B5qUfs.cpp').read_text();fmt=(device/'package/B5qUfs/B5qRootFormat.h').read_text();board=tomllib.loads((device/'board.toml').read_text());config=(device/'configs/b5q_macos_defconfig').read_text();recipe=(device/'scripts/build-b5q-storage.py').read_text()
assert '0x01d84000,0x3000' in source and '0x15000000,0x100000' in source
smmu=(device/'package/B5qUfs/B5qSmmu.h').read_text()
assert '0x80000060U' in smmu and '0x1401' not in source+smmu
assert 'if(!normalUnit(lun))' in source and 'if(unit[4]!=0)' in source and 'last<lastLba' in source
protocol=(device/'package/B5qUfs/B5qUfsProtocol.h').read_text()
assert 'cdb[0]==0x9e&&cdb[1]==0x10' in protocol and 'cdb[0]==0x88' in protocol
assert 'if(!wakeDevice())' in source and 'ready(lun,readinessCommand' in source
assert 'if(lun==0xd0)' in protocol and 'cdb[4]!=0x10' in protocol
assert 'host.selected||lba<1||lba>264||count>265-lba' in source
assert 'lun!=host.lun||lba<firstLba||lba>lastLba' in source
assert 'out.entriesLba>64' in fmt and '265-out.entriesLba' in fmt
assert 'vr_open_header(' in source and 'vr_open(' in source and 'vr_verify_block(' in source
assert 'VM_PROT_READ' in source and 'OSDynamicCast(B5qRootBlock' in source
assert 'b5q-root=1' in board['payload']['kernel_args']
assert 'native-ufs-root=1' not in board['payload']['kernel_args'] # retained upstream sheng PMGR preflight is not this implementation
assert 'vmm-present' not in board.get('adt',{}).get('defaults',{}).get('u32',{})
assert 'B5qRootBinding.cpp' in recipe and 'B5qUfs.cpp' in recipe and 'SourceStorage.cpp' not in recipe
for flag in ['OWNER_ROOT_AUDIT','OWNER_ROOT_TRUST','OWNER_DATA_MOUNT','OWNER_CACHE_MOUNT','OWNER_BOOT_MANIFEST']:assert 'CONFIG_XNU_'+flag+'=y' in config
assert '1552CFEE-78FF-48D8-8A6C-694B867D61AC' in config
for name in ['native_ufs_store_write','native_ufs_store_write_cached','native_ufs_store_sync']:
 text=(device/'package/B5qAbsentBoard.cpp').read_text();assert name in text
report={'source_sha256':hashlib.sha256(source.encode()).hexdigest(),'host_checks':'PASS: board identity, command allowlist, metadata/root confinement, actual RSA/block verification call sites, real XNU root flags, no Xiaomi peripheral reuse','hardware_tested':False}
(root/'artifacts/b5q-firstboot/source-contract.json').write_text(json.dumps(report,indent=2)+'\n');print(report['host_checks'])
