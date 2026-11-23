#!/usr/bin/env python3
"""Exercise the real DarwinBoot range functions with captured b5q inputs."""
from pathlib import Path
import json,runpy,tomllib
ROOT=Path(__file__).resolve().parents[2]
r=json.loads((ROOT/'UniXNU-b5q/reports/batch2-inputs.json').read_text())
b=tomllib.loads((ROOT/'UniXNU-b5q/board.toml').read_text());a=b['payload']['adt']
functions=runpy.run_path(str(ROOT/'sources/UniXNU/drivers/DarwinBoot/Test/test-memory-window.py'))
outside=runpy.run_path(str(ROOT/'sources/UniXNU/drivers/DarwinBoot/Test/test-memory-outside.py'))['run']
free=[(7,int(x['base'],0),x['bytes'])for x in r['candidate_safe_fragments_before_runtime_EFI_allocations']]
span=int(a['owned_memory_size'],0);head=0x18000000
base,usable=functions['start'](free,0x4000,head,span)
assert base>=0x880000000 and base+head<=0x8b9a00000
excluded=functions['exclusions'](free,base,span,128)
assert sum(n for _,n in excluded)+usable==span
holes=[tuple(map(lambda s:int(s,0),x.split(':')))for x in a['owned_memory_outside_reserved']]
def subtract(rs):
 for lo,n in holes:
  hi=lo+n;rs=[(a,b)for l,h in rs for a,b in [(l,min(lo,h)),(max(hi,l),h)]if a<b]
 return rs
raw=outside(free,base,span,16);low=subtract([(a,a+n)for a,n in raw])
assert all(0x80000000<=a<z<=0x100000000 for a,z in low)
assert max(z for _,z in low)-min(a for a,_ in low)<4<<30
predicted=usable+sum(z-a for a,z in low)
assert predicted>=6<<30
# No reserved byte can enter either aperture.
for group in [r['linux_memory_reserved'],r['UEFI_static_reservations']]:
 for x in group:
  lo,hi=int(x['base'],0),int(x['end_exclusive'],0)
  assert not any(max(lo,z)<min(hi,h) for z,h in low)
# Runtime reservation pressure reduces the usable count, never silently
# promotes a boot-services/runtime range. The kernel's explicit >=6GiB
# floor is 4.5GiB; 6GiB remains an observation target, not a forced outcome.
pressure=[]
for carve in (0,128<<20,384<<20,640<<20):
 changed=[]
 for kind,start,n in free:
  if start==0x8c0000000 and carve:
   changed += [(kind,start,n-carve),(4,start+n-carve,carve)]
  else:changed.append((kind,start,n))
 actual,bytes_=functions['start'](changed,0x4000,head,span)
 pairs=outside(changed,actual,span,16);low2=subtract([(a,a+n)for a,n in pairs])
 physical=bytes_+sum(z-a for a,z in low2)
 pressure.append({'firmware_carve_bytes':carve,'model_usable_bytes':physical,'persistent_profile_admitted':physical>=9<<29,'target_6GiB_met':physical>=6<<30})
 assert physical<=predicted
 # Every reserved pressure block appears in the real exclusion table.
 if carve:
  table=functions['exclusions'](changed,actual,span,128)
  assert any(a<=0xa00000000-carve and a+n>=0xa00000000 for a,n in table)
result={'passed':True,'evidence_scope':'production allocator/exclusion/outside functions with captured-FDT/static-UEFI-derived synthetic maps; not a final EFI map or hardware RAM claim',
 'span':hex(span),'candidate_base':hex(base),'model_inside_bytes':usable,'model_low_outside_ranges':[{'base':hex(a),'bytes':z-a}for a,z in low],
 'model_total_GiB_before_runtime_EFI_allocations':predicted/2**30,'runtime_pressure_cases':pressure,
 'usb_domain_limit':hex(0x1000000000),'owned_end_within_36bit':base+span<=0x1000000000,
 'hardware_memory_qualified':False,'required_runtime_gate':'B5qMemory max_mem>=4.5GiB; target>=6GiB after existing EARLY_BOOT outside adoption; no assumed hardware outcome'}
(ROOT/'artifacts/b5q-batch2-work/memory-model.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
