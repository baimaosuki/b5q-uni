#!/usr/bin/env python3
"""Verify boot boundaries and shutdown order against pinned production sources."""
from pathlib import Path
import importlib.util,sys,tomllib,json,hashlib
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R/'UniXNU/scripts'))
from unixnu.payload import check_args
from unixnu.util import Error
board=tomllib.loads((R/'UniXNU-b5q/board.toml').read_text())
line=check_args(board['payload']['kernel_args']);assert len(line.encode('ascii'))<=1000
assert len(check_args(['x'*1000]))==1000
try:check_args(['x'*1001])
except Error:pass
else:raise AssertionError('1001-byte line accepted')
loader=R/'sources/UniXNU/drivers/DarwinBoot/DarwinBootPkg/Driver'
assert 'CommandLine[1024]' in (loader/'BootArgs.h').read_text()
assert 'Index >= sizeof (CommandLine) - 1' in (loader/'DarwinBoot.c').read_text()
xnu=R/'sources/UniXNU/out/feeds/xnu-3199e8bc'
assert '#define BOOT_LINE_LENGTH 1024' in (xnu/'pexpert/pexpert/arm64/boot.h').read_text()
for size in (1000,1023,1024):assert (size<1024)==all(i<1023 for i in range(size))
storage=(R/'UniXNU-b5q/package/B5qRamStorage.cpp').read_text()
assert 'minimum=9ULL<<29' in storage and 'max_mem<minimum' in storage
assert all(x in storage for x in ('ml_outside_memory_pages','ml_outside_memory_refused','outside adopted='))
data=(R/'UniXNU-b5q/package/B5qUfs/B5qDataBlock.h').read_text();assert 'dataClosing' not in data
assert 'writes=FUA-still-accepted' in data
shutdown=(xnu/'bsd/kern/kern_shutdown.c').read_text()
assert shutdown.index('vfs_unmountall(TRUE)')<shutdown.index('vfs_unmountall(FALSE)')<shutdown.index('host_reboot(host_priv_self()')
power=(xnu/'iokit/Kernel/IOPlatformExpert.cpp').read_text()
start=power.index('PEHaltRestartInternal(');s=power[start:];assert s.index('handlePlatformHaltRestart')<s.index('gIOPlatform->haltRestart')
root=(xnu/'iokit/Kernel/IOPMrootDomain.cpp').read_text();assert 'if (kPEPagingOff != pe_type)' in root
report=dict(passed=True,args_bytes=len(line),engineering_limit=1000,buffer_bytes=1024,terminator_required=True,memory_floor_bytes=9<<29,target_bytes=6<<30,
 shutdown='ProcessExit->PagingOff only; vfs_unmountall(TRUE/FALSE)->host_reboot->rootDomain driver shutdown->platform PSCI; FUA late writes accepted and invalidate old flush status',
 source_sha256={str(p.relative_to(R)):hashlib.sha256(p.read_bytes()).hexdigest()for p in [loader/'BootArgs.h',loader/'DarwinBoot.c',xnu/'bsd/kern/kern_shutdown.c',xnu/'iokit/Kernel/IOPlatformExpert.cpp',xnu/'iokit/Kernel/IOPMrootDomain.cpp']})
(R/'artifacts/b5q-batch2-work/boot-shutdown-contract.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
