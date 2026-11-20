#!/usr/bin/env python3
"""Translate Samsung KGSL pwrlevels into the shared SM8550 HFI policy types."""
import argparse,hashlib,json,re,sys
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--unixnu',type=Path,required=True);p.add_argument('--dtb',type=Path,required=True);p.add_argument('--catalog',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
sys.path.insert(0,str(a.unixnu/'scripts'));from unixnu.devicetree import read_fdt,registers
root=read_fdt(a.dtb.read_bytes());nodes=list(root.walk());gpu=next(n for n in nodes if n.name=='qcom,kgsl-3d0@3d00000');gmu=next(n for n in nodes if n.name=='qcom,gmu@3d69000');smmu=next(n for n in nodes if n.name=='kgsl-smmu@3da0000')
bins=next(n for n in gpu.children if n.name=='qcom,gpu-pwrlevel-bins');bandwidth=gpu.cells('qcom,bus-table-ddr');records={}
for table in bins.children:
 entries=[]
 for n in table.children:
  if not n.enabled():continue
  hz=n.scalar('qcom,gpu-freq');level=n.scalar('qcom,level');index=n.scalar('qcom,bus-freq');assert 0<index<len(bandwidth) and hz%1000==0
  entries.append(dict(hz=hz,level=level,kbps=bandwidth[index],acd_present='qcom,acd-level'in n.properties,acd=n.scalar('qcom,acd-level',0)))
 entries.sort(key=lambda e:e['hz']);assert len(entries)<16 and len({e['hz']for e in entries})==len(entries)
 assert all(entries[i]['level']>=entries[i-1]['level']for i in range(1,len(entries)))
 records[table.name]={'sku_codes':table.cells('qcom,sku-codes'),'opps':[dict(hz=0,level=0,kbps=0,acd_present=False,acd=0)]+entries}
# Compile separate policies for both bins; selecting one is a runtime board
# input. Neither the model suffix nor a reference board selects the silicon bin.
gmu_cells=gmu.cells('qcom,gmu-freq-table');assert len(gmu_cells)%2==0
gmu_opps=[dict(hz=0,level=0,kbps=0,acd_present=False,acd=0)]+[dict(hz=gmu_cells[i],level=gmu_cells[i+1],kbps=0,acd_present=False,acd=0)for i in range(0,len(gmu_cells),2)]
pins=json.loads((a.unixnu/'scripts/data/adreno-inputs.json').read_text());expected=pins['linux']['files']['drivers/gpu/drm/msm/adreno/a6xx_catalog.c']['sha256'];assert hashlib.sha256(a.catalog.read_bytes()).hexdigest()==expected
record=re.search(r'\.chip_ids = ADRENO_CHIP_IDS\(0x43050a01\)([\s\S]*?)\.preempt_record_size',a.catalog.read_text())[1]
policies=[]
for name,body in re.findall(r'\{\s*\.name = "([A-Z0-9]+)",([^{}]+)\}',record):
 if name!='ACV':
  m=re.fullmatch(r'\s*\.buswidth = (\d+)\s*',body);assert m;policies.append(dict(name=name,buswidth=int(m[1]),fixed=0,perfmode=0,perfmode_kbps=0))
 else:
  m=re.fullmatch(r'\s*\.fixed = true,\s*\.perfmode = BIT\((\d+)\),\s*\.perfmode_bw = (\d+),\s*',body);assert m;policies.append(dict(name=name,buswidth=0,fixed=1,perfmode=1<<int(m[1]),perfmode_kbps=int(m[2])))
assert [e['name']for e in policies]==['SH0','MC0','ACV']
a.out.mkdir(parents=True,exist_ok=True)
common='/* Generated from b5q Samsung DT and pinned shared A740 catalog. */\n#include <stdint.h>\n#define SHENG_GMU_VOTES_CHIP_ID 0x43050a01u\ntypedef struct {uint64_t hz;uint32_t level,kbps,acd_present,acd;} ShengGmuOpp;\n'
for table,v in records.items():
 text=common
 for kind,rows in [('gpu',v['opps']),('gmu',gmu_opps)]:
  text+=f'#define SHENG_{kind.upper()}_OPPS {len(rows)}u\nstatic const ShengGmuOpp sheng_{kind}_opps[]={{\n'
  text+='\n'.join('{'+','.join(str(int(e[k]))for k in ['hz','level','kbps','acd_present','acd'])+'},'for e in rows)+'\n};\n'
 bw=sorted({e['kbps']for e in v['opps']});text+=f'#define SHENG_GPU_BANDWIDTHS {len(bw)}u\nstatic const uint32_t sheng_gpu_bandwidths[]={{'+','.join(map(str,bw))+'};\nstatic const AdrenoHfiBcm sheng_bcm_policy[3]={\n'
 text+='\n'.join('{.address=0,.unit=0,.width=0,.buswidth='+str(e['buswidth'])+',.vcd=0,.fixed='+str(e['fixed'])+',.perfmode='+str(e['perfmode'])+',.perfmode_kbps='+str(e['perfmode_kbps'])+'},'for e in policies)+'\n};\n'
 (a.out/('B5qGmuVotes-'+table.rsplit('-',1)[1]+'.h')).write_text(text)
# Explicit bin policies are retained; the generated default below uses only
# rows identical in both Samsung tables until an active SKU is bound.
tables=list(records.values());common_rows=[e for e in tables[0]['opps'] if e in tables[1]['opps']]
assert len(common_rows)>1
source=(a.out/'B5qGmuVotes-1.h').read_text()
for entry in tables[1]['opps']:
 if entry not in common_rows:
  source=source.replace('{'+','.join(str(int(entry[k]))for k in ['hz','level','kbps','acd_present','acd'])+'},\n','')
source=re.sub(r'#define SHENG_GPU_OPPS \d+u',f'#define SHENG_GPU_OPPS {len(common_rows)}u',source)
bw=sorted({e['kbps']for e in common_rows})
source=re.sub(r'#define SHENG_GPU_BANDWIDTHS \d+u',f'#define SHENG_GPU_BANDWIDTHS {len(bw)}u',source)
source=re.sub(r'sheng_gpu_bandwidths\[\]=\{[^}]+\}', 'sheng_gpu_bandwidths[]={'+','.join(map(str,bw))+'}',source)
(a.out/'B5qGmuVotes-common.h').write_text(source)
(a.out/'ShengGmuVotesSource.h').write_text('#pragma once\n#include "B5qGmuVotes-common.h"\n')
db=next(n for n in nodes if n.strings('compatible')==['qcom,cmd-db']);ranges=registers(db);assert len(ranges)==1;address,bytes_=ranges[0]
(a.out/'ShengGmuCommandDbSource.h').write_text(f'#include <stdint.h>\n#define SHENG_GMU_COMMAND_DB_BASE UINT64_C({address:#x})\n#define SHENG_GMU_COMMAND_DB_BYTES {bytes_}u\n')
for name,sid in [('gfx3d_user',0),('gfx3d_lpac',1),('gfx3d_secure',2)]:
 assert next(n for n in nodes if n.name==name).cells('iommus')==[smmu.scalar('phandle'),sid,0]
reg=registers(smmu)[0];assert reg==(0x3da0000,0x40000) and gmu.cells('iommus')[1]==5
(a.out/'ShengGpuSmmuSource.h').write_text(f'#include <stdint.h>\n#define SHENG_GPU_SMMU_BASE UINT64_C({reg[0]:#x})\n#define SHENG_GPU_SMMU_BYTES {reg[1]}u\n#define SHENG_GPU_SMMU_GPU_STREAMS 2u\n#define SHENG_GPU_SMMU_GMU_SID 5u\nstatic const uint16_t sheng_gpu_smmu_sids[2]={{0,1}};\n')
report=dict(device='b5q',dtb_sha256=hashlib.sha256(a.dtb.read_bytes()).hexdigest(),catalog_sha256=expected,bins=records,gmu_opps=gmu_opps,bcms=policies,command_db=dict(base=address,bytes=bytes_),bin_selection='default exact intersection of both Samsung tables through615MHz; actual SKU binding required before selecting680/719MHz bin policy',GPU_streams_source='Samsung FDT gfx3d_user SID0, gfx3d_lpac SID1, secure SID2; only nonsecure0/1 used',no_hardware_IO=True)
(a.out/'votes-source-report.json').write_text(json.dumps(report,indent=2)+'\n');print('Derived both Samsung GPU bins, GMU votes, command-db and shared SMMU parameters')
