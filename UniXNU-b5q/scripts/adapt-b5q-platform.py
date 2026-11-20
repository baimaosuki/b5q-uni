from pathlib import Path
import hashlib,json,re,sys
R=Path(__file__).resolve().parents[2];D=R/'UniXNU-b5q';ref=R/'sources/UniXNU-sheng/package';out=D/'package';inputs=out/'Sm8550Inputs'
sys.path.insert(0,str(R/'UniXNU/scripts'));from unixnu.devicetree import read_fdt,registers
nodes=list(read_fdt((R/'b5q-runtime.fdt').read_bytes()).walk())
# Confirm all physical reservations and windows against the b5q runtime input.
zap=next(n for n in nodes if n.name=='gpu_micro_code_region@9b09a000');assert registers(zap)==[(0x9b09a000,0x2000)]
gcc=next(n for n in nodes if n.name in ['qcom,gcc@100000','clock-controller@100000']);assert registers(gcc)[0][0]==0x100000
gpucc=next(n for n in nodes if 'gpucc@3d90000' in n.name or n.name=='clock-controller@3d90000');assert registers(gpucc)[0][0]==0x3d90000
# Samsung downstream confirms the reference's GPUCC PLL constants, RCG rates and branch offsets.
clock=R/'artifacts/b5q-runtime-v19-work/samsung-reference/drivers/clk/qcom/gpucc-kalama.c';c=clock.read_text().lower()
for v in ['0x20485699','0x00182261','0x82aa299c','0x9318','0x93ec','0x913c','0x911c','0x7000']:
 assert v in c,v
assert registers(next(n for n in nodes if n.name=='qcom,gdsc@3d99108'))==[(0x3d99108,4)]
assert registers(next(n for n in nodes if n.name=='qcom,gdsc@3d9905c'))==[(0x3d9905c,4)]
assert registers(next(n for n in nodes if n.name=='syscon@3d9953c'))==[(0x3d9953c,4)]
for name,sid in [('gfx3d_user',0),('gfx3d_lpac',1),('gfx3d_secure',2)]:assert next(n for n in nodes if n.name==name).cells('iommus')==[224,sid,0]
for v in ['.l = 0x1e','.l = 0x16','.alpha = 0xbaaa','.alpha = 0xeaaa','f(220000000','f(200000000']:assert v in c,v
# The common policy is the exact intersection of both Samsung tables. Runtime
# DVFS never assumes a SKU or enables the 719MHz bin without its binding.
votes=json.loads((inputs/'votes-source-report.json').read_text());bins=list(votes['bins'].values());common=[e for e in bins[0]['opps']if e in bins[1]['opps']];assert len(common)>=8 and common[0]['hz']==0
text=(inputs/'B5qGmuVotes-1.h').read_text()
for row in bins[1]['opps']:
 if row not in common:text=text.replace('{'+','.join(str(int(row[k]))for k in ['hz','level','kbps','acd_present','acd'])+'},\n','')
text=text.replace('#define SHENG_GPU_OPPS 10u',f'#define SHENG_GPU_OPPS {len(common)}u')
bw=sorted({r['kbps']for r in common})
text=re.sub(r'#define SHENG_GPU_BANDWIDTHS \d+u',f'#define SHENG_GPU_BANDWIDTHS {len(bw)}u',text)
text=re.sub(r'sheng_gpu_bandwidths\[\]=\{[^}]+\}', 'sheng_gpu_bandwidths[]={'+','.join(map(str,bw))+'}',text)
(inputs/'B5qGmuVotes-common.h').write_text(text)
(inputs/'ShengGmuVotesSource.h').write_text('#pragma once\n#include "B5qGmuVotes-common.h"\n')
rows=common; (inputs/'B5qGpuRates.h').write_text('#pragma once\nstatic constexpr uint32_t kGpuMHz[]={'+','.join(str(e['hz']//1000000)for e in rows)+'};\nstatic constexpr unsigned kGpuTop='+str(len(rows)-1)+';\n')
(out/'B5qGmuVotes.c').write_text('/* Board policy algorithm from UniXNU-sheng; tables are Samsung b5q. */\n'+(ref/'ShengGmuVotes.c').read_text())
(out/'B5qGpuPowerBoard.h').write_text('// Shared SM8550 clock/power sequence; checked against Samsung gcc/gpucc-kalama.\n// b5q provenance: reports/peripheral-inputs-v19.json and shared-platform-v19.json.\n'+(ref/'GpuPowerBoard.h').read_text())
s=(ref/'GpuPowerProbe.cpp').read_text();changes=[]
def replace(old,new):
 global s
 n=s.count(old);assert n>0,old;s=s.replace(old,new);changes.append({'from':old,'to':new,'occurrences':n})
replace('#include "BootLatencyTrace.h"','#include "B5qGpuTrace.h"\n#include "B5qGpuFirmware.h"\n#include "B5qPeripheralHardware.h"\n#include "ShengGmuSource.h"')
replace('#include "GpuPowerBoard.h"','#include "B5qGpuPowerBoard.h"')
# Runtime firmware was authenticated in /chosen by the same inventory hash;
# no weak-empty firmware defaults or Xiaomi firmware are used by this path.
for old,new in [('native_adreno_sqe_firmware_image','b5q_sqe_firmware_image'),('native_adreno_zap_image','b5q_zap_image'),('native_adreno_firmware_image','b5q_gmu_firmware_image')]:replace(old,new)
s=re.sub(r'extern "C" const uint8_t b5q_(?:sqe_firmware_image|zap_image|gmu_firmware_image)\[\] __attribute__\(\(weak\)\);\n','',s)
s=re.sub(r'extern "C" const uint64_t b5q_(?:sqe_firmware_image|zap_image|gmu_firmware_image)_size __attribute__\(\(weak\)\);\n','',s)
s=s.replace('&b5q_sqe_firmware_image_size','b5q_sqe_firmware_image_size').replace('&b5q_zap_image_size','b5q_zap_image_size').replace('!&b5q_gmu_firmware_image_size','!b5q_gmu_firmware_image_size')
replace('0x6a000','SHENG_GMU_CORE_GPU_DELTA')
replace('constexpr uint64_t kGmuPhys[3] = {0x03d6a000, 0x03d50000, 0x03d9e000};','constexpr uint64_t kGmuPhys[3] = {B5qHardware::gmuBase, 0x03d50000, 0x03d9e000};')
replace('constexpr uint64_t kGmuLen[3] = {0x35000, 0x10000, 0x1000};','constexpr uint64_t kGmuLen[3] = {B5qHardware::gmuBytes, 0x10000, 0x1000};')
replace('constexpr uint64_t kColdPhys[5] = {0x03d6a000, 0x03d50000, 0x0b280000, 0x03d00000, 0x03d9e000};','constexpr uint64_t kColdPhys[5] = {B5qHardware::gmuBase, 0x03d50000, 0x0b280000, 0x03d00000, 0x03d9e000};')
replace('constexpr uint64_t kColdLen[5] = {0x35000, 0x10000, 0x10000, 0x40000, 0x1000};','constexpr uint64_t kColdLen[5] = {B5qHardware::gmuBytes, 0x10000, 0x10000, 0x40000, 0x1000};')
replace('constexpr uint32_t kGpuMHz[9] = {0, 220, 295, 348, 401, 475, 550, 615, 680};\nconstexpr unsigned kGpuTop = 8;','#include "B5qGpuRates.h"')
# Preserve the reference's timing governor but size diagnostic counters for
# actual Samsung common OPP count, rather than silently dropping the top OPP.
replace('native_gpu_dcvs[15]','native_gpu_dcvs[7 + kGpuTop]')
# Existing diagnostic rows go into the persistent console journal immediately.
replace('void setRow(unsigned slot, const char *text) {','void setRow(unsigned slot, const char *text) {\n    IOLog("B5qGpu: stage=%x row=%u %s\\n", native_gpu_power_stage, slot, text);')
replace('extern char boot_progress_ext_wide[2][112];','char b5q_gpu_progress_wide[2][112];')
replace('boot_progress_ext_wide','b5q_gpu_progress_wide')
# Local row storage only: do not overlay or depend on an absent custom boot UI.
replace('extern char boot_progress_ext[8][48];','char b5q_gpu_progress[8][48];')
replace('boot_progress_ext[slot]','b5q_gpu_progress[slot]')
replace('extern "C" void sheng_gpu_power_probe(void) {','extern "C" void b5q_gpu_start(void) {')
replace('void probeThread(void *, wait_result_t) {','void probeThread(void *, wait_result_t) {\n    if (!b5q_gpu_firmware_bind()) {IOLog("B5qGpu: stage=Samsung-firmware-invalid\\n"); thread_terminate(current_thread()); return;}')
# Retain native code/ownership checks; no synthetic power/DMA handoff record.
s='// Samsung b5q adaptation of the pinned shared SM8550 reference pipeline.\n// See reports/shared-platform-v19.json for exact replacements and source hashes.\n'+s
s=s.replace('extern volatile uint32_t native_hid_input_events[8] __attribute__((weak_import));','// No b5q touch observer is linked; the optional governor boost has no events.\nvolatile uint32_t native_hid_input_events[8] = {};').replace('uint32_t touches = &native_hid_input_events ? native_hid_input_events[6] : 0;','uint32_t touches = native_hid_input_events[6];').replace('boostAbs && &native_hid_input_events &&','boostAbs &&')
(out/'B5qGpu.cpp').write_text(s)
meta={'upstream_commit':'c8f92b208068eeaa4cd2b0f592671f04ee70076e','reference_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest()for p in [ref/'GpuPowerProbe.cpp',ref/'GpuPowerBoard.h',ref/'ShengGmuVotes.c']},'Samsung_clock_sha256':hashlib.sha256(clock.read_bytes()).hexdigest(),'runtime_fdt_sha256':hashlib.sha256((R/'b5q-runtime.fdt').read_bytes()).hexdigest(),'replacements':changes,'OPP_policy':'Exact intersection of both b5q GPU tables; includes 124.8..615MHz,680/719MHz remain bin-specific,not an asserted active SKU','firmware_transport':'original Samsung bytes from official ADT properties, complete SHA256 validation before GPU MMIO','GPU_SMMU_ownership':'reference exclusive unused SMR gate; no apps_smmu accesses','hardware_tested':False}
(D/'reports/shared-platform-v19.json').write_text(json.dumps(meta,indent=2)+'\n');print('Adapted shared platform; no generated firmware images included')
