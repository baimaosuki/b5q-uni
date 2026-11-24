#!/usr/bin/env python3
"""Check whether retained original inputs prove a separate DP scanout mapping."""
from pathlib import Path
import hashlib,json,re,struct
R=Path(__file__).resolve().parents[2]
files={
 'selected_DisplayDxe':R/'uefi-b5q/Binaries/b5q/QcomPkg/Drivers/DisplayDxe/DisplayDxe.patched.efi',
 'b5q_dts':R/'uefi-b5q/Resources/DTBs/b5q.dts',
 'original_IORT':R/'artifacts/b5q-p4-work/stock-IORT/reference.dts',
 'original_msm_drm':R/'sources/twrp-b5q/recovery/root/lib/modules/msm_drm.ko',
 'matching_sde_kms':R/'artifacts/b5q-p5-work/source-extra/qcom/opensource/display-drivers/msm/sde/sde_kms.c',
 'matching_sde_hw_top':R/'artifacts/b5q-p5-work/source-extra/qcom/opensource/display-drivers/msm/sde/sde_hw_top.c',
 'matching_sde_plane':R/'artifacts/b5q-p5-work/source-extra/qcom/opensource/display-drivers/msm/sde/sde_plane.c',
 'existing_MemoryMapLib':R/'uefi-b5q/Platforms/Samsung/b5qPkg/Library/MemoryMapLib/MemoryMapLib.c',
}
raw=files['selected_DisplayDxe'].read_bytes()
assert hashlib.sha256(raw).hexdigest()=='51babf469c8a6753082b1a84c677a21ed4ddca64ac98ca939a3bb42a614e8070'
assert raw[:2]==b'MZ';pe=struct.unpack_from('<I',raw,0x3c)[0];assert raw[pe:pe+4]==b'PE\0\0'
sections=struct.unpack_from('<H',raw,pe+6)[0];optional=struct.unpack_from('<H',raw,pe+20)[0]
def at(rva,n):
 for i in range(sections):
  off=pe+24+optional+40*i;vsize,va,size,where=struct.unpack_from('<4I',raw,off+8)
  if va<=rva and rva+n<=va+size:return raw[where+rva-va:where+rva-va+n]
 raise ValueError(hex(rva))
# Actual selected entry returns success without making the orphan HAL call.
assert at(0x19b18,8)==bytes.fromhex('e0031f2ac0035fd6')
call,=struct.unpack('<I',at(0x133cc,4));assert call>>26==0x25
disp=call&0x3ffffff;disp=disp-(1<<26)if disp&(1<<25)else disp
assert 0x133cc+disp*4==0x19b18
dts=files['b5q_dts'].read_text()
def node(text,name):
 start=text.index(name+' {');brace=text.index('{',start);depth=0
 for i in range(brace,len(text)):
  depth+=(text[i]=='{')-(text[i]=='}')
  if not depth:return text[start:i+1]
mdp=node(dts,'qcom,mdss_mdp@ae00000')
assert '"sid_phys"'not in mdp
assert 'reg-names = "mdp_phys", "vbif_phys", "regdma_phys", "ipcc_reg";'in mdp
unsec=node(dts,'qcom,smmu_sde_unsec_cb');assert 'iommus = <0x42 0x1c00 0x02>;'in unsec
iort=node(files['original_IORT'].read_text(),'NAMEDNODE_Display')
rows=[]
for entry in re.findall(r'SIDMappings_\d+\s*\{([^}]+)\}',iort):
 def val(key):return int(re.search(key+r'\s*=\s*<(0x[0-9a-f]+)>',entry)[1],16)
 encoded=val('OutputBase');rows.append(dict(arid=hex(val('InputBase')),encoded=hex(encoded),sid=hex(encoded&65535),mask=hex(encoded>>16)))
assert len(rows)==4 and rows[0]['sid']=='0x1c00'and rows[0]['mask']=='0x2'and rows[3]['sid']=='0x1c04'
kms=files['matching_sde_kms'].read_text();top=files['matching_sde_hw_top'].read_text();plane=files['matching_sde_plane'].read_text()
assert 'msm_ioremap(platformdev, "sid_phys", "sid_phys")'in kms and 'sde_kms->sid = NULL;'in kms
sid=top[top.index('void sde_hw_set_sspp_sid('):top.index('static void sde_hw_program_cwb_ppb_ctrl(')]
assert 'if (!sid)\n\t\treturn;'in sid and 'SDE_REG_WRITE(&sid->hw, offset, vm << 2);'in sid
assert 'sde_hw_set_sspp_sid(sde_kms->hw_sid, psde->pipe, vm, sde_kms->catalog);'in plane
result=dict(
 complete_P5=False,hardware_verified=False,separate_DP_DMA_mapping_proven=False,
 inputs={name:dict(path=str(p.relative_to(R)),bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest())for name,p in files.items()},
 selected_DisplayDxe=dict(caller_RVA='0x133cc',target_RVA='0x19b18',actual_words=['mov w0,wzr','ret'],
  orphan_HAL_body='0x19b20..0x19bd4; not executed by the selected caller; does not prove a retained identity/bypass mapping'),
 display_IORT=rows,
 mdp_reg_names=['mdp_phys','vbif_phys','regdma_phys','ipcc_reg'],sid_phys_present=False,
 source_route='sde_plane_set_sid -> sde_hw_set_sspp_sid; no write when hw_sid absent; sid_phys is optional and absent in original b5q node',
 existing_primary_stream=dict(sid='0x1c00',mask='0x2',must_preserve=True),
 candidate_only=dict(arid='0x03000003',sid='0x1c04',mask='0x2',routable_by_b5q_display='unknown'),
 reservation_is_not_mapping='0xb8000000+0x02b00000 is a splash reservation, not proof of unused GOP allocation or DP DMA coverage',
 required='A source-qualified independently routable DP fetch stream and retained firmware mapping, or a qualified nonoverlapping scanout allocation within an actually mapped display range',
 prohibited_assumptions=['copy another board sid_phys address','reconfigure the live primary Display domain/bank','scan apps_smmu at XNU EL1','infer whole-RAM identity from a firmware success-return patch'],
 unresolved_software=['native complete hardware ownership/glue','external IOMFB scanout and hotplug/lid integration','final P5 link closure/CI/ESP'],
 device_access=False,EL1_apps_smmu_access=False)
out=R/'UniXNU-b5q/reports/p5-display-dma-inputs.json';out.write_text(json.dumps(result,indent=2)+'\n')
print('PASS original static input checks; separate DP DMA route/mapping remains UNKNOWN. P5 release gate stays closed.')
