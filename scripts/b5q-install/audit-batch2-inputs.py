#!/usr/bin/env python3
"""Read-only b5q memory/root/PSCI evidence. No phone or block-device access."""
import hashlib,json,re,runpy,struct
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
model=runpy.run_path(str(ROOT/'UniXNU-b5q/scripts/inventory-hardware.py'))
fdt=ROOT/'b5q-runtime.fdt';blob=fdt.read_bytes();nodes,_=model['parse_fdt'](blob)
def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def tuples(path):
 return [(int(x['base'],0),int(x['end_exclusive'],0))for x in model['reg'](nodes,path) if int(x['size'],0)]
def region(a,b):return {'base':hex(a),'end_exclusive':hex(b),'bytes':b-a}
def subtract(ranges,holes):
 for a,b in sorted(holes):
  ranges=[q for lo,hi in ranges for q in [(lo,min(a,hi)),(max(b,lo),hi)] if q[0]<q[1]]
 return sorted(ranges)
memory=tuples('/memory');reserved=[];records=[]
for name in nodes:
 if name.startswith('/reserved-memory/'):
  for a,b in tuples(name):reserved.append((a,b));records.append(dict(path=name,**region(a,b)))
map_path=ROOT/'uefi-b5q/Platforms/Samsung/b5qPkg/Library/MemoryMapLib/MemoryMapLib.c'
uefi=[]
for name,base,size in re.findall(r'\{"([^"]+)"\s*,\s*(0x[0-9a-fA-F]+)(?:ULL)?\s*,\s*(0x[0-9a-fA-F]+)(?:ULL)?',map_path.read_text()):
 a,z=int(base,16),int(size,16)
 if 0x80000000<=a<0x1000000000:reserved.append((a,a+z));uefi.append(dict(name=name,**region(a,a+z)))
safe=subtract(memory,reserved)
image=ROOT/'artifacts/b5q-full-27.3-26C5035r/delivery/macosroot.img'
with image.open('rb') as f:h=f.read(4096)
assert h[:8]==b'SHNGROOT' and struct.unpack_from('<II',h,8)==(2,6)
assert hashlib.sha256(h[:4064]).digest()==h[4064:]
total=struct.unpack_from('<Q',h,16)[0];assert total==image.stat().st_size==17603493888
first,last=49692663,62275574;dataFirst=last+1-30*2**30//4096
assert dataFirst>=first+(total+256*2**20)//4096
p=ROOT/'UniXNU-b5q/reports/batch2-inputs.json'
r={'runtime_fdt_sha256':sha(fdt),'source':'existing b5q SM-F731B /sys/firmware/fdt capture; no new device access',
'physical_dram_envelopes':[region(0x80000000,0x100000000),region(0x880000000,0xa00000000)],
'linux_memory_fragments':[region(a,b)for a,b in memory],
'linux_memory_reserved':records,'UEFI_static_reservations':uefi,'UEFI_memory_map_source_sha256':sha(map_path),
'firmware_patch_sha256':sha(ROOT/'patches/uefi-b5q/0002-b5q-live-high-memory.patch'),
'candidate_safe_fragments_before_runtime_EFI_allocations':[region(a,b)for a,b in safe],
'upper_bound_bytes_before_runtime_EFI_allocations':sum(b-a for a,b in safe),
'upper_bound_GiB_before_runtime_EFI_allocations':sum(b-a for a,b in safe)/2**30,
'largest_contiguous_safe_bytes':max(b-a for a,b in safe),
'known_runtime_owned':region(0x8c0004000,0x9c0004000),
'final_runtime_EFI_descriptor_capture':'not present as a machine-readable input; Linux FDT and static UEFI map are not a final EFI allocation map',
'memory_plan':'6 GiB span with excluded ranges plus low-bank outside-memory adoption; contiguous 6 GiB is impossible. Actual >=6 GiB after EFI reservations remains unproven.',
'root_header_sha256':hashlib.sha256(h).hexdigest(),'root_total_bytes':total,'root_first_lba':first,'root_last_lba':first+total//4096-1,
'partition_last_lba':last,'minimum_guard_bytes':256*2**20,'actual_guard_bytes':(dataFirst-first)*4096-total,
'data_window_first_lba':dataFirst,'data_window_last_lba':last,'data_window_bytes':30*2**30,
'data_header_blocks':256,'data_apfs_first_lba':dataFirst+256,'data_apfs_blocks':30*2**30//4096-256,
'PSCI':{name:{k:model['text'](v)for k,v in props.items()if k in ('method','compatible')}for name,props in nodes.items()if props.get('compatible')==b'arm,psci-1.0\0'},
'hardware_verified_new_configuration':False}
p.write_text(json.dumps(r,indent=2)+'\n')
print(json.dumps({k:r[k]for k in ('upper_bound_GiB_before_runtime_EFI_allocations','largest_contiguous_safe_bytes','root_total_bytes','root_last_lba','actual_guard_bytes','data_window_first_lba','data_window_last_lba','data_apfs_blocks')},indent=2))
